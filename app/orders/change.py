"""Changing the delivery address / phone (docs/SPEC-v4.8-change-info.md).

- "မဟုတ်ဘူး" / "no" / "ပြောင်းမယ်" right after our "ဖုန်း …၊ လိပ်စာ … ကိုပဲ ပို့ပေးရမလား။" = change_info
  (unclear): the parser service asks negative_answer() before the rules.
- Which order a change is for: the open one, else the customer's latest paid one.
- Needs you: an address / phone changed after payment (until an admin ticks "checked" or the order
  is sent out), and change requests for orders already sent out (no automatic change).
"""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Customer, Message, MessageReview, Order, OrderEvent, ParseResult, QuickAction, User
from app.models.orders import OPEN_STATUSES
from app.parser.rules import ParseOutcome

NEGATIVE_RE = re.compile(r"^(?:မ\s*ဟုတ်(?:ဘူး|ပါဘူး|ပါ)?|no|nope|not that|ပြောင်း(?:မယ်|ချင်(?:တယ်)?)(?:ပါ)?)"
                         r"(?:\s*(?:ရှင့်|ရှင်|ခင်ဗျာ|ခင်ဗျ|နော်|ပါ|ဗျ|sis|pls|please))*[\s.!။]*$")
AFTER_PAYMENT = ("photo_received", "paid", "packed")  # changed on the order + Needs you to check
SENT = ("sent_out", "delivered")  # never changed automatically
RECENT = timedelta(days=30)
NEEDS_YOU_WINDOW = timedelta(days=3)
CHANGED_SHOWN = timedelta(hours=24)


def returning_question_open(session: Session, message: Message) -> bool:
    """Our last cart list (before this message) ended with "same phone & address?": an unconfirmed
    cart whose list went out, and a phone and an address to offer."""
    from app.orders import cart  # late import: cart -> models only, but keep the parser path light

    order = session.scalar(select(Order).where(Order.customer_id == message.customer_id,
                                               Order.status == "cart", Order.list_sent_at.is_not(None),
                                               Order.list_sent_at <= message.received_at))
    if order is None:
        return False
    customer = session.get(Customer, message.customer_id)
    return bool((order.phones or cart.customer_phones(session, customer.id)) and (cart.order_address(order) or cart.saved_address(customer)))


def negative_answer(session: Session, message: Message, normalized: str) -> ParseOutcome | None:
    """"မဟုတ်ဘူး" to "…ကိုပဲ ပို့ပေးရမလား။" means "send it somewhere else" (change_info, unclear)."""
    if message.direction != "in" or not NEGATIVE_RE.match(normalized or ""):
        return None
    if not returning_question_open(session, message):
        return None
    return ParseOutcome("change_info", None, None, 1, 0.8)


def target_order(session: Session, customer_id: int) -> Order | None:
    """The open order, else the latest paid one (last 30 days)."""
    order = session.scalar(select(Order).where(Order.customer_id == customer_id, Order.status.in_(OPEN_STATUSES)))
    if order is not None:
        return order
    return session.scalar(select(Order).where(
        Order.customer_id == customer_id, Order.status.in_(AFTER_PAYMENT + SENT),
        Order.paid_at >= datetime.now(UTC) - RECENT).order_by(Order.paid_at.desc()).limit(1))


def waiting_after_payment(session: Session, customer_id: int) -> Order | None:
    """A paid order whose customer asked to change the address / phone (we asked for the new one)."""
    return session.scalar(select(Order).where(Order.customer_id == customer_id, Order.status.in_(AFTER_PAYMENT),
                                              Order.change_wanted.is_not(None)))


# ---------- what the dashboard shows ----------

def recent_changes(session: Session, order_id: int, now: datetime | None = None) -> list[OrderEvent]:
    """Contact changes of the last 24 h (cart panel: "address changed at hh:mm (old: …)")."""
    now = now or datetime.now(UTC)
    return list(session.scalars(select(OrderEvent).where(
        OrderEvent.order_id == order_id, OrderEvent.kind == "contact", OrderEvent.created_at >= now - CHANGED_SHOWN)
        .order_by(OrderEvent.id.desc())))


def history(session: Session, order_ids: list[int]) -> dict[int, list[OrderEvent]]:
    """All contact changes per order (orders page)."""
    out: dict[int, list[OrderEvent]] = {}
    for e in session.scalars(select(OrderEvent).where(OrderEvent.order_id.in_(order_ids), OrderEvent.kind == "contact")
                             .order_by(OrderEvent.id)):
        out.setdefault(e.order_id, []).append(e)
    return out


def changed_after_payment(session: Session) -> list[tuple[Order, Customer, OrderEvent]]:
    """Needs you: "📍 Order #N address changed after payment — check before packing/sending", until an
    admin ticks "checked" (an address_checked event newer than the change) or the order is sent out."""
    out = []
    for order, customer in session.execute(select(Order, Customer).join(Customer, Customer.id == Order.customer_id)
                                           .where(Order.status.in_(AFTER_PAYMENT))).all():
        event = session.scalar(select(OrderEvent).where(
            OrderEvent.order_id == order.id, OrderEvent.kind == "contact",
            OrderEvent.from_status.in_(AFTER_PAYMENT)).order_by(OrderEvent.id.desc()).limit(1))
        if event is None:
            continue
        checked = session.scalar(select(exists().where(OrderEvent.order_id == order.id,
                                                       OrderEvent.kind == "address_checked", OrderEvent.id > event.id)))
        if not checked:
            out.append((order, customer, event))
    return out


def mark_checked(session: Session, order: Order, user: User) -> None:
    session.add(OrderEvent(order_id=order.id, from_status=order.status, to_status=order.status, kind="address_checked",
                           previous={}, created_by=user.id))


def requests_for_sent_orders(session: Session, now: datetime | None = None) -> list[tuple[Message, Customer, Order]]:
    """Needs you: "customer wants to change the address of an order already sent" (no auto reply)."""
    now = now or datetime.now(UTC)
    handled = exists().where(QuickAction.message_id == Message.id, QuickAction.undone_at.is_(None))
    reviewed = exists().where(MessageReview.message_id == Message.id, MessageReview.status.in_(("done", "ignored")))
    rows = session.execute(
        select(Message, Customer).join(ParseResult, (ParseResult.message_id == Message.id) & ParseResult.is_current)
        .join(Customer, Customer.id == Message.customer_id)
        .where(Message.direction == "in", Message.received_at >= now - NEEDS_YOU_WINDOW,
               ParseResult.intent == "change_info", Customer.ignored.is_(False), ~handled, ~reviewed)
        .order_by(Message.received_at.desc())).all()
    out = []
    for message, customer in rows:
        order = target_order(session, customer.id)
        if order is not None and order.status in SENT:
            out.append((message, customer, order))
    return out
