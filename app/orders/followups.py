"""Safety nets (docs/SPEC-v3.md 6.2, 6.3): payment reminder + auto-cancel, and the
"Needs you" lists for messages nobody answered and paid orders a customer wants to cancel.

Reminder / cancel: an order waiting for payment with no screenshot gets ONE reminder after
reminder_hours (default 12) and is cancelled after cancel_hours (default 48), with a
message. Only while auto-reply is ON and the chat may be auto-answered (customer not
ignored, not "never auto", owner not replying by hand); otherwise nothing is sent and the
order is listed in "Needs you" with a button for the admin.
"""
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session, aliased

from app.models import AuditLog, Customer, Message, MessageReview, Order, OrderEvent, Outbox, ParseResult, PaymentCheck
from app.models.orders import OPEN_STATUSES, SHIPPING_STATUSES
from app.orders import auto, delivery, unknown
from app.pricing.prices import format_mmk
from app.replies import templates as replies
from app.replies.templates import render

UNANSWERED_AFTER = timedelta(minutes=2)
RECENT = timedelta(days=7)
INFO_WINDOW = timedelta(hours=24)
QUESTION_INTENTS = ("other", "unknown", "ask_delivery", "cancel_order")  # listed even without an order
PAID_CANCEL_STATUSES = ("photo_received",) + SHIPPING_STATUSES  # money involved: the admin decides


# ---------- payment reminder + auto-cancel ----------

@dataclass
class Due:
    order: Order
    customer: Customer
    what: str  # reminder | cancel
    hours: int  # since the payment info was sent


