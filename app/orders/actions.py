"""One-tap actions on a customer message (docs/SPEC-orders.md "One-tap quick replies").

For each message at most ONE action is offered, chosen from its parse and the cart:
  ask_price / ask_stock -> price        reply with the price(s)
  buy                   -> cart_add     add the items + reply with the cart list
  remove                -> cart_remove  remove the items + reply with the cart list
  done                  -> cart_list    reply with the cart list
  confirm               -> confirm      confirm the cart (+ ask address & phone if unknown)
  address               -> address      save address (+ send payment info when ready)
Only offered when the data is complete (every item known, priced, in stock...).

The preview is made by running the action inside a savepoint and rolling it back, so the
text on the button is produced by exactly the same code as the real tap; the tap is
refused if the result differs (fingerprint). A reply waits UNDO_SECONDS in the outbox;
Undo reverses exactly what the action changed (stored in quick_actions.undo).
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Customer, Message, MessageReview, Order, Outbox, ParseItem, ParseResult, QuickAction, User,
)
from app.models.outbox import UNDO_SECONDS
from app.orders import cart
from app.parser.rules import NEEDS_REVIEW_BELOW
from app.replies import compose

CONTEXT_WINDOW = timedelta(hours=24)
UNDO_WITHOUT_REPLY = timedelta(seconds=60)  # actions that send nothing can be undone this long
CART_KINDS = ("cart_add", "cart_remove", "cart_list", "confirm", "address")


class Refused(Exception):
    """The action is not possible (any more)."""


@dataclass
class Outcome:
    kind: str
    label: str
    text: str | None  # reply to queue; None = nothing is sent
    reply_kind: str | None
    note: str = ""  # what else happens, shown under the button
    order_id: int | None = None
    undo: dict[str, Any] = field(default_factory=dict)
    edit_query: str = ""  # chat editor link parameters


@dataclass(frozen=True)
class Suggestion:
    kind: str
    label: str
    text: str | None
    note: str
    fingerprint: str
    edit_url: str | None

    @property
    def preview(self) -> str:
        line = " · ".join(t for t in (self.text or self.note).splitlines() if t.strip())
        return line if len(line) <= 90 else line[:89] + "…"

    @property
    def tooltip(self) -> str:
        return "\n\n".join(t for t in (self.text, self.note) if t)


def fingerprint(kind: str, text: str | None, note: str) -> str:
    return hashlib.sha256(json.dumps([kind, text, note]).encode()).hexdigest()[:16]


def upsert_review(db: Session, message_id: int, status: str, user: User | None, note: str | None = None) -> None:
    values = {"message_id": message_id, "status": status, "reviewed_by": user.id if user else None,
              "reviewed_at": datetime.now(UTC)}
    if note is not None:
        values["note"] = note.strip() or None
    stmt = insert(MessageReview).values(**values)
    db.execute(stmt.on_conflict_do_update(
        index_elements=["message_id"], set_={k: v for k, v in values.items() if k != "message_id"}))


# ---------- what the parse says ----------

def _items(session: Session, result: ParseResult) -> list[ParseItem]:
    rows = session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)
                           .order_by(ParseItem.position)).all()
    if not rows and result.product_id is not None:  # a result without item rows
        rows = [ParseItem(product_id=result.product_id, size_ml=result.size_ml, is_full_bottle=False,
                          quantity=result.quantity, unknown_text=None, from_context=False)]
    return list(rows)


def _certain(items: list[ParseItem]) -> bool:
    return bool(items) and all(i.product_id and not i.unknown_text and not i.from_context for i in items)


def _wanted(items: list[ParseItem]) -> list[cart.WantedItem]:
    return [cart.WantedItem(i.product_id, i.size_ml, i.is_full_bottle, i.quantity or 1) for i in items]


# ---------- the actions (run for preview in a savepoint, and for real) ----------

def _order_state(order: Order) -> dict[str, Any]:
    return {"status": order.status, "confirmed_at": _iso(order.confirmed_at),
            "payment_info_sent_at": _iso(order.payment_info_sent_at), "list_sent_at": _iso(order.list_sent_at),
            "address": order.address, "phone": order.phone}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _apply(session: Session, message: Message, result: ParseResult, texts: dict[str, str]) -> Outcome | None:
    intent = result.intent
    customer = session.get(Customer, message.customer_id)
    items = _items(session, result)

    if intent in ("ask_price", "ask_stock"):
        if not _certain(items):
            return None
        price_items = []
        for i in items:
            p = compose.PriceItem(i.product_id, "full" if i.is_full_bottle else str(i.size_ml) if i.size_ml else "all")
            if p not in price_items:
                price_items.append(p)
        if len(price_items) > compose.MAX_PRICE_ITEMS:
            return None
        made = compose.price_reply(session, price_items, texts)
        if made.problems or made.notes or not made.text:
            return None
        query = "".join(f"&p{n}={i.product_id}&s{n}={i.size}" for n, i in enumerate(price_items, 1))
        return Outcome("price", "💬 Reply price", made.text, "price", edit_query=f"compose=price&make=1{query}")

    order = cart.open_cart(session, customer.id)
    if intent == "buy":
        if not _certain(items):
            return None
        created = order is None
        order = order or cart.open_cart(session, customer.id, create=True)
        before = _order_state(order)
        changed = cart.add_items(session, order, _wanted(items), message.id)
        view = cart.view(session, order)
        if view.unpriced or any(_out_of_stock(session, i, p) for i, p in view.lines if i.id in changed):
            return None
        order.list_sent_at = datetime.now(UTC)
        return Outcome("cart_add", "🛒 Add to cart + send list", cart.cart_text(session, order, texts), "cart",
                       f"Adds {len(items)} item(s); cart total {view.total:,} ကျပ်.", order.id,
                       {"added": [i for i in changed if i > 0], "removed": [-i for i in changed if i < 0],
                        "order": before, "created_order": created})
    if order is None or order.status not in ("cart", "confirmed", "waiting_payment"):
        return None
    before = _order_state(order)
    if intent == "remove":
        if not _certain(items):
            return None
        removed = cart.remove_items(session, order, _wanted(items))
        if not removed:
            return None
        order.list_sent_at = datetime.now(UTC)
        view = cart.view(session, order)
        return Outcome("cart_remove", "➖ Remove + send list", cart.cart_text(session, order, texts), "cart",
                       f"Removes {len(removed)} item(s); new total {view.total:,} ကျပ်.", order.id,
                       {"restore": removed, "order": before})
    view = cart.view(session, order)
    if view.empty:
        return None
    if intent == "done" and order.status == "cart":
        order.list_sent_at = datetime.now(UTC)
        return Outcome("cart_list", "💬 Send cart list", cart.cart_text(session, order, texts), "cart",
                       "", order.id, {"order": before})
    if intent == "confirm" and order.status == "cart":
        cart.confirm(session, order)
        missing = cart.missing_contact(order, customer)
        if missing and customer.address and "address" in missing and "phone" not in missing:
            return Outcome("confirm", "✅ Confirm cart", None, None,
                           "Then choose in the cart: same address as last time, or ask for the address.",
                           order.id, {"order": before})
        if missing:
            return Outcome("confirm", "✅ Confirm + ask address & phone", texts["ask_address"], "ask_address",
                           "Cart confirmed.", order.id, {"order": before})
        return Outcome("confirm", "✅ Confirm cart", None, None, "Cart confirmed; next: send payment info.",
                       order.id, {"order": before})
    if intent == "address" and order.status in ("cart", "confirmed"):
        address = cart.address_from_message(message.raw_text)
        has_text = any(c.isalpha() for c in address)
        if not has_text and not result.phone:
            return None
        undo = {"order": before, "customer": {"address": customer.address, "phone": customer.phone}}
        cart.set_contact(session, order, customer, address if has_text else None, result.phone)
        saved = ", ".join(x for x in (address if has_text else None, result.phone) if x)
        if not cart.payment_problems(session, order, customer):
            text = cart.payment_text(session, order, texts)
            cart.payment_info_sent(session, order, customer)
            return Outcome("address", "📍 Save address + 💳 send payment info", text, "payment_info",
                           f"Saves: {saved}", order.id, undo)
        return Outcome("address", "📍 Save address", None, None, f"Saves: {saved}", order.id, undo)
    return None


def _out_of_stock(session: Session, item, product) -> bool:
    prices = {(p.size_ml, p.in_stock) for p in cart.current_prices(session, [product.id]).get(product.id, [])}
    size = None if item.is_full_bottle else item.size_ml
    return (size, False) in prices


# ---------- suggest / perform / undo ----------

def _eligible(session: Session, message: Message, result: ParseResult | None, now: datetime) -> bool:
    if message.direction != "in" or result is None or not result.is_current:
        return False
    if result.method != "human" and result.confidence < NEEDS_REVIEW_BELOW:
        return False
    if session.scalar(select(exists().where(QuickAction.message_id == message.id, QuickAction.undone_at.is_(None)))):
        return False  # already handled with a one-tap action
    if session.scalar(select(exists().where(Outbox.customer_id == message.customer_id,
                                            Outbox.status.in_(("queued", "sending"))))):
        return False  # a reply is waiting to go out: don't race it
    if result.intent in ("ask_price", "ask_stock"):
        return True
    if now - message.received_at > CONTEXT_WINDOW:
        return False
    # cart actions only for messages newer than the customer's last one-tap action
    last = session.scalar(select(Message.received_at).join(QuickAction, QuickAction.message_id == Message.id)
                          .where(QuickAction.customer_id == message.customer_id, QuickAction.undone_at.is_(None))
                          .order_by(Message.received_at.desc()).limit(1))
    return last is None or message.received_at > last


def _with_greeting(session: Session, outcome: Outcome, customer_id: int, texts: dict[str, str], now: datetime):
    if outcome.text:
        outcome.text = compose.with_greeting(outcome.text, texts, compose.needs_greeting(session, customer_id, now))
    return outcome


def suggest(session: Session, message: Message, result: ParseResult | None, texts: dict[str, str],
            now: datetime | None = None) -> Suggestion | None:
    now = now or datetime.now(UTC)
    if not _eligible(session, message, result, now):
        return None
    savepoint = session.begin_nested()
    try:
        outcome = _apply(session, message, result, texts)
        if outcome is not None:
            _with_greeting(session, outcome, message.customer_id, texts, now)
    finally:
        savepoint.rollback()
    if outcome is None:
        return None
    return Suggestion(outcome.kind, outcome.label, outcome.text, outcome.note,
                      fingerprint(outcome.kind, outcome.text, outcome.note), _edit_url(message, outcome))


def _edit_url(message: Message, outcome: Outcome) -> str | None:
    if outcome.kind == "price":
        return f"/chats/{message.customer_id}?{outcome.edit_query}#reply"
    return f"/chats/{message.customer_id}?tab=cart#cart"


def perform(session: Session, message: Message, expect: str, user: User, texts: dict[str, str]) -> QuickAction:
    """Do the action the button showed. Raises Refused if it changed meanwhile."""
    session.execute(select(Customer.id).where(Customer.id == message.customer_id).with_for_update())
    now = datetime.now(UTC)
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    if not _eligible(session, message, result, now):
        raise Refused("Not possible any more (already handled, or a reply is waiting to go out).")
    outcome = _apply(session, message, result, texts)
    if outcome is not None:
        _with_greeting(session, outcome, message.customer_id, texts, now)
    if outcome is None or fingerprint(outcome.kind, outcome.text, outcome.note) != expect:
        raise Refused("Not sent: the reply changed (price, cart or parse). Check and try again.")
    review = session.scalar(select(MessageReview).where(MessageReview.message_id == message.id))
    outcome.undo["review"] = review.status if review else "new"
    outbox_id = None
    if outcome.text:
        box = Outbox(customer_id=message.customer_id, text=outcome.text, reply_kind=outcome.reply_kind,
                     status="queued", idempotency_key=f"quick-{message.id}-{now.timestamp()}", created_by=user.id,
                     send_after=now + timedelta(seconds=UNDO_SECONDS), source_message_id=message.id,
                     previous_review_status=outcome.undo["review"])
        session.add(box)
        session.flush()
        outbox_id = box.id
    upsert_review(session, message.id, "done", user)
    action = QuickAction(message_id=message.id, customer_id=message.customer_id, kind=outcome.kind,
                         order_id=outcome.order_id, outbox_id=outbox_id, undo=outcome.undo, created_by=user.id)
    session.add(action)
    session.flush()
    session.add(AuditLog(user_id=user.id, action=f"quick.{outcome.kind}", details={
        "quick_action_id": action.id, "message_id": message.id, "customer_id": message.customer_id,
        "order_id": outcome.order_id, "outbox_id": outbox_id}))
    return action


def undo(session: Session, action: QuickAction, user: User) -> None:
    """Reverse an action. Raises Refused if its reply already went out (or too late)."""
    if action.undone_at is not None:
        return
    if action.outbox_id:
        box = session.scalar(select(Outbox).where(Outbox.id == action.outbox_id).with_for_update())
        if box.status != "queued":
            raise Refused("Too late to undo: it has already been sent.")
        box.status = "cancelled"
    elif datetime.now(UTC) - action.created_at > UNDO_WITHOUT_REPLY:
        raise Refused("Too late to undo; change it in the cart instead.")
    u = action.undo
    if action.order_id:
        order = session.get(Order, action.order_id)
        customer = session.get(Customer, action.customer_id)
        if u.get("added"):
            cart.remove_item_ids(session, order, u["added"])
        if u.get("removed"):
            cart.restore_item_ids(session, order, u["removed"])
        if u.get("restore"):
            cart.restore_item_ids(session, order, u["restore"])
        if "order" in u:
            o = u["order"]
            order.status, order.address, order.phone = o["status"], o["address"], o["phone"]
            order.confirmed_at, order.payment_info_sent_at, order.list_sent_at = (
                _dt(o["confirmed_at"]), _dt(o["payment_info_sent_at"]), _dt(o["list_sent_at"]))
        if "customer" in u:
            customer.address, customer.phone = u["customer"]["address"], u["customer"]["phone"]
        if u.get("created_order") and cart.view(session, order).empty:
            cart.cancel(session, order)
        cart.touch(session, order)
    upsert_review(session, action.message_id, u.get("review") or "new", user)
    action.undone_at = datetime.now(UTC)
    session.add(AuditLog(user_id=user.id, action="quick.undo", details={"quick_action_id": action.id}))


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def latest_actions(session: Session, message_ids: list[int]) -> dict[int, tuple[QuickAction, Outbox | None]]:
    """The live (not undone) action per message, with its reply."""
    if not message_ids:
        return {}
    rows = session.execute(select(QuickAction, Outbox).outerjoin(Outbox, Outbox.id == QuickAction.outbox_id)
                           .where(QuickAction.message_id.in_(message_ids), QuickAction.undone_at.is_(None))
                           .order_by(QuickAction.id))
    return {a.message_id: (a, o) for a, o in rows}
