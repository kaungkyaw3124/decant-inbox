"""Never leave a customer in silence (docs/SPEC-v4.13-hotfix.md Q1, docs/SPEC-v4.20-automation-goal.md G3).

The watchdog (parser worker, every second): a customer text message that is 10 s old and still has no
answer at all — no reply after it (sent, sending or queued), no one-tap / auto action, not marked done —
gets the HOLDING reply "ခဏစောင့်ပေးပါနော်၊ စစ်ပြီး ပြန်ပြောပေးပါမယ်။" and is logged "silent message caught".
Not caught: small talk that needs no answer ("thanks", "ok", 👍, emoji only), unless it is a complaint.
Complaints / refunds / angry messages (is_complaint) are never answered automatically: a person.
At most once per 10 minutes per customer; never when a person replied by hand in the last 10 minutes;
never for ignored customers or customers with auto replies off; only while auto replies are ON.
Needs you lists these as "⏰ customer waiting" (at the top) until someone answers.
"""
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import AuditLog, Customer, Message, MessageReview, Outbox, QuickAction
from app.orders import auto
from app.replies import compose
from app.replies import templates as replies

log = logging.getLogger("holding")
WAIT = timedelta(seconds=10)  # G3: the customer hears from us within 10 s (4.13 had 60 s)
LOOKBACK = timedelta(minutes=30)  # older messages (history imports, a long outage) are not caught here
ONCE_PER = timedelta(minutes=10)
HAND_QUIET = timedelta(minutes=10)
WAITING_FOR = timedelta(hours=24)  # Needs you "⏰ customer waiting"
# a person handles these; a reply must never promise a refund / replacement (docs/SPEC-v4.20 A4)
COMPLAINT_RE = re.compile(
    r"ယို(?:နေ|ထွက်|ကျ)|ကွဲ(?:နေ|သွား|ပြီး)|ပျက်(?:နေ|သွား)|မှား(?:ပို့|ရောက်)|ပစ္စည်း\s*မှား|မတူ(?:ဘူး|ပါဘူး)|"
    r"ပြန်\s*အမ်း|ငွေ\s*ပြန်|အတု|မမွှေး|စိတ်\s*(?:ညစ်|တို|ပျက်)|လိမ်|"
    r"(?<![a-z])(?:broken|broke|leak\w*|damaged?|refund\w*|fake|wrong (?:item|perfume|bottle)|complain\w*|"
    r"scam|angry|cheat\w*|return)(?![a-z])", re.IGNORECASE)
# needs no answer when nothing else is pending: thanks / ok / yes / emoji only (every word one of these)
SMALL_TALK_RE = re.compile(
    r"ကျေးဇူး\S*|thank\S*|thx|tq|ty|you|very|so|much|a|lot|ok\S*|okay|ဟုတ်(?:ကဲ့)?\S*|အိုကေ\S*|ရပါပြီ|ရပြီ|"
    r"good|nice|great|ကောင်းပါတယ်|bye|ဘိုင်|ပါ|နော်|ရှင့်|ရှင်|ဗျ|ဗျာ|ခင်ဗျာ|[^\w]+", re.IGNORECASE)


def is_complaint(text: str | None) -> bool:
    return bool(text and COMPLAINT_RE.search(text))


def is_small_talk(text: str | None) -> bool:
    words = (text or "").split()
    return bool(words) and not is_complaint(text) and all(SMALL_TALK_RE.fullmatch(w) for w in words)


def _answered(session: Session, message: Message):
    """Something went (or is going) to the customer after this message, or someone handled it."""
    return (session.scalar(select(exists().where(
        Outbox.customer_id == message.customer_id, Outbox.created_at >= message.received_at,
        Outbox.status.in_(("queued", "sending", "sent"))))) or session.scalar(select(exists().where(
            Message.customer_id == message.customer_id, Message.direction == "out",
            Message.received_at >= message.received_at))) or session.scalar(select(exists().where(
                QuickAction.message_id == message.id, QuickAction.undone_at.is_(None)))) or session.scalar(
        select(exists().where(MessageReview.message_id == message.id,
                              MessageReview.status.in_(("done", "ignored"))))))


def _waiting_customer(session: Session, message: Message) -> bool:
    """Every message waits for an answer (G3), except small talk ("thanks", "ok", 👍) — that needs none."""
    return not is_small_talk(message.raw_text)