def due(session: Session, now: datetime | None = None) -> list[Due]:
    """Orders waiting for payment (no screenshot) that need a reminder or a cancel now."""
    now = now or datetime.now(UTC)
    r = delivery.rules(session)
    photo = exists().where(PaymentCheck.order_id == Order.id)
    rows = session.execute(select(Order, Customer).join(Customer, Customer.id == Order.customer_id).where(
        Order.status == "waiting_payment", Order.payment_info_sent_at.is_not(None), ~photo,
        Order.payment_info_sent_at <= now - timedelta(hours=r["reminder_hours"])).order_by(Order.id)).all()
    found = []
    for order, customer in rows:
        age = now - order.payment_info_sent_at
        if age >= timedelta(hours=r["cancel_hours"]):
            found.append(Due(order, customer, "cancel", int(age.total_seconds() // 3600)))
        elif order.reminder_sent_at is None:
            found.append(Due(order, customer, "reminder", int(age.total_seconds() // 3600)))
    return found


def blocked(session: Session, customer: Customer, now: datetime) -> str | None:
    """Why the system may not message this customer by itself (None = it may)."""
    if not auto.enabled(session):
        return "auto-reply is off"
    if customer.ignored:
        return "ignored customer"
    if customer.auto_reply_off:
        return "never auto-reply to this customer"
    if auto.paused_until(session, customer, now):
        return "paused: owner is replying by hand"
    return None


def reminder_text(session: Session, order: Order, texts: dict[str, str]) -> str:
    from app.orders import cart

    return render(texts["payment_reminder"], total=format_mmk(cart.view(session, order).total))


def send_reminder(session: Session, order: Order, user, texts: dict[str, str], now: datetime,
                  delay: timedelta = delivery.UNDO_WINDOW) -> Outbox:
    if order.reminder_sent_at is not None:
        raise delivery.OrderError("A reminder was already sent for this order.")
    box = delivery.queue(session, order, reminder_text(session, order, texts), user, "reminder", "reminder", delay)
    order.reminder_sent_at = now
    session.add(AuditLog(user_id=user.id if user else None, action="order.reminder", details={
        "actor": "admin" if user else "auto", "order_id": order.id, "outbox_id": box.id}))
    return box


def run(session: Session, now: datetime | None = None) -> dict[str, int]:
    """Send due reminders / cancel unpaid orders (auto-reply ON only). Returns counts."""
    now = now or datetime.now(UTC)
    texts = replies.load(session)
    pace = auto.speed(session)
    stats: dict[str, int] = {}
    for d in due(session, now):
        if blocked(session, d.customer, now):
            continue  # listed in Needs you instead
        delay = timedelta(seconds=random.uniform(pace["delay_min_s"], pace["delay_max_s"]))
        if d.what == "reminder":
            send_reminder(session, d.order, None, texts, now, delay)
        else:
            delivery.cancel(session, d.order, None, texts, note=f"auto: not paid in {d.hours} h",
                            message="order_auto_cancelled", delay=delay)
        stats[d.what] = stats.get(d.what, 0) + 1
    return stats


def auto_cancelled(session: Session, now: datetime | None = None) -> list[tuple[Order, Customer]]:
    """Info in Needs you: orders the system cancelled in the last 24 h."""
    now = now or datetime.now(UTC)
    return session.execute(select(Order, Customer).join(Customer, Customer.id == Order.customer_id)
                           .join(OrderEvent, OrderEvent.order_id == Order.id).where(
        OrderEvent.to_status == "cancelled", OrderEvent.created_by.is_(None), OrderEvent.undone_at.is_(None),
        OrderEvent.created_at >= now - INFO_WINDOW, Order.status == "cancelled").order_by(OrderEvent.id.desc())).all()


# ---------- unanswered messages ----------

_M = aliased(Message, name="m")  # the unanswered message (Message itself is used for "later out")
_SRC = aliased(Message, name="src")  # the message a quick / auto reply answered


def _base(now: datetime, wait: timedelta):
    """Incoming messages of the last 7 days that nobody answered (no message from us after
    them, nothing queued) and nobody marked done / ignored. A quick / auto reply to an
    EARLIER message does not answer this one ("stw 5ml ယူမယ်" + "authentic လား" right after)."""
    for_earlier = exists().where(_SRC.id == Outbox.source_message_id, _SRC.id != _M.id,
                                 _SRC.received_at < _M.received_at)
    later_out = exists().where(Message.customer_id == Customer.id, Message.direction == "out",
                               Message.received_at > _M.received_at,
                               ~exists().where(Outbox.sent_message_id == Message.id, for_earlier))
    later_box = exists().where(Outbox.customer_id == Customer.id, Outbox.status.in_(("queued", "sending", "sent")),
                               Outbox.created_at > _M.received_at, ~for_earlier)
    payment_photo = exists().where(PaymentCheck.message_id == _M.id)
    reviewed = exists().where(MessageReview.message_id == _M.id, MessageReview.status.in_(("done", "ignored")))
    return (select(_M, Customer, ParseResult).join(Customer, Customer.id == _M.customer_id)
            .outerjoin(ParseResult, and_(ParseResult.message_id == _M.id, ParseResult.is_current))
            .where(_M.direction == "in", _M.received_at >= now - RECENT, _M.received_at <= now - wait,
                   Customer.ignored.is_(False), ~later_out, ~later_box, ~payment_photo, ~reviewed)
            .order_by(_M.received_at, _M.id))



@dataclass
class Unanswered:
    customer: Customer
    message_ids: list[int]
    last_text: str
    last_at: datetime
    reason: str
    faq: tuple | None = None  # (message id, faq.Match): an FAQ question inside (Step 7 hint)
    card: tuple | None = None  # (message, cards.Card): its teaching card (docs/SPEC-v4.md 4.2)


def unanswered(session: Session, now: datetime | None = None) -> list[Unanswered]:
    """One row per customer: their unanswered messages (2 min, open cart / order not yet
    delivered), plus other/unknown questions from the last 7 days."""
    now = now or datetime.now(UTC)
    active = set(session.scalars(select(Order.customer_id).where(
        Order.status.in_(OPEN_STATUSES + SHIPPING_STATUSES))))
    cancel_ids = {m.id for m, *_ in cancel_requests(session, now)}
    by_customer: dict[int, Unanswered] = {}
    for m, customer, result in session.execute(_base(now, UNANSWERED_AFTER)).all():
        intent = result.intent if result else None
        if m.id in cancel_ids:
            continue  # its own row
        if customer.id not in active and intent not in QUESTION_INTENTS:
            continue
        if intent in unknown.QUESTION_INTENTS and unknown.open_unknowns(session, m):
            continue  # listed as an unknown item
        row = by_customer.get(customer.id)
        reason = "open order" if customer.id in active else "question"
        if row is None:
            by_customer[customer.id] = Unanswered(customer, [m.id], m.raw_text or "📷 photo", m.received_at, reason)
        else:
            row.message_ids.append(m.id)
            row.last_text, row.last_at = m.raw_text or "📷 photo", m.received_at
    return sorted(by_customer.values(), key=lambda r: r.last_at, reverse=True)


def cancel_requests(session: Session, now: datetime | None = None) -> list[tuple]:
    """"Customer wants to cancel a paid order": (message, customer, order), newest first."""
    now = now or datetime.now(UTC)
    rows = session.execute(_base(now, timedelta(0)).where(ParseResult.intent == "cancel_order")).all()
    found = []
    for m, customer, _ in rows:
        order = session.scalar(select(Order).where(
            Order.customer_id == customer.id, Order.status.in_(PAID_CANCEL_STATUSES))
            .order_by(Order.id.desc()).limit(1))
        if order is not None:
            found.append((m, customer, order))
    return list(reversed(found))


def clear(session: Session, message_ids: list[int], status: str, user) -> None:
    from app.orders import actions

    for message_id in message_ids:
        actions.upsert_review(session, message_id, status, user)

