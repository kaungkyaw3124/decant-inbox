"""Live listener: saves new private messages (incoming and our own outgoing) as they
arrive, and runs the outbox sender + photo downloads (app/listener/sender.py), because
only one process may use the Telegram session.

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
from app.listener import sender
from app.listener.save import ChatMessage, from_telethon, is_customer_chat, save_message

log = logging.getLogger("listener")
HEARTBEAT_SECONDS = 60
SAVE_RETRIES = (0.5, 1.0, 2.0)  # docs/SPEC-v5.9 B2: the database may be gone for a moment
GAP_FILL_SECONDS = 300.0
GAP_CHATS, GAP_MESSAGES = 30, 30


def _save(msg: ChatMessage) -> bool:
    with SessionLocal.begin() as session:
        return save_message(session, msg)


async def save_with_retry(msg: ChatMessage) -> bool:
    """Saved (True) / already there (False). Raises after the retries; fill_gaps() saves it later."""
    for delay in (*SAVE_RETRIES, None):
        try:
            return await asyncio.to_thread(_save, msg)
        except Exception:
            if delay is None:
                raise
            log.warning("save failed chat=%s msg=%s, retry in %ss", msg.external_chat_id, msg.external_message_id, delay)
            await asyncio.sleep(delay)


async def on_new_message(message, chat) -> None:
    """A new private message (in or out) from Telegram."""
    try:
        msg = from_telethon(message, chat)
        if msg is None:
            return
        inserted = await save_with_retry(msg)
        log.info("%s %s chat=%s msg=%s", "saved" if inserted else "duplicate", msg.direction,
                 msg.external_chat_id, msg.external_message_id)
    except Exception:
        # Never let one bad message stop the listener; fill_gaps() saves it within 5 minutes.
        log.exception("failed to handle message id=%s", message.id)


async def fill_gaps(client) -> int:
    """docs/SPEC-v5.9 B2: read (read-only) the last GAP_MESSAGES messages of the GAP_CHATS most recently active
    private chats and save the missing ones (same idempotent save). Returns how many were new."""
    new = 0
    for dialog in await client.get_dialogs(limit=GAP_CHATS):
        user = dialog.entity
        if not dialog.is_user or not is_customer_chat(user):
            continue
        for message in reversed(await client.get_messages(user, limit=GAP_MESSAGES)):  # oldest first
            msg = from_telethon(message, user)
            if msg is not None and await save_with_retry(msg):
                new += 1
    if new:
        log.warning("gap fill: %d missed messages saved", new)
    return new


async def fill_gaps_forever(client, every: float = GAP_FILL_SECONDS) -> None:
    """At start and every `every` seconds."""
    while True:
        if client.is_connected():
            try:
                await fill_gaps(client)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("gap fill failed")
        await asyncio.sleep(every)


async def main() -> None:
    client = make_client()
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Not logged in. Run: .venv/bin/python -m app.listener.login")
    secure_session_file()

    @client.on(events.NewMessage(func=lambda e: e.is_private))  # in and out
    async def on_message(event: events.NewMessage.Event) -> None:
        try:
            chat = await event.get_chat()
        except Exception:
            log.exception("could not read the chat of message id=%s", event.message.id)
            return  # fill_gaps() saves it later
        await on_new_message(event.message, chat)

    async def heartbeat() -> None:
        while True:
            if client.is_connected():
                try:
                    await asyncio.to_thread(beat, "listener", "connected")
                except Exception:
                    log.exception("heartbeat failed")
            await asyncio.sleep(HEARTBEAT_SECONDS)

    log.info("listening for new private messages; outbox sender running")
    heartbeat_task = asyncio.create_task(heartbeat())
    sender_task = asyncio.create_task(sender.run_forever(client))
    gaps_task = asyncio.create_task(fill_gaps_forever(client))
    try:
        # Returns when the connection is lost for good; the process then exits and
        # systemd restarts it (catch_up=True fetches what arrived meanwhile).
        await client.run_until_disconnected()
    finally:
        heartbeat_task.cancel()
        sender_task.cancel()
        gaps_task.cancel()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(main())
