"""Live listener: saves new incoming private messages as they arrive.

Usage: .venv/bin/python -m app.listener.main
Logs only ids and counts, never message text or credentials.
"""
import asyncio
import logging
import sys

from telethon import events

from app.core.db import SessionLocal
from app.core.heartbeat import beat
from app.listener.client import make_client, secure_session_file
from app.listener.save import IncomingMessage, from_telethon, save_message

log = logging.getLogger("listener")
HEARTBEAT_SECONDS = 60


def _save(msg: IncomingMessage) -> bool:
    with SessionLocal.begin() as session:
        return save_message(session, msg)


async def main() -> None:
    client = make_client()
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Not logged in. Run: .venv/bin/python -m app.listener.login")
    secure_session_file()

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def on_message(event: events.NewMessage.Event) -> None:
        try:
            msg = from_telethon(event.message, await event.get_sender())
            if msg is None:
                return
            inserted = await asyncio.to_thread(_save, msg)
            log.info("%s chat=%s msg=%s", "saved" if inserted else "duplicate",
                     msg.external_chat_id, msg.external_message_id)
        except Exception:
            # Never let one bad message stop the listener; import_history fills gaps.
            log.exception("failed to handle message id=%s", event.message.id)

    async def heartbeat() -> None:
        while True:
            if client.is_connected():
                try:
                    await asyncio.to_thread(beat, "listener", "connected")
                except Exception:
                    log.exception("heartbeat failed")
            await asyncio.sleep(HEARTBEAT_SECONDS)

    log.info("listening for new private messages")
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        # Returns when the connection is lost for good; the process then exits and
        # systemd restarts it (catch_up=True fetches what arrived meanwhile).
        await client.run_until_disconnected()
    finally:
        heartbeat_task.cancel()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(main())
