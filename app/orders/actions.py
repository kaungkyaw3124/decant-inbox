"""One-tap actions on a customer message (docs/SPEC-orders.md "One-tap quick replies",
"Step 4b").

For each message at most ONE action is offered, chosen from its parse and the cart:
  ask_price / ask_stock -> price        reply with the price(s)
  buy                   -> cart_add     add the known items + reply with the cart list
                                        (unknown / unpriced items: red rows + named in a note;
                                        out of stock: not added, out-of-stock line)
  remove                -> cart_remove  remove the items + reply with the cart list
  done                  -> cart_list    reply with the cart list
  confirm               -> confirm      confirm + ask the first missing thing (phone, then
                                        address) or send payment info when all is known
  phone(s) / address    -> contact      save them + ask what is still missing, or send
                                        payment info when everything is ready
So every customer reply gets exactly one next action: list -> confirm -> phone -> address
-> payment info.

The preview is made by running the action inside a savepoint and rolling it back, so the
text on the button is produced by exactly the same code as the real tap; the tap is
refused if the reply text differs (fingerprint). A reply waits UNDO_SECONDS in the outbox;
Undo reverses exactly what the action changed (stored in quick_actions.undo).
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Customer, Message, MessageReview, Order, Outbox, ParseItem, ParseResult, Product, QuickAction, User,
)
from app.models.outbox import UNDO_SECONDS
from app.orders import cart, unknown
from app.parser.normalize import normalize
from app.parser.rules import ADDRESS_RE, NEEDS_REVIEW_BELOW, find_phones
from app.pricing.prices import size_label
from app.replies import compose
from app.replies.templates import render

CONTEXT_WINDOW = timedelta(hours=24)
UNDO_WITHOUT_REPLY = timedelta(seconds=60)  # actions that send nothing can be undone this long
MIN_ADDRESS_LETTERS = 12  # a longer leftover counts as an address even without address words
# "one more of the same": only then does a product+size already in the cart get +qty
MORE_RE = re.compile(r"ထပ်|(?<![a-z])(?:more|another|again|extra)(?![a-z])|\+\s*1")


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
    address: str | None = None  # address this action saves (editable before the tap)


@dataclass(frozen=True)
class Suggestion:
    kind: str
    label: str
    text: str | None
    note: str
    fingerprint: str
    edit_url: str | None
    address: str | None = None

    @property
    def preview(self) -> str:
        line = " · ".join(t for t in (self.text or self.note).splitlines() if t.strip())
        return line if len(line) <= 90 else line[:89] + "…"

    @property
    def tooltip(self) -> str:
        return "\n\n".join(t for t in (self.text, self.note) if t)


def fingerprint(kind: str, text: str | None) -> str:
    """What the admin approves: the action and the exact reply (the address may be edited)."""
    return hashlib.sha256(json.dumps([kind, text]).encode()).hexdigest()[:16]


def upsert_review(db: Session, message_id: int, status: str, user: User | None, note: str | None = None) -> None:
    """user None = done by auto mode."""
    values = {"message_id": message_id, "status": status, "reviewed_by": user.id if user else None,
              "reviewed_at": datetime.now(UTC)}
    if note is not None:
        values["note"] = note.strip() or None
    stmt = insert(MessageReview).values(**values)
    db.execute(stmt.on_conflict_do_update(
        index_elements=["message_id"], set_={k: v for k, v in values.items() if k != "message_id"}))


# ---------- what the message says ----------

def _items(session: Session, result: ParseResult) -> list[ParseItem]:
    rows = session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)
                           .order_by(ParseItem.position)).all()
    if not rows and result.product_id is not None:  # a result without item rows
        rows = [ParseItem(product_id=result.product_id, size_ml=result.size_ml, is_full_bottle=False,
                          quantity=result.quantity, unknown_text=None, from_context=False)]
    return list(rows)


def _certain(items: list[ParseItem]) -> bool:
    return bool(items) and all(i.product_id and not i.unknown_text and not i.from_context for i in items)


def _wanted(i: ParseItem) -> cart.WantedItem:
    return cart.WantedItem(i.product_id, i.size_ml, i.is_full_bottle, i.quantity or 1,
                           None if i.product_id else i.unknown_text)


def contact_in(message: Message) -> tuple[list[str], str | None]:
    """(phones, address) found in a message. Address = the text without phones, if it
    has address words or is long enough."""
    phones = find_phones(message.normalized_text or "")
    address = cart.address_from_message(message.raw_text)
    letters = sum(c.isalpha() for c in address)
    if not letters or not (ADDRESS_RE.search(address.lower()) or letters >= MIN_ADDRESS_LETTERS):
        address = None
    return phones, address


# ---------- the actions (run for preview in a savepoint, and for real) ----------

def _order_state(order: Order) -> dict[str, Any]:
    return {"status": order.status, "confirmed_at": _iso(order.confirmed_at),
            "payment_info_sent_at": _iso(order.payment_info_sent_at), "list_sent_at": _iso(order.list_sent_at),
            "address": order.address, "phones": list(order.phones or [])}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _ask_next(session: Session, order: Order, texts: dict[str, str]) -> tuple[str | None, str | None, str]:
    """For a confirmed cart: (reply, reply_kind, label suffix) for the next step, phone first."""
    missing = cart.missing_contact(order)
    if "phone" in missing:
        return texts["ask_phone"], "ask_phone", " + ask phone"
    if "address" in missing:
        return texts["ask_address"], "ask_address", " + ask address"
    if order.status == "confirmed" and not cart.payment_problems(session, order):
        text = cart.payment_text(session, order, texts)
        cart.payment_info_sent(session, order)
        return text, "payment_info", " + 💳 send payment info"
    return None, None, ""


def _apply(session: Session, message: Message, result: ParseResult, texts: dict[str, str],
           address_override: str | None = None) -> Outcome | None:
    dropped = _not_stocked_lines(session, message, result, texts)
    outcome = _apply_items(session, message, result, texts, address_override, dropped)
    if not dropped or (outcome is not None and outcome.kind == "cart_add"):  # cart_add placed them itself
        return outcome
    if outcome is None:
        if any(i.product_id or i.unknown_text for i in _remaining(session, message, result)):
            return None  # something else in the message is still uncertain
        return Outcome("not_stocked", "💬 Reply: we don't have it", "\n".join(dropped), "custom")
    if outcome.text:
        outcome.text = "\n".join([outcome.text, *dropped])
    return outcome


def _remaining(session: Session, message: Message, result: ParseResult) -> list[ParseItem]:
    """Items without the ones the admin marked "we don't have it"."""
    dropped = unknown.not_stocked_texts(session, message.id)
    return [i for i in _items(session, result) if not (i.unknown_text and normalize(i.unknown_text) in dropped)]


def _not_stocked_lines(session: Session, message: Message, result: ParseResult, texts: dict[str, str]) -> list[str]:
    dropped = unknown.not_stocked_texts(session, message.id)
    return [render(texts["not_stocked_item"], name=i.unknown_text) for i in _items(session, result)
            if i.unknown_text and normalize(i.unknown_text) in dropped]


def _apply_items(session: Session, message: Message, result: ParseResult, texts: dict[str, str],
                 address_override: str | None, dropped: list[str]) -> Outcome | None:
    intent = result.intent
    customer = session.get(Customer, message.customer_id)
    items = _remaining(session, message, result)

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
        return _buy(session, message, customer, order, items, texts, dropped)
    if order is None or order.status not in ("cart", "confirmed", "waiting_payment"):
        return None
    before = _order_state(order)
    if intent == "remove":
        if not _certain(items):
            return None
        removed = cart.remove_items(session, order, [_wanted(i) for i in items])
        if not removed:
            return None
        order.list_sent_at = datetime.now(UTC)
        view = cart.view(session, order)
        return Outcome("cart_remove", "➖ Remove + send list", cart.cart_text(session, order, texts), "cart",
                       f"Removes {len(removed)} item(s); new total {view.total:,} ကျပ်.", order.id,
                       {"restore": removed, "order": before})
    if cart.view(session, order).empty:
        return None
    if intent == "done" and order.status == "cart":
        order.list_sent_at = datetime.now(UTC)
        return Outcome("cart_list", "💬 Send cart list", cart.cart_text(session, order, texts), "cart",
                       "", order.id, {"order": before})
    if intent == "confirm" and order.status == "cart":
        cart.confirm(session, order)
        cart.use_saved_contact(session, order, customer)  # "ok" to "same phone & address?" (returning)
        text, reply_kind, suffix = _ask_next(session, order, texts)
        return Outcome("confirm", "✅ Confirm" + suffix, text, reply_kind, "Cart confirmed.", order.id,
                       {"order": before})
    phones, address = contact_in(message)
    if address_override is not None and address is not None:
        address = address_override.strip()[:500] or address
    if phones or address:
        return _contact(session, message, customer, order, phones, address, texts, before)
    return None


def _buy(session: Session, message: Message, customer: Customer, order: Order | None,
         items: list[ParseItem], texts: dict[str, str], dropped: list[str]) -> Outcome | None:
    """Add what we know; unknown and unpriced items become red rows named in the reply;
    out-of-stock items are not added (out-of-stock line instead)."""
    if not items or any(i.from_context or (not i.product_id and not i.unknown_text) for i in items):
        return None  # a guessed or unnamed product: use the chat
    add, out_of_stock, sellable = [], [], 0
    for i in items:
        w = cart.normalize_wanted(session, _wanted(i))
        if w.product_id is not None:
            price, in_stock = cart.price_of(session, w.product_id, w.size_ml, w.is_full_bottle)
            if price is not None and not in_stock:
                out_of_stock.append(w)
                continue
            sellable += price is not None
        add.append(w)
    if not sellable:
        return None  # nothing we can sell from this message: use the chat
    created = order is None
    order = order or cart.open_cart(session, customer.id, create=True)
    if order.status not in ("cart", "confirmed", "waiting_payment"):
        return None
    before = _order_state(order)
    more = bool(MORE_RE.search(message.normalized_text or ""))
    changed = cart.add_items(session, order, add, message.id, more=more)
    order.list_sent_at = datetime.now(UTC)
    notes = []
    for w in out_of_stock:
        product = session.get(Product, w.product_id)
        notes.append(render(texts["out_of_stock"], product=product.name,
                            size=size_label(None if w.is_full_bottle else w.size_ml, product.full_size_ml)))
    lines = [cart.cart_text(session, order, texts, notes + dropped)]
    view = cart.view(session, order)
    partial = sellable < len(items)
    label = (f"🛒 Add {sellable} known item{'s' if sellable > 1 else ''} + send list" if partial
             else "🛒 Add to cart + send list")
    note = f"Cart total {view.total:,} ကျပ်."
    if view.problems:
        note += " To check (red in the cart): " + ", ".join(view.problems) + "."
    return Outcome("cart_add", label, "\n".join(lines), "cart", note, order.id,
                   {"added": [i for i in changed if i > 0], "removed": [-i for i in changed if i < 0],
                    "order": before, "created_order": created})


def _contact(session: Session, message: Message, customer: Customer, order: Order, phones: list[str],
             address: str | None, texts: dict[str, str], before: dict) -> Outcome | None:
    """Save phone(s) and/or address, then ask for what is still missing (phone first) or
    send payment info when everything is ready."""
    undo = {"order": before, "customer": {"address": customer.address},
            "phones": [list(r) for r in cart.phone_rows(session, customer.id)]}
    agreed = order.status == "cart"  # Step 4d: a phone or address while "cart" = the customer agrees
    if agreed:
        cart.confirm(session, order)
    added = cart.add_phones(session, order, customer, phones, message.id) if phones else []
    phones_new_on_order = bool(set(order.phones or []) - set(before["phones"]))
    new_address = address if address and address != order.address else None
    if new_address:
        cart.set_address(session, order, customer, new_address)
    if not phones_new_on_order and not new_address:
        return None  # nothing new
    if order.status == "confirmed":  # a returning customer: keep the saved part they didn't change
        cart.use_saved_contact(session, order, customer)
    shown_phones = ", ".join(added or [p for p in order.phones if p in phones])
    parts = ([f"📞 Save phone{'s' if len(phones) > 1 else ''}"] if phones_new_on_order else []) + (
        ["📍 Save address"] if new_address else [])
    label, text, reply_kind = ("✅ " if agreed else "") + " & ".join(parts), None, None
    if order.status == "confirmed":
        if phones_new_on_order and not new_address and not order.address:
            text = render(texts["phone_saved_ask_address"], phones=shown_phones)
            reply_kind, label = "contact", label + " + ask address"
        else:
            text, reply_kind, suffix = _ask_next(session, order, texts)
            label += suffix
    elif order.status == "waiting_payment" and added:  # payment info already sent: confirm the number
        text, reply_kind = render(texts["phone_added"], phone=", ".join(added)), "contact"
        label += " + reply"
    saved = ", ".join(x for x in (shown_phones if phones_new_on_order else "", new_address or "") if x)
    problems = cart.view(session, order).problems
    note = (("Counts as agreement: cart confirmed. " if agreed else "") + f"Saves: {saved}."
            + (f" Still to check before payment: {', '.join(problems)}." if problems else ""))
    return Outcome("contact", label, text, reply_kind, note, order.id, undo, address=new_address)


# ---------- suggest / perform / undo ----------

def _eligible(session: Session, message: Message, result: ParseResult | None, now: datetime) -> bool:
    if message.direction != "in" or result is None or not result.is_current:
        return False
    if result.method != "human" and result.confidence < NEEDS_REVIEW_BELOW and not _resolved(session, message, result):
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


def _resolved(session: Session, message: Message, result: ParseResult) -> bool:
    """Low confidence only because of unknown items that are clear by now: a buy (partial
    cart: unknown items become red rows) or items the admin resolved ("we don't have it")."""
    items = _items(session, result)
    if not items or any(i.from_context or (not i.product_id and not i.unknown_text) for i in items):
        return False
    return result.intent == "buy" or (result.intent in ("ask_price", "ask_stock")
                                      and not unknown.open_unknowns(session, message))


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
                      fingerprint(outcome.kind, outcome.text), _edit_url(message, outcome), outcome.address)


def _edit_url(message: Message, outcome: Outcome) -> str | None:
    if outcome.kind == "price":
        return f"/chats/{message.customer_id}?{outcome.edit_query}#reply"
    return f"/chats/{message.customer_id}?tab=cart#cart"


def perform(session: Session, message: Message, expect: str, user: User | None, texts: dict[str, str],
            address: str | None = None, delay: timedelta = timedelta(seconds=UNDO_SECONDS)) -> QuickAction:
    """Do the action the button showed (address: the admin's edited address, if any).
    user None = auto mode (app/orders/auto.py), which passes its own random delay.
    Raises Refused if the reply changed meanwhile."""
    auto = user is None
    user_id = None if auto else user.id
    session.execute(select(Customer.id).where(Customer.id == message.customer_id).with_for_update())
    now = datetime.now(UTC)
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    if not _eligible(session, message, result, now):
        raise Refused("Not possible any more (already handled, or a reply is waiting to go out).")
    outcome = _apply(session, message, result, texts, address_override=address)
    if outcome is not None:
        _with_greeting(session, outcome, message.customer_id, texts, now)
    if outcome is None or fingerprint(outcome.kind, outcome.text) != expect:
        raise Refused("Not sent: the reply changed (price, cart or parse). Check and try again.")
    review = session.scalar(select(MessageReview).where(MessageReview.message_id == message.id))
    outcome.undo["review"] = review.status if review else "new"
    outbox_id = None
    if outcome.text:
        box = Outbox(customer_id=message.customer_id, text=outcome.text, reply_kind=outcome.reply_kind,
                     status="queued", idempotency_key=f"quick-{message.id}-{now.timestamp()}", created_by=user_id,
                     send_after=now + delay, source_message_id=message.id,
                     previous_review_status=outcome.undo["review"])
        session.add(box)
        session.flush()
        outbox_id = box.id
    upsert_review(session, message.id, "done", user)
    action = QuickAction(message_id=message.id, customer_id=message.customer_id, kind=outcome.kind,
                         order_id=outcome.order_id, outbox_id=outbox_id, undo=outcome.undo, created_by=user_id,
                         auto=auto)
    session.add(action)
    session.flush()
    session.add(AuditLog(user_id=user_id, action=f"{'auto' if auto else 'quick'}.{outcome.kind}", details={
        "actor": "auto" if auto else "admin", "quick_action_id": action.id, "message_id": message.id,
        "customer_id": message.customer_id, "order_id": outcome.order_id, "outbox_id": outbox_id}))
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
        if "phones" in u:
            cart.set_customer_phones(session, customer, [tuple(r) for r in u["phones"]])
        if "customer" in u:
            customer.address = u["customer"]["address"]
        if "order" in u:
            o = u["order"]
            order.status, order.address, order.phones = o["status"], o["address"], o.get("phones", [])
            order.confirmed_at, order.payment_info_sent_at, order.list_sent_at = (
                _dt(o["confirmed_at"]), _dt(o["payment_info_sent_at"]), _dt(o["list_sent_at"]))
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


def contact_suggestion(session: Session, customer_id: int,
                       texts: dict[str, str]) -> tuple[Message, Suggestion] | None:
    """The newest message of this customer that would save an address (shown in the cart
    panel, where the address can be edited before the tap)."""
    rows = session.execute(
        select(Message, ParseResult).join(ParseResult, (ParseResult.message_id == Message.id) & ParseResult.is_current)
        .where(Message.customer_id == customer_id, Message.direction == "in")
        .order_by(Message.received_at.desc(), Message.id.desc()).limit(3)).all()
    for message, result in rows:
        s = suggest(session, message, result, texts)
        if s is not None and s.kind == "contact" and s.address:
            return message, s
    return None
