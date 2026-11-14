"""docs/SPEC-v5.9-reliability-under-load.md T1/T2 at REAL speed: N customers write the normal order flow at the
same moment; the real worker + the real sender loop at the real send limits (1 msg / 3 s, 20 / min) answer them
through a FAKE Telegram client. Its own throwaway database (<db>_chaos, made fresh each run): never the live
database, never the real Telegram session.

Usage: nice -n 19 .venv/bin/python -m scripts.load_test [--customers 50] [--speed 1]
Prints time to first / last reply (p50 / p90 / max), sends per minute, and the capacity statement.
"""
import os

if __name__ == "__main__":  # its own database, chosen before app.core.db creates the engine
    from app.core.config import get_settings as _gs

    os.environ["DB_NAME"] = _gs().db_name + "_chaos"
    os.environ["AI_PROVIDER"] = "off"
    _gs.cache_clear()

import argparse
import json
import time

import pytest


def fresh_database() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from app.core.config import BASE_DIR, get_settings
    from app.core.db import engine

    name = get_settings().db_name
    assert name.endswith("_chaos"), "the load test only ever drops its own database"
    admin = create_engine(get_settings().database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{name}"'))
        c.execute(text(f'ALTER DATABASE "{name}" SET synchronous_commit = off'))
    admin.dispose()
    command.upgrade(Config(str(BASE_DIR / "alembic.ini")), "head")


def main() -> int:
    import logging

    from tests.chaos.harness import median, open_shop, percentile, run_flows, scalar, wait_until

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--customers", type=int, default=50)
    parser.add_argument("--speed", type=float, default=1.0, help="send-limiter clock speed (1 = real time)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    fresh_database()
    started = time.monotonic()
    with pytest.MonkeyPatch.context() as mp:
        env = open_shop(mp, speed=args.speed, short_timers=False)
        try:
            uids = env.customers(args.customers)
            env.listener.start()
            env.start_worker()
            result = run_flows(env, uids, within=3600)
            wait_until(lambda: not scalar("SELECT count(*) FROM outbox WHERE status IN ('queued', 'sending')"), 3600, 1)
        finally:
            env.close()
    took = time.monotonic() - started
    firsts = [r["first"] for r in result.values() if r["first"] is not None]
    lasts = [r["last"] for r in result.values() if r["last"] is not None]
    missing = sum(len(r["missing"]) for r in result.values())
    sends = len(env.fake.sent)
    per_min = env.fake.max_per_minute()
    numbers = {"customers": args.customers, "speed": args.speed, "seconds": round(took),
               "sends": sends, "missing_replies": missing, "max_sends_per_minute": per_min,
               "first_reply_s": {"p50": round(median(firsts), 1), "p90": round(percentile(firsts, 90), 1),
                                 "max": round(max(firsts), 1)},
               "last_reply_s": {"p50": round(median(lasts), 1), "p90": round(percentile(lasts, 90), 1),
                                "max": round(max(lasts), 1)}}
    print(json.dumps(numbers, indent=1))
    per_customer = sends / args.customers
    print(f"Capacity: about {60 / 3 / per_customer:.1f} customers per minute at the current limits "
          f"(each full order flow needs ~{per_customer:.1f} messages; 20 messages / min, 1 per 3 s).")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
