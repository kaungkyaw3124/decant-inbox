"""Parser worker: parses messages that have no current parse result yet.

Talks to the other services only through the database, so it can restart at any
time; on start it simply catches up on everything still unparsed.

Usage: .venv/bin/python -m app.parser.worker [--once]
Logs only ids and counts, never message text.
"""
import argparse
import logging
import time

from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.core.heartbeat import beat
from app.models import Message
from app.orders import auto, cart
from app.parser.rules import PARSER_VERSION
from app.parser.service import load_aliases, load_full_sizes, parse_message, unparsed_message_ids
from scripts.reparse_all import reparse_all

log = logging.getLogger("parser")
BATCH = 200
HEARTBEAT_SECONDS = 30
HOUSEKEEPING_SECONDS = 600
_failed: set[int] = set()  # retried after a restart, so one bad row cannot block the queue


def run_batch() -> int:
    """Parse up to BATCH unparsed messages. Returns how many were parsed."""
    with SessionLocal() as session:
        ids = unparsed_message_ids(session, BATCH, _failed)
        if not ids:
            return 0
        aliases = load_aliases(session)  # reloaded per batch: dashboard may add aliases
        full_sizes = load_full_sizes(session)
    done = 0
    for message_id in ids:
        try:
            with SessionLocal.begin() as session:
                parse_message(session, session.get(Message, message_id), aliases, full_sizes)
            done += 1
        except IntegrityError:
            log.info("message=%s already parsed by another process", message_id)
        except Exception:
            _failed.add(message_id)
            log.exception("failed to parse message=%s", message_id)
    return done


def catalog_fingerprint() -> int:
    with SessionLocal() as session:
        return hash((frozenset(load_aliases(session)), frozenset(load_full_sizes(session).items())))


def reparse_if_catalog_changed(last: int | None) -> int:
    """Products/aliases edited in the dashboard (or re-seeded) -> re-parse everything.
    Also runs once at start, to catch changes made while the worker was down."""
    current = catalog_fingerprint()
    if current != last:
        stats = reparse_all()
        log.info("catalog changed, re-parsed: %s", dict(stats))
    return current


def housekeeping() -> None:
    """Carts idle for 3 days -> abandoned (DB-only chore; this worker runs 24/7 anyway)."""
    with SessionLocal.begin() as session:
        abandoned = cart.abandon_idle(session)
    if abandoned:
        log.info("abandoned %d idle carts", abandoned)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="parse what is pending, then exit")
    # 1 s: auto replies should go out ~3 s after the customer's message (Step 4d)
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between polls")
    args = parser.parse_args()

    log.info("parser worker started (%s)", PARSER_VERSION)
    fingerprint = None
    last_beat = last_chores = 0.0
    while True:
        if time.monotonic() - last_chores >= HOUSEKEEPING_SECONDS:
            housekeeping()
            last_chores = time.monotonic()
        if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
            beat("parser", PARSER_VERSION)
            last_beat = time.monotonic()
        fingerprint = reparse_if_catalog_changed(fingerprint)
        parsed = run_batch()
        if parsed:
            log.info("parsed %d messages", parsed)
            continue  # there may be more
        auto.run_once()  # auto mode (does nothing while it is switched off)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
