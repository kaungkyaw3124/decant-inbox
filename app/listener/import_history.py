"""Import private messages (incoming and our outgoing, photo metadata) from the last N days. Idempotent: re-running
skips messages already saved, so it also fills gaps after listener downtime.

Usage: .venv/bin/python -m app.listener.import_history --days 30 [--dry-run]
"""
import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from app.core.db import SessionLocal
from app.listener.client import make_client, secure_session_file
from app.listener.save import from_telethon, is_customer_chat, save_message


async def run(days: int, dry_run: bool) -> None:
    client = make_client()
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Not logged in. Run: .venv/bin/python -m app.listener.login")
    secure_session_file()
    cutoff = datetime.now(UTC) - timedelta(days=days)
    totals = {"chats": 0, "seen": 0, "kept": 0, "new": 0}
    try:
        async for dialog in client.iter_dialogs():  # all folders, incl. archived
            user = dialog.entity
            if not dialog.is_user or not is_customer_chat(user):
                continue
            if dialog.date and dialog.date < cutoff:
                continue  # no activity in the window
            batch = []
            async for message in client.iter_messages(dialog, offset_date=cutoff, reverse=True):
                totals["seen"] += 1
                msg = from_telethon(message, user)
                if msg is not None:
                    batch.append(msg)
            if not batch:
                continue
            totals["chats"] += 1
            totals["kept"] += len(batch)
            if not dry_run:
                with SessionLocal.begin() as session:
                    totals["new"] += sum(save_message(session, m) for m in batch)
            print(f"chat {user.id}: {len(batch)} messages")
    finally:
        await client.disconnect()
    mode = "DRY RUN, nothing saved" if dry_run else "saved"
    print(f"{mode}: {totals['chats']} chats, {totals['seen']} messages scanned, "
          f"{totals['kept']} kept, {totals['new']} new rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = parser.parse_args()
    asyncio.run(run(args.days, args.dry_run))


if __name__ == "__main__":
    main()
