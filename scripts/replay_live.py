"""docs/SPEC-v4.20-automation-goal.md A5 / G4: replay the last 30 days of REAL incoming messages on a COPY of the
live database, through today's pipeline, with sending disabled. Prints numbers, reason counts and message ids
only — never customer text — and writes data/exports/replay_<time>.json (git-ignored). The copy is deleted after.

How: pg_dump the live database -> pg_restore into <db>_replay -> migrate to head -> keep the catalog, prices,
settings, FAQ, templates and learned words, but empty every conversation (messages, orders, replies, AI calls,
payment checks, customers' saved phone / address) -> each customer's incoming messages again, in order, with
the real time gaps (scripts/simulate.py's turn runner: parser, AI, auto mode, silence watchdog, a FAKE Telegram
client — nothing can reach Telegram: no Telethon session is used and the copy has no listener). Our own
hand-typed messages are not replayed (they would pause auto mode; we measure what the bot does alone).
Judged by the strict judge (prices / totals / phones / Order IDs / refund promises), as there are no expected
facts for real messages.

AI: the real provider (cost cap $1 per run, $3 per day), answers cached in data/exports/replay_cassette.json.
Usage: .venv/bin/python -m scripts.replay_live [--days 30] [--ai real|off] [--keep]
Exit 0 = G4 met (>= 85% automatic, 0 wrong).
"""
import os
import sys

if __name__ == "__main__":  # the copy, made before app.core.db creates the engine
    from app.core.config import get_settings as _gs

    LIVE_DB = _gs().db_name
    os.environ["DB_NAME"] = LIVE_DB + "_replay"
    _gs.cache_clear()

import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text

from app.ai import providers
from app.core.config import BASE_DIR, get_settings
from app.core.db import SessionLocal, engine
from app.orders import auto, holding
from scripts import simulate

GOAL_AUTOMATIC = 0.85
MAX_GAP = timedelta(days=3)
KEEP_TABLES = {"alembic_version", "products", "product_aliases", "product_prices", "product_costs", "payment_methods",
               "reply_templates", "app_settings", "faq_entries", "users", "learned_patterns", "service_heartbeats",
               "customers", "vial_costs"}
CASSETTE = simulate.EXPORTS / "replay_cassette.json"


def copy_live(live: str, replay: str) -> None:
    s = get_settings()
    assert replay.endswith("_replay") and replay != live, "only ever replaces the _replay copy"
    admin = create_engine(s.database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{replay}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{replay}"'))
    admin.dispose()
    env = {**os.environ, "PGPASSWORD": s.db_password.get_secret_value()}
    conn = ["-h", s.db_host, "-p", str(s.db_port), "-U", s.db_user]
    dump = subprocess.Popen(["pg_dump", *conn, "-d", live, "-Fc", "--no-owner"], stdout=subprocess.PIPE, env=env)
    subprocess.run(["pg_restore", *conn, "-d", replay, "--no-owner"], stdin=dump.stdout, env=env, check=True)
    if dump.wait() != 0:
        raise SystemExit("pg_dump of the live database failed")
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(BASE_DIR / "alembic.ini")), "head")


