"""Never leave a customer in silence (docs/SPEC-v4.13-hotfix.md Q1).

The watchdog (parser worker, every second): a customer text message that is 60 s old and still has no
answer at all — no reply after it (sent, sending or queued), no one-tap / auto action, not marked done —
while the customer has an order that is not delivered yet, or the message asks to buy / about a price,
gets the HOLDING reply "ခဏစောင့်ပေးပါနော်၊ စစ်ပြီး ပြန်ပြောပေးပါမယ်။" and is logged "silent message caught".
At most once per 10 minutes per customer; never when a person replied by hand in the last 10 minutes;
never for ignored customers or customers with auto replies off; only while auto replies are ON.
Needs you lists these as "⏰ customer waiting" (at the top) until someone answers.
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import AuditLog, Customer, Message, MessageReview, Order, Outbox, ParseResult, QuickAction
from app.models.orders import OPEN_STATUSES, SHIPPING_STATUSES
from app.orders import auto
from app.replies import compose
from app.replies import templates as replies

log = logging.getLogger("holding")
WAIT = timedelta(seconds=60)
LOOKBACK = timedelta(minutes=30)  # older messages (history imports, a long outage) are not caught here
ONCE_PER = timedelta(minutes=10)
HAND_QUIET = timedelta(minutes=10)
WAITING_FOR = timedelta(hours=24)  # Needs you "⏰ customer waiting"
ASKING = ("buy", "ask_price", "ask_stock", "order_start", "previous_item", "modify_cart", "remove")


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
    """An order that is not delivered yet, or a buy / price question."""
    if session.scalar(select(exists().where(Order.customer_id == message.customer_id,
                                            Order.status.in_(OPEN_STATUSES + SHIPPING_STATUSES)))):
        return True
    intent = session.scalar(select(ParseResult.intent).where(ParseResult.message_id == message.id,
                                                             ParseResult.is_current))
    return intent in ASKING


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
