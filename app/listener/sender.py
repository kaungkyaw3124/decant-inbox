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
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.orm import aliased
from telethon import errors
from telethon.tl import types

from app.core.db import SessionLocal
from app.core.notify import AsyncWaiter
from app.listener.save import CHANNEL, ChatMessage, insert_message
from app.models import Customer, MediaDownload, Message, Outbox
from app.models.outbox import MAX_TEXT, MEDIA_DIR

log = logging.getLogger("sender")
MIN_INTERVAL = 3.0  # seconds between two sends, overall
MAX_PER_MINUTE = 20
MAX_MEDIA_BYTES = 10 * 1024 * 1024
MEDIA_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
# docs/SPEC-v4.18 S3: a waiting customer's reply goes before reminders / notices (same 1 msg / 3 s limit)
LATER_KINDS = ("reminder", "cancel", "delivery")
# docs/SPEC-v5.9 B3: network / timeout / Telegram server errors are retried after these delays (s); anything
# else (privacy, blocked, peer invalid, entity not found) fails at once
RETRY_DELAYS = (10, 30, 90)
TRANSIENT = (TimeoutError, ConnectionError, OSError, errors.ServerError, errors.TimedOutError)
# docs/SPEC-v5.9 B1: a row "sending" longer than this was interrupted (crash / restart / deploy)
STUCK_AFTER = timedelta(seconds=90)
RESEND_WITHIN = timedelta(minutes=15)  # an older stuck reply is stale: failed (Needs you), never sent this late
RECOVER_EVERY = 60.0


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
    """Take the next queued row and mark it "sending". Returns (outbox id, customer id, telegram user id,
    text), or None. Rows failing the safety checks are marked failed and the next row is taken.
    docs/SPEC-v5.9 B6: a waiting customer's reply before reminders; then the customer who got our last message
    longest ago (one customer's burst does not hold up everyone else); a customer's own replies in order."""
    earlier = aliased(Outbox)
    last_sent = select(func.max(earlier.sent_at)).where(
        earlier.customer_id == Outbox.customer_id, earlier.status == "sent").scalar_subquery()
    while True:
        with SessionLocal.begin() as s:
            row = s.scalar(select(Outbox).where(Outbox.status == "queued", Outbox.send_after <= func.now())
                           .order_by(case((Outbox.reply_kind.in_(LATER_KINDS), 1), else_=0),
                                     func.coalesce(last_sent, datetime(2000, 1, 1, tzinfo=UTC)), Outbox.id)
                           .limit(1).with_for_update(of=Outbox, skip_locked=True))
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
                continue  # the next row now, not after the next poll
            row.status, row.error, row.claimed_at = "sending", None, func.now()
            return row.id, row.customer_id, customer.external_user_id, text


def mark_sent(outbox_id: int, customer_id: int, user_id: str, sent) -> None:
    with SessionLocal.begin() as s:
        message_id, _ = insert_message(s, ChatMessage(
            external_chat_id=user_id, external_message_id=str(sent.id), external_user_id=user_id,
            username=None, display_name=None, text=sent.message or "", received_at=sent.date,
            direction="out"), customer_id)
        row = s.get(Outbox, outbox_id)
        row.status, row.sent_at, row.sent_message_id, row.error = "sent", datetime.now(UTC), message_id, None


def mark(outbox_id: int, status: str, error: str | None, retry_in: float | None = None) -> None:
    with SessionLocal.begin() as s:
        row = s.get(Outbox, outbox_id)
        row.status, row.error = status, error
        if retry_in is not None:
            row.send_after = datetime.now(UTC) + timedelta(seconds=retry_in)


def _attempts(outbox_id: int) -> int:
    with SessionLocal() as s:
        return s.get(Outbox, outbox_id).attempts


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
    except TRANSIENT as exc:  # docs/SPEC-v5.9 B3: try again later, then fail (Needs you + alert)
        error = f"{type(exc).__name__}: {exc}"[:500]
        tries = await asyncio.to_thread(_attempts, outbox_id)
        if tries <= len(RETRY_DELAYS):
            await asyncio.to_thread(mark, outbox_id, "queued", error, RETRY_DELAYS[tries - 1])
            log.warning("outbox=%s %s, retry %d in %ss", outbox_id, type(exc).__name__, tries, RETRY_DELAYS[tries - 1])
        else:
            await asyncio.to_thread(mark, outbox_id, "failed", error)
            log.warning("outbox=%s failed after %d tries: %s", outbox_id, tries, type(exc).__name__)
        return True
    except Exception as exc:
        await asyncio.to_thread(mark, outbox_id, "failed", f"{type(exc).__name__}: {exc}"[:500])
        log.warning("outbox=%s failed: %s", outbox_id, type(exc).__name__)
        return True
    await asyncio.to_thread(mark_sent, outbox_id, customer_id, user_id, sent)
    log.info("outbox=%s sent chat=%s msg=%s", outbox_id, user_id, sent.id)
    return True


# ---------- docs/SPEC-v5.9 B1: replies left in "sending" by a crash / restart ----------

_PLAIN = re.compile(r"[\s*_~`\[\]()]+")  # Telegram may drop markdown marks: compare the words only


def _same(a: str | None, b: str | None) -> bool:
    return _PLAIN.sub("", a or "") == _PLAIN.sub("", b or "")


