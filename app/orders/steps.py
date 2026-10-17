"""Where a customer is, and how to bring them back (docs/SPEC-v4.10-interruptions.md).

step(): what the shop waits for —
  none              no open order (or a confirmed one with everything known)
  need_confirm      cart list sent with "…ကိုပဲ ပို့ပေးရမလား။" (saved phone + address)
  need_phone        no phone yet                    resume: the cart's phone question / ask_phone
  need_address      no address yet                  resume: ask_address
  waiting_new_info  4.8 "send the new address"      resume: ask_new_*
  waiting_payment   payment info sent, no photo     resume: resume_payment
  photo_received    screenshot being checked        (no resume line)
  locked            the latest order is paid (Order ID): nothing the customer can change
The resume line is added after an automatic / one-tap answer to something else, at most every
10 minutes per customer (setting resume_line_minutes), and never when the reply already asks
for that step.

Also here: locked paid orders, change requests a person must handle (Needs you), the "total
changed" history used by the payment card, and the "add it to this order?" offer.
"""
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from app.learning import patterns
from app.models import Customer, Message, Order, OrderEvent
from app.models.orders import LOCKED_STATUSES, OPEN_STATUSES
from app.orders import cart
from app.parser.rules import ParsedItem, ParseOutcome
from app.replies.templates import render

LOCKED_RECENT = timedelta(days=30)  # older paid orders: a new message is just a new conversation
SHIPPING_LOCKED = ("paid", "packed", "sent_out")  # not delivered yet: a new order is "another order"
OFFER_TTL = timedelta(hours=24)
NO_RESUME_KINDS = ("greeting", "change_info", "choose_previous", "choose_product", "hold", "locked", "cancel_order",
                   "delivery")
ASK_NEW = {"address": "ask_new_address", "phone": "ask_new_phone"}
RequestRef = aliased(OrderEvent)
YES_RE = re.compile(r"^(?:ok(?:ay)?|ok\s*ပါ|yes|ဟုတ်(?:ကဲ့)?|ဟုတ်ပါတယ်|ရ(?:ပါ)?တယ်|ထည့်(?:ပေး|မယ်)(?:ပါ)?|"
                    r"ယူ(?:ပါ)?မယ်|ok\s*ထည့်ပေး(?:ပါ)?|အဲ့ဒါပါ\s*ထည့်ပေး(?:ပါ)?)"
                    r"(?:\s*(?:ရှင့်|ရှင်|ခင်ဗျာ|ခင်ဗျ|နော်|ပါ|ဗျ|sis|pls|please))*[\s.!။]*$")


@dataclass
class Step:
    kind: str
    order: Order | None = None  # the open order (or the locked one)

    @property
    def locked(self) -> bool:
        return self.kind == "locked"


def locked_order(session: Session, customer_id: int, statuses=LOCKED_STATUSES) -> Order | None:
    """The customer's latest order with an Order ID (paid or later), from the last 30 days."""
    return session.scalar(select(Order).where(
        Order.customer_id == customer_id, Order.status.in_(statuses), Order.order_no.is_not(None),
        Order.paid_at >= datetime.now(UTC) - LOCKED_RECENT).order_by(Order.paid_at.desc()).limit(1))


def step(session: Session, customer_id: int) -> Step:
    order = session.scalar(select(Order).where(Order.customer_id == customer_id, Order.status.in_(OPEN_STATUSES)))
    if order is None:
        locked = locked_order(session, customer_id)
        return Step("locked", locked) if locked is not None else Step("none")
    if order.change_wanted:
        return Step("waiting_new_info", order)
    if order.status == "waiting_payment":
        return Step("waiting_payment", order)
    if order.status == "photo_received":
        return Step("photo_received", order)
    if cart.view(session, order).empty:
        return Step("none", order)
    customer = session.get(Customer, customer_id)
    phones = order.phones or (cart.customer_phones(session, customer_id) if order.status == "cart" else [])
    address = cart.order_address(order) or (cart.saved_address(customer) if order.status == "cart" else None)
    if not phones:
        return Step("need_phone", order)
    if not address:
        return Step("need_address", order)
    if order.status == "cart":
        return Step("need_confirm", order)
    return Step("none", order)