def drop_copy(replay: str) -> None:
    engine.dispose()
    admin = create_engine(get_settings().database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{replay}" WITH (FORCE)'))
    admin.dispose()


def take_messages(days: int) -> list[tuple]:
    """(live message id, customer id, Telegram user id, kind, text, received_at) of the window, oldest first."""
    with SessionLocal() as s:
        return [tuple(r) for r in s.execute(text(
            "SELECT m.id, m.customer_id, c.external_user_id, m.kind, coalesce(m.raw_text, ''), m.received_at "
            "FROM messages m JOIN customers c ON c.id = m.customer_id WHERE m.direction = 'in' AND NOT c.ignored "
            "AND m.received_at >= now() - make_interval(days => :d) ORDER BY m.received_at, m.id"), {"d": days})]


def wipe_conversations() -> None:
    with SessionLocal.begin() as s:
        tables = [t for t in s.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                  if t not in KEEP_TABLES]
        s.execute(text("SET LOCAL session_replication_role = replica"))
        s.execute(text("; ".join(f'DELETE FROM "{t}"' for t in tables)))
        s.execute(text("SET LOCAL session_replication_role = DEFAULT"))
        s.execute(text("UPDATE customers SET phone = NULL, address = NULL, address_parts = NULL, "
                       "auto_resumed_at = NULL, resume_line_at = NULL"))
        s.execute(text("UPDATE outbox SET status = 'cancelled' WHERE status IN ('queued', 'sending')"))  # none left


def approve_screenshots(fake) -> None:
    """In the COPY only: what the admin does in Payments (live, real payments are never approved by the
    system). Without it every later message of that customer would meet "screenshot being checked"."""
    from app.models import Order, PaymentCheck, User
    from app.orders import payments
    from app.replies import templates as replies

    with SessionLocal.begin() as s:
        admin = s.scalar(text("SELECT id FROM users ORDER BY id LIMIT 1"))
        user = s.get(User, admin) if admin else None
        for check in s.scalars(text("SELECT id FROM payment_checks WHERE decision = 'pending'")).all():
            check = s.get(PaymentCheck, check)
            order = s.get(Order, check.order_id)
            if user is None or order.status != "photo_received":
                continue
            try:
                payments.approve(s, check, payments.Form(f"REPLAY{check.id}", order.total_mmk, None), user,
                                 replies.load(s), confirmed=True)
            except payments.PaymentError:
                pass  # e.g. no valid address: stays for a person, as live
    simulate._deliver(fake)


def _private(problem: str) -> str:
    """No customer data in the report: long numbers and quoted pieces go."""
    return re.sub(r"\d{5,}", "[n]", re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", problem))


def replay(messages: list[tuple], provider) -> dict:
    by_customer: dict[int, list[tuple]] = {}
    for m in messages:
        by_customer.setdefault(m[1], []).append(m)
    fake = simulate.FakeTelegram()
    counts, reasons, ids = Counter(), Counter(), {"wrong": [], "silent": [], "person": []}
    providers.use(provider)
    cap, auto.DAILY_CAP = auto.DAILY_CAP, 100_000
    try:
        for customer_id, rows in by_customer.items():
            chat = simulate.Chat(0)
            chat.user, chat.customer_id = rows[0][2], customer_id
            said, last = [], None
            for live_id, _, _, kind, body, at in rows:
                if last is not None and at > last:
                    chat.travel(min(at - last, MAX_GAP))
                last = at
                turn = simulate.Turn(0, [body], {"reply": "any"})
                said.append(body)
                simulate.run_turn(chat, turn, fake, kind if kind in ("text", "photo") else "other")
                approve_screenshots(fake)  # the admin's part, in the copy only
                simulate.judge(chat, turn, said)
                small = kind == "text" and holding.is_small_talk(body)
                counts["messages"] += 1
                if turn.wrong:
                    counts["wrong"] += 1
                    ids["wrong"].append(live_id)
                    reasons["WRONG: " + _private(next(p for p in turn.problems if p.startswith("WRONG")))] += 1
                if turn.got == "auto" or (turn.got == "none" and small):
                    counts["automatic"] += 1
                elif turn.got == "person":
                    counts["person"] += 1
                    ids["person"].append(live_id)
                    reasons["person: " + _private(turn.reason.split(" | ")[0] or "holding reply")] += 1
                else:
                    counts["silent"] += 1
                    ids["silent"].append(live_id)
                    reasons["silent: " + _private(turn.reason.split(" | ")[0])] += 1
            simulate.finish(chat)
    finally:
        providers.use(None)
        auto.DAILY_CAP = cap
    total = counts["messages"] or 1
    return {"messages": counts["messages"], "automatic": round(counts["automatic"] / total, 4),
            "wrong": counts["wrong"], "silent": counts["silent"], "person": counts["person"],
            "customers": len(by_customer), "reasons": dict(reasons.most_common()), "message_ids": ids}


def main() -> int:
    import logging

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--ai", choices=("real", "off"), default="real")
    parser.add_argument("--keep", action="store_true", help="keep the _replay copy (to look at it)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    replay_db = get_settings().db_name
    copy_live(LIVE_DB, replay_db)
    try:
        messages = take_messages(args.days)
        wipe_conversations()
        cassette = None
        if args.ai == "real":
            real = providers.get()
            if real is None:
                print("AI is off / no OPENAI_API_KEY: run with --ai off")
                return 2
            simulate.EXPORTS.mkdir(parents=True, exist_ok=True)
            cassette = simulate.CassetteProvider(CASSETTE, real=real)  # git-ignored cache (customer-derived)
        result = replay(messages, cassette)
        if cassette:
            cassette.save()
            simulate._add_spent(cassette.spent)
            result["ai_cost_usd"] = round(cassette.spent, 4)
    finally:
        if not args.keep:
            drop_copy(replay_db)
    result["goal_met"] = result["automatic"] >= GOAL_AUTOMATIC and result["wrong"] == 0
    out = simulate.EXPORTS / f"replay_{datetime.now(UTC):%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(result, indent=1))
    print(f"replayed {result['messages']} messages of {result['customers']} customers: automatic "
          f"{result['automatic']:.1%}, wrong {result['wrong']}, silent {result['silent']}, person {result['person']}"
          f"; AI ${result.get('ai_cost_usd', 0):.4f}")
    for reason, n in result["reasons"].items():
        print(f"  {n} × {reason}")
    print(f"message ids: {result['message_ids']}")
    print("G4 MET" if result["goal_met"] else "G4 not met", f"(report: {out.relative_to(BASE_DIR)})")
    return 0 if result["goal_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
