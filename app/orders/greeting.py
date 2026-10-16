"""The reply to a message that is only a greeting ("hi") (docs/SPEC-v4.9-greeting.md).

It always gets an answer, unless we already sent a greeting reply to this customer in the last
30 minutes (setting greeting_repeat_minutes; a repeated "hi" then waits in Needs you). The
answer follows where the customer is:
  no order          greeting_reply            "မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။"
  open cart         greeting_cart             the list + the next question (phone / address / same?)
  waiting for a new address / phone (4.8)     the ask_new_* question again
  waiting_payment   greeting_waiting_payment  items, total, "send the screenshot"
  photo_received    greeting_photo_received
  paid / packed     greeting_preparing        Order #
  sent_out          greeting_sent             Order # + date
The 6 h rule (compose.needs_greeting) only decides whether the reply starts with "မင်္ဂလာပါ။":
if we messaged them in the last 6 h, the leading greeting is left out. Never twice.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.learning import patterns
from app.models import Order, Outbox
from app.models.orders import OPEN_STATUSES
from app.orders import cart, delivery
from app.pricing.prices import format_mmk
from app.replies import compose
from app.replies.templates import render

ASK_NEW = {"address": "ask_new_address", "phone": "ask_new_phone"}


def greeted_recently(session: Session, customer_id: int, now: datetime | None = None) -> bool:
    """A greeting reply to this customer was queued / sent within greeting_repeat_minutes."""
    minutes = patterns.settings(session)["greeting_repeat_minutes"]
    if minutes <= 0:
        return False
    since = (now or datetime.now(UTC)) - timedelta(minutes=minutes)
    return bool(session.scalar(select(exists().where(
        Outbox.customer_id == customer_id, Outbox.reply_kind == "greeting", Outbox.status != "cancelled",
        Outbox.created_at >= since))))


def _items_short(session: Session, order: Order) -> str:
    return ", ".join(f"{p.name} {cart.item_size(i, p)}".strip() + (f" ×{i.quantity}" if i.quantity > 1 else "")
                     for i, p in cart.view(session, order).lines if p is not None)


def body(session: Session, customer_id: int, texts: dict[str, str]) -> str:
    """The full reply for the customer's current state (with the leading greeting)."""
    order = session.scalar(select(Order).where(Order.customer_id == customer_id, Order.status.in_(OPEN_STATUSES)))
    shipping = delivery.shipping_order(session, customer_id)
    if order is not None and order.change_wanted:
        return compose.with_greeting(texts[ASK_NEW.get(order.change_wanted, "ask_new_contact")], texts, True)
    if order is not None and order.status in ("cart", "confirmed"):
        view = cart.view(session, order)
        lines = cart.item_lines(session, order, texts)
        if lines:
            return render(texts["greeting_cart"], items="\n".join(lines), total=format_mmk(view.total),
                          next_step=cart.closing_line(session, order, texts))
    if order is not None and order.status == "waiting_payment":
        return render(texts["greeting_waiting_payment"], items_short=_items_short(session, order),
                      total=format_mmk(cart.view(session, order).total))
    if order is not None and order.status == "photo_received":
        return texts["greeting_photo_received"]
    if shipping is not None and shipping.status in ("paid", "packed"):
        return render(texts["greeting_preparing"], order_no=str(shipping.order_no))
    if shipping is not None and shipping.status == "sent_out":
        return render(texts["greeting_sent"], order_no=str(shipping.order_no),
                      sent_date=delivery.local_date(shipping.sent_out_at))
    return texts["greeting_reply"]


def reply(session: Session, customer_id: int, texts: dict[str, str], now: datetime | None = None) -> str:
    """body() without the leading "မင်္ဂလာပါ။" when we messaged them in the last 6 h."""
    text = body(session, customer_id, texts)
    lead = texts["greeting"].strip()
    if lead and text.startswith(lead) and not compose.needs_greeting(session, customer_id, now):
        text = text[len(lead):].lstrip(" \n")
    return text
