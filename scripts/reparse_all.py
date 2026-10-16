"""Re-parse every stored message with the current rules (after the parser, the
aliases or normalize() change). Adds a new parse_results row only where the outcome
or parser version changed; old rows stay as history. Human edits and AI results are never replaced.

Usage: .venv/bin/python -m scripts.reparse_all [--dry-run]
Prints counts only, never message text.
"""
import argparse
from collections import Counter

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Message
from app.parser.rules import PARSER_VERSION
from app.parser.service import load_aliases, load_full_sizes, load_known_words, load_phrases, parse_message

CHUNK = 500


def reparse_all(dry_run: bool = False) -> Counter:
    stats: Counter = Counter()
    last_id = 0
    with SessionLocal() as session:
        aliases = load_aliases(session)
        full_sizes = load_full_sizes(session)
        known_words = load_known_words(session)
        phrases = load_phrases(session)
    while True:
        session = SessionLocal()
        try:
            messages = list(session.scalars(
                select(Message).where(Message.id > last_id, Message.direction == "in")
                .order_by(Message.id).limit(CHUNK)
            ))
            if not messages:
                return stats
            for message in messages:
                stats[parse_message(session, message, aliases, full_sizes, known_words, phrases)] += 1
            last_id = messages[-1].id
            session.rollback() if dry_run else session.commit()
        finally:
            session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show counts, write nothing")
    args = parser.parse_args()
    stats = reparse_all(args.dry_run)
    mode = "DRY RUN, nothing saved" if args.dry_run else "saved"
    print(f"{mode} ({PARSER_VERSION}): " + ", ".join(
        f"{k}={stats[k]}" for k in ("new", "changed", "unchanged", "human", "ai")))


if __name__ == "__main__":
    main()
