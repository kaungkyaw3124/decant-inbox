"""The ONLY place that writes to the Telegram account (docs/SPEC-orders.md):
send a text that an admin queued in the dashboard (outbox), to a private chat that has
messaged us first. Never edit, delete, forward, pin or mark-read.
tests/test_listener_readonly.py allows send_message here and nowhere else.

Also downloads a photo when an admin asks to see it (read-only).
Logs ids and counts only, never message text.
"""
import asyncio
import hashlib
import logging
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import exists, func, select
from telethon import errors
from telethon.tl import types

from app.core.db import SessionLocal
from app.listener.save import CHANNEL, ChatMessage, insert_message
from app.models import Customer, MediaDownload, Message, Outbox
from app.models.outbox import MAX_TEXT, MEDIA_DIR

log = logging.getLogger("sender")
MIN_INTERVAL = 3.0  # seconds between two sends, overall
MAX_PER_MINUTE = 20
MAX_MEDIA_BYTES = 10 * 1024 * 1024
MEDIA_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class RateLimiter:
    """At most one send per MIN_INTERVAL and MAX_PER_MINUTE per 60 s."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.sent: deque[float] = deque()

    def wait_time(self) -> float:
        now = self.clock()
        while self.sent and now - self.sent[0] >= 60:
            self.sent.popleft()
        waits = [0.0]
        if self.sent:
            waits.append(self.sent[-1] + MIN_INTERVAL - now)
        if len(self.sent) >= MAX_PER_MINUTE:
            waits.append(self.sent[0] + 60 - now)
        return max(waits)

    def record(self) -> None:
        self.sent.append(self.clock())


# ---------- outbox (database side; sync, run in a thread) ----------

def claim_next() -> tuple[int, int, str, str] | None:
    """Take the oldest queued row and mark it "sending". Returns (outbox id, customer id,
    telegram user id, text), or None. Rows failing the safety checks are marked failed."""
    with SessionLocal.begin() as s:
        row = s.scalar(select(Outbox).where(Outbox.status == "queued", Outbox.send_after <= func.now())
                       .order_by(Outbox.id)
                       .limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        customer = s.get(Customer, row.customer_id)
        has_written = s.scalar(select(exists().where(
            Message.customer_id == row.customer_id, Message.direction == "in")))
        text = row.text.strip()
        problem = None
        if customer is None or customer.channel != CHANNEL:
            problem = "not a Telegram customer"
        elif not has_written:
            problem = "this customer has never messaged us"
        elif not text or len(text) > MAX_TEXT:
            problem = f"text must be 1-{MAX_TEXT} characters"
        row.attempts += 1
        if problem:
            row.status, row.error = "failed", problem
            log.warning("outbox=%s refused: %s", row.id, problem)
            return None
        row.status, row.error = "sending", None
        return row.id, row.customer_id, customer.external_user_id, text


def mark_sent(outbox_id: int, customer_id: int, user_id: str, sent) -> None:
    with SessionLocal.begin() as s:
        message_id, _ = insert_message(s, ChatMessage(
            external_chat_id=user_id, external_message_id=str(sent.id), external_user_id=user_id,
            username=None, display_name=None, text=sent.message or "", received_at=sent.date,
            direction="out"), customer_id)
        row = s.get(Outbox, outbox_id)
        row.status, row.sent_at, row.sent_message_id, row.error = "sent", datetime.now(UTC), message_id, None


def mark(outbox_id: int, status: str, error: str | None) -> None:
    with SessionLocal.begin() as s:
        row = s.get(Outbox, outbox_id)
        row.status, row.error = status, error


async def send_next(client, limiter: RateLimiter) -> bool:
    """Send one queued message if any. Returns True if a row was handled."""
    wait = limiter.wait_time()
    if wait > 0:
        await asyncio.sleep(wait)
    job = await asyncio.to_thread(claim_next)
    if job is None:
        return False
    outbox_id, customer_id, user_id, text = job
    try:
        entity = await client.get_input_entity(types.PeerUser(int(user_id)))
        limiter.record()
        sent = await client.send_message(entity, text, link_preview=False)
    except errors.FloodWaitError as exc:
        await asyncio.to_thread(mark, outbox_id, "queued", f"Telegram asked to wait {exc.seconds}s")
        log.warning("outbox=%s flood wait %ss, kept queued", outbox_id, exc.seconds)
        await asyncio.sleep(exc.seconds + 1)
        return True
    except Exception as exc:
        await asyncio.to_thread(mark, outbox_id, "failed", f"{type(exc).__name__}: {exc}"[:500])
        log.warning("outbox=%s failed: %s", outbox_id, type(exc).__name__)
        return True
    await asyncio.to_thread(mark_sent, outbox_id, customer_id, user_id, sent)
    log.info("outbox=%s sent chat=%s msg=%s", outbox_id, user_id, sent.id)
    return True


# ---------- photo downloads ----------

def claim_download() -> tuple[int, str, str, str] | None:
    """(message id, chat id, telegram message id, mime) of the oldest queued download."""
    with SessionLocal.begin() as s:
        row = s.scalar(select(MediaDownload).where(MediaDownload.status == "queued")
                       .order_by(MediaDownload.requested_at).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        msg = s.get(Message, row.message_id)
        problem = None
        if msg.kind != "photo":
            problem = "not a photo"
        elif msg.media_mime not in MEDIA_EXT:
            problem = f"unsupported image type {msg.media_mime}"
        elif msg.media_size and msg.media_size > MAX_MEDIA_BYTES:
            problem = "photo too big (over 10 MB)"
        if problem:
            row.status, row.error, row.done_at = "failed", problem, datetime.now(UTC)
            return None
        # stays "queued" while downloading (one listener, one job at a time)
        return msg.id, msg.external_chat_id, msg.external_message_id, msg.media_mime


def finish_download(message_id: int, path: str | None, error: str | None, sha256: str | None = None) -> None:
    with SessionLocal.begin() as s:
        row = s.get(MediaDownload, message_id)
        row.status = "done" if path else "failed"
        row.path, row.error, row.done_at, row.sha256 = path, error, datetime.now(UTC), sha256


async def download_next(client) -> bool:
    job = await asyncio.to_thread(claim_download)
    if job is None:
        return False
    message_id, chat_id, tg_message_id, mime = job
    MEDIA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = MEDIA_DIR / f"{message_id}{MEDIA_EXT[mime]}"
    try:
        entity = await client.get_input_entity(types.PeerUser(int(chat_id)))
        message = await client.get_messages(entity, ids=int(tg_message_id))
        if message is None or message.media is None:
            raise LookupError("message or photo no longer exists")
        result = await client.download_media(message, file=str(target))
        if not result or Path(result).stat().st_size > MAX_MEDIA_BYTES:
            Path(result or target).unlink(missing_ok=True)
            raise ValueError("download failed or too big")
        Path(result).chmod(0o600)
        digest = hashlib.sha256(Path(result).read_bytes()).hexdigest()
        await asyncio.to_thread(finish_download, message_id, Path(result).name, None, digest)
        log.info("photo downloaded message=%s", message_id)
    except Exception as exc:
        await asyncio.to_thread(finish_download, message_id, None, f"{type(exc).__name__}: {exc}"[:300])
        log.warning("photo download failed message=%s: %s", message_id, type(exc).__name__)
    return True


async def run_forever(client, poll_seconds: float = 0.5) -> None:
    """Outbox + downloads loop, inside the listener (the one process with the session)."""
    limiter = RateLimiter()
    while True:
        try:
            busy = False
            if client.is_connected():
                busy = await send_next(client, limiter)
                busy = await download_next(client) or busy
            if not busy:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("outbox loop error")
            await asyncio.sleep(10)
