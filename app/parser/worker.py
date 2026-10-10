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
from app.models import Message
from app.parser.rules import PARSER_VERSION
from app.parser.service import load_aliases, parse_message, unparsed_message_ids
from scripts.reparse_all import reparse_all

log = logging.getLogger("parser")
BATCH = 200
_failed: set[int] = set()  # retried after a restart, so one bad row cannot block the queue


def run_batch() -> int:
    """Parse up to BATCH unparsed messages. Returns how many were parsed."""
    with SessionLocal() as session:
        ids = unparsed_message_ids(session, BATCH, _failed)
        if not ids:
            return 0
        aliases = load_aliases(session)  # reloaded per batch: dashboard may add aliases
    done = 0
    for message_id in ids:
        try:
            with SessionLocal.begin() as session:
                parse_message(session, session.get(Message, message_id), aliases)
            done += 1
        except IntegrityError:
            log.info("message=%s already parsed by another process", message_id)
        except Exception:
            _failed.add(message_id)
            log.exception("failed to parse message=%s", message_id)
    return done


def catalog_fingerprint() -> int:
    with SessionLocal() as session:
        return hash(frozenset(load_aliases(session)))


def reparse_if_catalog_changed(last: int | None) -> int:
    """Products/aliases edited in the dashboard (or re-seeded) -> re-parse everything.
    Also runs once at start, to catch changes made while the worker was down."""
    current = catalog_fingerprint()
    if current != last:
        stats = reparse_all()
        log.info("catalog changed, re-parsed: %s", dict(stats))
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="parse what is pending, then exit")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
    args = parser.parse_args()

    log.info("parser worker started (%s)", PARSER_VERSION)
    fingerprint = None
    while True:
        fingerprint = reparse_if_catalog_changed(fingerprint)
        parsed = run_batch()
        if parsed:
            log.info("parsed %d messages", parsed)
            continue  # there may be more
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