def stuck_rows() -> list[tuple[int, int, str, str, datetime]]:
    """(outbox id, customer id, telegram user id, text, claimed at) of rows "sending" for too long."""
    with SessionLocal() as s:
        claimed = func.coalesce(Outbox.claimed_at, Outbox.created_at)
        return [tuple(r) for r in s.execute(
            select(Outbox.id, Outbox.customer_id, Customer.external_user_id, Outbox.text, claimed)
            .join(Customer, Customer.id == Outbox.customer_id)
            .where(Outbox.status == "sending", claimed < func.now() - STUCK_AFTER).order_by(Outbox.id))]


def _saved_copy(outbox_id: int, customer_id: int, text: str, since: datetime) -> int | None:
    """Our message already saved by the listener (its own "out" event) and not linked to another reply."""
    with SessionLocal() as s:
        for message in s.scalars(select(Message).where(
                Message.customer_id == customer_id, Message.direction == "out",
                Message.received_at >= since - timedelta(seconds=5),
                ~exists().where(Outbox.sent_message_id == Message.id)).order_by(Message.id)):
            if _same(message.raw_text, text):
                return message.id
    return None


def _finish_recovered(outbox_id: int, message_id: int | None, sent=None, customer_id=None, user_id=None) -> str:
    """Found in the chat -> sent; not found -> queued again once (if claimed < RESEND_WITHIN ago); twice / too
    old -> failed (never a double send, never a stale reply)."""
    if sent is not None:
        with SessionLocal.begin() as s:
            message_id, _ = insert_message(s, ChatMessage(
                external_chat_id=user_id, external_message_id=str(sent.id), external_user_id=user_id,
                username=None, display_name=None, text=sent.message or "", received_at=sent.date,
                direction="out"), customer_id)
            if s.scalar(select(exists().where(Outbox.sent_message_id == message_id, Outbox.id != outbox_id))):
                message_id = None  # the same text of another reply (e.g. two "please wait"), not this one
    with SessionLocal.begin() as s:
        row = s.scalar(select(Outbox).where(Outbox.id == outbox_id, Outbox.status == "sending").with_for_update())
        if row is None:
            return "gone"
        if message_id is not None:
            row.status, row.sent_at, row.sent_message_id, row.error = "sent", datetime.now(UTC), message_id, None
            return "sent"
        claimed = row.claimed_at or row.created_at
        if row.recovered_at is None and datetime.now(UTC) - claimed < RESEND_WITHIN:
            row.status, row.recovered_at, row.error = "queued", datetime.now(UTC), "re-queued after a restart"
            return "requeued"
        if row.recovered_at is None:
            row.status, row.error = "failed", "stuck while sending for too long; not sent again automatically"
            return "failed"
        row.status, row.error = "failed", "interrupted twice while sending; check the chat before sending again"
        return "failed"


async def recover_stuck(client) -> dict[str, int]:
    """Rows "sending" longer than STUCK_AFTER: look in the chat (read-only, our last 20 messages) for the
    same text sent after the claim. Offline / Telegram error = cannot tell: left as they are (the alert service
    reports them). Runs in the sender loop, so no send of this process is in flight meanwhile."""
    stats: dict[str, int] = {}
    for outbox_id, customer_id, user_id, text, claimed in await asyncio.to_thread(stuck_rows):
        found = await asyncio.to_thread(_saved_copy, outbox_id, customer_id, text, claimed)
        sent = None
        if found is None:
            if not client.is_connected():
                stats["unknown"] = stats.get("unknown", 0) + 1
                continue
            try:
                entity = await client.get_input_entity(types.PeerUser(int(user_id)))
                recent = await client.get_messages(entity, limit=20)
            except Exception as exc:
                log.warning("outbox=%s stuck, cannot check the chat: %s", outbox_id, type(exc).__name__)
                stats["unknown"] = stats.get("unknown", 0) + 1
                continue
            since = claimed - timedelta(seconds=5)
            sent = next((m for m in recent or [] if getattr(m, "out", False) and m.date and m.date >= since
                         and _same(m.message, text)), None)
        outcome = await asyncio.to_thread(_finish_recovered, outbox_id, found, sent, customer_id, user_id)
        log.warning("outbox=%s was stuck in sending: %s", outbox_id, outcome)
        stats[outcome] = stats.get(outcome, 0) + 1
    return stats


def next_due() -> float | None:
    """Seconds until the next queued reply may go out (its send_after), or None."""
    with SessionLocal() as s:
        at = s.scalar(select(func.min(Outbox.send_after)).where(Outbox.status == "queued"))
    return None if at is None else (at - datetime.now(UTC)).total_seconds()


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
    """Outbox + downloads loop, inside the listener (the one process with the session).
    docs/SPEC-v4.18 S1: sleeps until the next reply is due, or a NOTIFY on "outbox" (a new reply); the
    0.5 s poll stays as the fallback."""
    limiter = RateLimiter()
    waiter = AsyncWaiter("outbox")
    last_recovery = None
    while True:
        try:
            if client.is_connected() and (last_recovery is None or time.monotonic() - last_recovery >= RECOVER_EVERY):
                await recover_stuck(client)  # at start and every minute (docs/SPEC-v5.9 B1)
                last_recovery = time.monotonic()
            busy = False
            if client.is_connected():
                busy = await send_next(client, limiter)
                busy = await download_next(client) or busy
            if not busy:
                due = await asyncio.to_thread(next_due)
                # due <= 0 but nothing sent (offline, locked row): the normal poll, never a busy loop
                wait = min(poll_seconds, due) if due is not None and due > 0 else poll_seconds
                await waiter.wait(wait)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("outbox loop error")
            await asyncio.sleep(10)