def resume_text(session: Session, s: Step, texts: dict[str, str]) -> str | None:
    if s.kind == "waiting_new_info":
        return texts[ASK_NEW.get(s.order.change_wanted, "ask_new_contact")]
    if s.kind == "waiting_payment":
        return texts["resume_payment"]
    if s.kind in ("need_phone", "need_address", "need_confirm"):
        if s.order.status == "cart":
            return cart.closing_line(session, s.order, texts)
        return texts["ask_phone"] if s.kind == "need_phone" else texts["ask_address"]
    return None


def with_resume(session: Session, kind: str, text: str | None, customer_id: int, texts: dict[str, str],
                now: datetime) -> tuple[str | None, bool]:
    """(the reply, with the resume line if one is due; whether it was added). Call it with the state
    AFTER the action (inside the preview savepoint / the real transaction)."""
    if not text or kind in NO_RESUME_KINDS:
        return text, False
    line = resume_text(session, step(session, customer_id), texts)
    if not line or line.strip() in text:
        return text, False  # nothing pending, or the reply asks for it already
    minutes = patterns.settings(session)["resume_line_minutes"]
    last = session.scalar(select(Customer.resume_line_at).where(Customer.id == customer_id))
    if minutes and last is not None and now - last < timedelta(minutes=minutes):
        return text, False
    return f"{text}\n{line}", True


# ---------- the "add it to this order?" offer (waiting for payment) ----------

def make_offer(order: Order, items: list[dict]) -> None:
    order.offer, order.offer_at = items, datetime.now(UTC)


def offer_answer(session: Session, message: Message, normalized: str) -> ParseOutcome | None:
    """"ok" / "ဟုတ်" / "ထည့်ပေး" right after we offered to add a priced item: buy those items."""
    if message.direction != "in" or not YES_RE.match(normalized or ""):
        return None
    order = session.scalar(select(Order).where(Order.customer_id == message.customer_id,
                                               Order.status == "waiting_payment", Order.offer.is_not(None)))
    if order is None or order.offer_at is None or not (
            order.offer_at <= message.received_at <= order.offer_at + OFFER_TTL):
        return None
    items = tuple(ParsedItem(o["product_id"], o.get("size_ml"), o.get("is_full_bottle", False), o.get("quantity", 1),
                             match="choice") for o in order.offer)
    first = items[0]
    return ParseOutcome("buy", first.product_id, first.size_ml, first.quantity, 0.9, items)


# ---------- history: total changes, change requests ----------

def record_total(session: Session, order: Order, old_total: int) -> OrderEvent | None:
    """While waiting for payment the total changed: kept for the payment card ("total changed at …")."""
    if old_total == order.total_mmk:
        return None
    event = OrderEvent(order_id=order.id, from_status=order.status, to_status=order.status, kind="total",
                       previous={"total": old_total, "new_total": order.total_mmk})
    session.add(event)
    session.flush()
    return event


def total_changes(session: Session, order_id: int) -> list[OrderEvent]:
    return list(session.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id, OrderEvent.kind == "total")
                                .order_by(OrderEvent.id)))


def record_request(session: Session, order: Order, message: Message, what: str) -> OrderEvent:
    """A change the customer asked for that a person must handle (photo sent / order locked)."""
    event = OrderEvent(order_id=order.id, from_status=order.status, to_status=order.status, kind="request",
                       previous={"what": what, "message_id": message.id, "text": (message.raw_text or "")[:300]})
    session.add(event)
    session.flush()
    return event


def open_requests(session: Session) -> list[tuple[OrderEvent, Order, Customer]]:
    """Needs you: requests without a later "done" (newest first)."""
    done = exists().where(OrderEvent.kind == "request_done", OrderEvent.previous["request_id"].as_integer()
                          == RequestRef.id)
    rows = session.execute(select(RequestRef, Order, Customer).join(Order, Order.id == RequestRef.order_id)
                           .join(Customer, Customer.id == Order.customer_id)
                           .where(RequestRef.kind == "request", ~done).order_by(RequestRef.id.desc())).all()
    return rows


def close_request(session: Session, request: OrderEvent, user, outcome: str) -> None:
    session.add(OrderEvent(order_id=request.order_id, from_status=request.from_status, to_status=request.to_status,
                           kind="request_done", previous={"request_id": request.id, "outcome": outcome},
                           created_by=user.id))


def locked_line(texts: dict[str, str], order: Order) -> str:
    return render(texts["order_locked"], order_no=str(order.order_no))