def silent(session: Session, now: datetime) -> list[Message]:
    """The newest unanswered waiting message per customer (60 s - 30 min old)."""
    rows = session.scalars(
        select(Message).join(Customer, Customer.id == Message.customer_id)
        .where(Message.direction == "in", Message.kind == "text", Message.received_at <= now - WAIT,
               Message.received_at >= now - LOOKBACK, Customer.ignored.is_(False),
               Customer.auto_reply_off.is_(False))
        .order_by(Message.received_at.desc(), Message.id.desc())).all()
    found, seen = [], set()
    for m in rows:
        if m.customer_id in seen:
            continue
        seen.add(m.customer_id)  # only the newest message of a customer counts
        if not _answered(session, m) and _waiting_customer(session, m):
            found.append(m)
    return found


def _held_recently(session: Session, customer_id: int, now: datetime) -> bool:
    return bool(session.scalar(select(exists().where(
        Outbox.customer_id == customer_id, Outbox.reply_kind == "holding", Outbox.created_at >= now - ONCE_PER))))


def _hand_reply_recently(session: Session, customer_id: int, now: datetime) -> bool:
    hand = auto.last_hand_reply(session, customer_id, now)
    if hand is not None and hand >= now - HAND_QUIET:
        return True
    return bool(session.scalar(select(exists().where(
        Outbox.customer_id == customer_id, Outbox.created_by.is_not(None), Outbox.created_at >= now - HAND_QUIET))))


def run_once(now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    stats: dict[str, int] = {}
    with SessionLocal.begin() as session:
        if not auto.enabled(session):
            return {}
        texts = None
        for message in silent(session, now):
            if session.scalar(select(exists().where(AuditLog.action == "auto.holding",
                                                    AuditLog.details["message_id"].as_integer() == message.id))):
                continue  # caught before (a person was busy): not again for the same message
            log.warning("silent message caught message=%s customer=%s", message.id, message.customer_id)
            if _held_recently(session, message.customer_id, now) or _hand_reply_recently(
                    session, message.customer_id, now):
                session.add(AuditLog(user_id=None, action="auto.holding", details={
                    "actor": "auto", "message_id": message.id, "customer_id": message.customer_id, "sent": False}))
                stats["caught"] = stats.get("caught", 0) + 1
                continue
            texts = texts or replies.load(session)
            body = compose.with_greeting(texts["holding_reply"], texts,
                                         compose.needs_greeting(session, message.customer_id, now))
            box = Outbox(customer_id=message.customer_id, text=body, reply_kind="holding", status="queued",
                         idempotency_key=f"holding-{message.id}", created_by=None, send_after=now,
                         source_message_id=message.id)
            session.add(box)
            session.flush()
            session.add(AuditLog(user_id=None, action="auto.holding", details={
                "actor": "auto", "message_id": message.id, "customer_id": message.customer_id, "outbox_id": box.id,
                "sent": True}))
            stats["held"] = stats.get("held", 0) + 1
    return stats


def waiting(session: Session, now: datetime | None = None) -> list[tuple[Customer, Message, datetime]]:
    """Needs you "⏰ customer waiting": caught messages nobody answered since (newest first)."""
    now = now or datetime.now(UTC)
    out, seen = [], set()
    for row in session.scalars(select(AuditLog).where(AuditLog.action == "auto.holding",
                                                      AuditLog.created_at >= now - WAITING_FOR)
                               .order_by(AuditLog.id.desc())):
        message = session.get(Message, row.details.get("message_id"))
        if message is None or message.customer_id in seen:
            continue
        seen.add(message.customer_id)
        later_reply = session.scalar(select(exists().where(
            Outbox.customer_id == message.customer_id, Outbox.created_at > row.created_at,
            Outbox.reply_kind != "holding", Outbox.status.in_(("queued", "sending", "sent")))))
        handled = session.scalar(select(exists().where(QuickAction.message_id == message.id,
                                                       QuickAction.undone_at.is_(None)))) or session.scalar(
            select(exists().where(MessageReview.message_id == message.id,
                                  MessageReview.status.in_(("done", "ignored")))))
        if later_reply or handled or auto.answered_by_human(session, message):
            continue
        out.append((session.get(Customer, message.customer_id), message, row.created_at))
    return out


def count_today(session: Session, now: datetime) -> int:
    return session.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "auto.holding", AuditLog.created_at >= now - timedelta(hours=24))) or 0
