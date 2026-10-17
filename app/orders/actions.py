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
  change_info           -> change_info  "I want to change the address / phone" (docs/SPEC-v4.8-change-info.md):
                                        ask for the new one; payment info waits; the next address /
                                        phone REPLACES the old one ("လိပ်စာ ပြင်ပြီးပါပြီ – …")
  ask_delivery          -> delivery     "preparing" / "sent on {date}" for a paid order
                                        (docs/SPEC-v3.md 6.1); no paid order: nothing
  cancel_order          -> cancel_order cancel an unpaid order + reply (6.4); once a payment
                                        screenshot came: nothing (Needs you, admin decides)
  FAQ question          -> faq          the FAQ answer (Step 7): first for other/unknown; for a
                                        price/stock/delivery question only when nothing else fits
  greeting              -> greeting     a message that is only a greeting: a reply that follows the order
                                        state (docs/SPEC-v4.9-greeting.md); not again within 30 min
  previous_item         -> cart_add     one earlier item: add it + list with "(အရင်ယူထားတဲ့ဟာ)" (4.3)
                        -> choose_previous  2-5 earlier items: numbered list; the answer "1" is a buy
Learned patterns (4.2) that are not approved yet still give the action, marked "📘", but only
as a one-tap button (auto mode skips them); accepting it unchanged counts a use.
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

from app.learning import patterns
from app.models import (
    AuditLog, ChoicePrompt, Customer, LearnedPattern, Message, MessageReview, Order, OrderEvent, Outbox, ParseItem,
    ParseResult, Product, QuickAction, UnknownRequest, User,
)
from app.models.outbox import UNDO_SECONDS
from app.orders import address, cart, change, delivery, previous, steps, unknown
from app.parser.normalize import normalize
from app.parser.rules import CHANGE_PHONE_RE, NEEDS_REVIEW_BELOW, change_kind, find_phones, replace_words
from app.pricing.prices import size_label
from app.replies import compose, faq
from app.replies.templates import render

CONTEXT_WINDOW = timedelta(hours=24)
UNDO_WITHOUT_REPLY = timedelta(seconds=60)  # actions that send nothing can be undone this long
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
    learned_pending: bool = False  # uses a learned pattern that is not approved yet (one-tap only)

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


def contact_in(session: Session, message: Message) -> tuple[list[str], address.Check | None]:
    """(phones, address reading) of a message. The reading went through the validator
    (docs/SPEC-v4.12-address-payment-ai.md): None = no address at all ("လိပ်စာ" or "ပို့ပေးပါ" alone is
    none, docs/SPEC-v4.8-change-info.md); otherwise valid / partial / invalid, and only a sure valid
    one is saved without a person."""
    return find_phones(message.normalized_text or ""), address.read_message(session, message)


def _override(read: address.Check | None, override: str | None) -> address.Check | None:
    """The admin's corrected address (cart panel / Needs you "check address") replaces the reading."""
    if override is None or read is None:
        return read
    return address.admin_check(override) if override.strip() else read


# ---------- the actions (run for preview in a savepoint, and for real) ----------

def _order_state(order: Order) -> dict[str, Any]:
    return {"status": order.status, "closed_at": _iso(order.closed_at), "confirmed_at": _iso(order.confirmed_at),
            "payment_info_sent_at": _iso(order.payment_info_sent_at), "list_sent_at": _iso(order.list_sent_at),
            "address": order.address, "phones": list(order.phones or []),
            "address_parts": order.address_parts, "address_invalid": order.address_invalid,
            "address_partial": order.address_partial, "address_partial_at": _iso(order.address_partial_at),
            "change_wanted": order.change_wanted, "change_asked_at": _iso(order.change_asked_at),
            "offer": order.offer, "offer_at": _iso(order.offer_at)}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _ask_next(session: Session, order: Order, texts: dict[str, str]) -> tuple[str | None, str | None, str]:
    """For a confirmed cart: (reply, reply_kind, label suffix) for the next step, phone first.
    While the customer's new address / phone is awaited (docs/SPEC-v4.8-change-info.md): ask for it
    again, never payment info with the old one."""
    if order.change_wanted:
        key = {"address": "ask_new_address", "phone": "ask_new_phone"}.get(order.change_wanted, "ask_new_contact")
        return texts[key], "contact", " + ask the new address / phone again"
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


def _faq(match: faq.Match) -> Outcome:
    return Outcome("faq", f"💬 Send FAQ: {match.entry.title}", match.entry.answer, "faq",
                   f"FAQ “{match.entry.title}” (keywords: {', '.join(match.keywords)}).")


def _apply(session: Session, message: Message, result: ParseResult, texts: dict[str, str],
           address_override: str | None = None) -> Outcome | None:
    if result.intent == "greeting":  # docs/SPEC-v4.9-greeting.md: always answered, by where the customer is
        from app.orders import greeting  # late import: greeting -> cart / delivery

        if not patterns.settings(session)["greeting"] or greeting.greeted_recently(session, message.customer_id):
            return None  # switched off, or a greeting reply went out in the last 30 min (Needs you)
        return Outcome("greeting", "👋 Reply greeting", greeting.reply(session, message.customer_id, texts),
                       "greeting")
    match = faq.for_message(session, message, result)
    if match is not None and result.intent in faq.FIRST_INTENTS:
        return _faq(match)
    dropped = _not_stocked_lines(session, message, result, texts)
    outcome = _apply_items(session, message, result, texts, address_override, dropped)
    if outcome is None and match is not None and not dropped:
        return _faq(match)  # e.g. "kpay ရလား", "deli ဘယ်နှစ်ရက်ကြာလဲ" without an order
    if not dropped or (outcome is not None and outcome.kind in ("cart_add", "cart_change")):  # placed them itself
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
    if any(i.candidates and not i.product_id for i in items):  # docs/SPEC-v4.11-ai-first.md L3: which one?
        return _choose_product(session, message, customer, result, items, texts)

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
        text, note, undo, order_id = made.text, "", {}, None
        waiting = cart.open_cart(session, customer.id)
        if waiting is not None and waiting.status == "waiting_payment" and not waiting.change_wanted \
                and all(i.size_ml or i.is_full_bottle for i in items):
            # docs/SPEC-v4.10-interruptions.md: "add it to this order?"; "ok" next adds it
            undo, order_id = {"order": _order_state(waiting)}, waiting.id
            steps.make_offer(waiting, [{"product_id": i.product_id, "size_ml": None if i.is_full_bottle else i.size_ml,
                                        "is_full_bottle": i.is_full_bottle, "quantity": i.quantity or 1} for i in items])
            text, note = f"{text}\n{texts['offer_add']}", "Offers to add it to the order waiting for payment."
        return Outcome("price", "💬 Reply price", text, "price", note, order_id, undo,
                       edit_query=f"compose=price&make=1{query}")

    if intent == "ask_delivery":
        shipping = delivery.shipping_order(session, customer.id)
        if shipping is None:
            return None  # no paid order: the admin answers (Needs you)
        return Outcome("delivery", "💬 Reply delivery status", delivery.status_answer(shipping, texts), "delivery",
                       f"Order #{shipping.order_no} is {shipping.status.replace('_', ' ')}.")
    order = cart.open_cart(session, customer.id)
    # docs/SPEC-v4.10-interruptions.md: "I paid" in words; changes after the screenshot; locked paid orders
    if intent == "payment_sent":
        return _payment_sent(order, texts)
    phones, read = contact_in(session, message)
    read = _override(read, address_override)
    asks_change = intent in ("buy", "previous_item", "remove", "change_info", "modify_cart") or (
        intent == "address" and bool(phones or read))
    if order is not None and order.status == "photo_received" and asks_change:
        return _hold_request(session, message, order, intent, texts)
    locked = steps.locked_order(session, customer.id)
    if locked is not None and intent in ("remove", "change_info", "address", "modify_cart") and asks_change and (
            order is None or (intent == "change_info" and order.status == "cart" and not order.address
                              and not order.phones and locked.status in steps.SHIPPING_LOCKED)):
        return _locked(session, message, locked, intent, texts)  # nothing is changed; Needs you
    if intent == "modify_cart":  # L2: removes + adds / price questions in one message, one reply
        return _modify(session, message, customer, order, items, texts, dropped)
    if intent == "previous_item":
        return _previous(session, message, customer, order, result, texts)
    if intent == "cancel_order":
        if order is None or order.status not in ("cart", "confirmed", "waiting_payment") \
                or delivery.has_payment_photo(session, order):
            return None  # nothing to cancel, or money may be involved: the admin decides
        before = _order_state(order)
        cart.cancel(session, order)
        order.cancel_note = "customer cancelled"
        return Outcome("cancel_order", "🚫 Cancel order + reply", texts["order_cancelled"], "cancel",
                       f"Cancels the {before['status'].replace('_', ' ')} order "
                       f"({order.total_mmk:,} ကျပ်).", order.id, {"order": before})
    if intent == "change_info":
        return _change(session, message, customer, texts, address_override)
    if intent == "buy":
        return _buy(session, message, customer, order, items, texts, dropped)
    if order is None or order.status not in ("cart", "confirmed", "waiting_payment"):
        return None
    before = _order_state(order)
    if intent == "remove":
        if not _certain(items):
            return None
        old_total = order.total_mmk
        removed = cart.remove_items(session, order, [_wanted(i) for i in items])
        if not removed:
            return None
        order.list_sent_at = datetime.now(UTC)
        view = cart.view(session, order)
        undo = {"restore": removed, "order": before}
        if view.empty:  # the last item: the order is cancelled
            cart.cancel(session, order)
            order.cancel_note = "customer removed every item"
            return Outcome("cancel_order", "🚫 Remove the last item = cancel + reply", texts["order_cancelled"],
                           "cancel", f"Removes {len(removed)} item(s): nothing left, the order is cancelled.",
                           order.id, undo)
        if before["status"] == "waiting_payment":
            _keep_waiting(session, order, before, old_total, undo)
            return Outcome("cart_remove", "➖ Remove + 💳 payment info with the new total",
                           cart.payment_text(session, order, texts, changed=True), "payment_info",
                           f"Removes {len(removed)} item(s); new total {view.total:,} ကျပ်. Still waiting for payment.",
                           order.id, undo)
        return Outcome("cart_remove", "➖ Remove + send list", cart.cart_text(session, order, texts), "cart",
                       f"Removes {len(removed)} item(s); new total {view.total:,} ကျပ်.", order.id, undo)
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
    if phones or read:
        return _contact(session, message, customer, order, phones, read, texts, before)
    return None


INTENT_ACTION = {"buy": "add", "previous_item": "add", "ask_price": "ask_price", "ask_stock": "ask_price",
                 "remove": "remove"}
ACTION_INTENT = {"add": "buy", "ask_price": "ask_price", "remove": "remove"}


def item_action(result: ParseResult, item: ParseItem) -> str | None:
    """add | remove | ask_price: the item's own action (L2), else what the message intent says."""
    return item.action or INTENT_ACTION.get(result.intent)


def _choose_product(session: Session, message: Message, customer: Customer, result: ParseResult,
                    items: list[ParseItem], texts: dict[str, str]) -> Outcome | None:
    """docs/SPEC-v4.11-ai-first.md L3: "ysl 10ml" = Y EDP or Libre? Ask the CUSTOMER (numbered); their
    answer "1" / "၂" / the name continues the original action with the message's other items."""
    asked = next(i for i in items if i.candidates and not i.product_id)
    action = item_action(result, asked)
    if action not in ("add", "ask_price") or any(i.from_context for i in items):
        return None  # which one to REMOVE: a person looks at the cart
    if action == "add" and not (asked.size_ml or asked.is_full_bottle):
        return None
    pending = []
    for i in items:
        if i is asked:
            continue
        if not i.product_id or i.unknown_text or (i.candidates and not i.product_id):
            return None  # something else is unclear too: a person decides
        pending.append({"product_id": i.product_id, "size_ml": i.size_ml, "is_full_bottle": i.is_full_bottle,
                        "quantity": i.quantity or 1, "action": item_action(result, i)})
    products = {p.id: p for p in session.scalars(select(Product).where(Product.id.in_(asked.candidates),
                                                                       Product.active))}
    options = [{"product_id": pid, "size_ml": None if asked.is_full_bottle else asked.size_ml,
                "is_full_bottle": asked.is_full_bottle} for pid in asked.candidates if pid in products]
    if not 2 <= len(options) <= 3:
        return None
    prompt = ChoicePrompt(customer_id=customer.id, message_id=message.id, options=options,
                          quantity=asked.quantity or 1, kind="product", action=action, pending=pending or None,
                          expires_at=datetime.now(UTC) + previous.PROMPT_TTL)
    session.add(prompt)
    session.flush()
    size = size_label(None if asked.is_full_bottle else asked.size_ml,
                      products[options[0]["product_id"]].full_size_ml) if (asked.size_ml or asked.is_full_bottle) \
        else ""
    words = " ".join(filter(None, [asked.name_text or "", size])).strip() or (message.raw_text or "")[:40]
    lines = "\n".join(f"{n}. {previous.label(session, o) if (o['size_ml'] or o['is_full_bottle']) else products[o['product_id']].name}"
                      for n, o in enumerate(options, 1))
    return Outcome("choose_product", "🔢 Ask the customer which product", render(texts["choose_product"], words=words,
                                                                                 options=lines),
                   "choice", f"“{words}” fits {len(options)} products; their answer “1” / the name continues.",
                   undo={"prompt": prompt.id})


def _modify(session: Session, message: Message, customer: Customer, order: Order | None, items: list[ParseItem],
            texts: dict[str, str], dropped: list[str]) -> Outcome | None:
    """docs/SPEC-v4.11-ai-first.md L2: remove + add (+ price questions) in one message, ONE reply:
    removed lines, not-stocked lines, prices, then the list + total (or "nothing left"), or payment
    info again with the new total while waiting for payment."""
    if any(i.from_context or not i.product_id or i.unknown_text or not i.action for i in items):
        return None  # something is unclear: a person decides
    removes = [i for i in items if i.action == "remove"]
    adds = [i for i in items if i.action == "add"]
    asks = [i for i in items if i.action == "ask_price"]
    if order is None and not adds:
        return None
    if order is not None and order.status not in ("cart", "confirmed", "waiting_payment"):
        return None
    waiting = order is not None and order.status == "waiting_payment"
    wanted = []
    for i in adds:
        w = cart.normalize_wanted(session, _wanted(i))
        price, in_stock = cart.price_of(session, w.product_id, w.size_ml, w.is_full_bottle)
        if price is None or not in_stock:
            return None  # no price / out of stock: a person answers
        wanted.append(w)
    price_text = ""
    if asks:
        price_items = list(dict.fromkeys(compose.PriceItem(i.product_id, "full" if i.is_full_bottle else str(
            i.size_ml) if i.size_ml else "all") for i in asks))
        made = compose.price_reply(session, price_items, texts)
        if made.problems or made.notes or not made.text:
            return None
        price_text = made.text
    created = order is None
    order = order or cart.open_cart(session, customer.id, create=True)
    before = _order_state(order)
    old_total = order.total_mmk
    removed = cart.remove_items(session, order, [_wanted(i) for i in removes]) if removes else []
    changed = cart.add_items(session, order, wanted, message.id,
                             more=bool(MORE_RE.search(message.normalized_text or ""))) if wanted else []
    if not removed and not changed and not price_text:
        return None  # nothing happened (removes of items not in the cart)
    undo = {"restore": removed, "added": [i for i in changed if i > 0], "removed": [-i for i in changed if i < 0],
            "order": before, "created_order": created}
    lines = []
    for i in removes:
        product = session.get(Product, i.product_id)
        size = size_label(None if i.is_full_bottle else i.size_ml, product.full_size_ml) \
            if (i.size_ml or i.is_full_bottle) else ""
        lines.append(render(texts["item_removed"], product=f"{product.name} {size}".strip()))
    lines += dropped
    if price_text:
        lines.append(price_text)
    order.list_sent_at = datetime.now(UTC)
    view = cart.view(session, order)
    note = f"Removes {len(removed)} item(s), adds {len(wanted)}."
    if view.empty:
        cart.cancel(session, order)
        order.cancel_note = "customer removed every item"
        lines.append(texts["cart_empty"])
        return Outcome("cart_change", "🔁 Change the cart + reply (nothing left)", "\n".join(lines), "cart",
                       note + " Nothing left: the order is cancelled.", order.id, undo)
    if waiting and order.total_mmk != old_total:
        _keep_waiting(session, order, before, old_total, undo)
        lines.append(cart.payment_text(session, order, texts, changed=True))
        return Outcome("cart_change", "🔁 Change the cart + 💳 payment info with the new total", "\n".join(lines),
                       "payment_info", note + f" New total {view.total:,} ကျပ်. Still waiting for payment.", order.id,
                       undo)
    lines.append(cart.cart_text(session, order, texts))
    return Outcome("cart_change", "🔁 Change the cart + send list", "\n".join(lines), "cart",
                   note + f" Cart total {view.total:,} ကျပ်.", order.id, undo)


def _payment_sent(order: Order | None, texts: dict[str, str]) -> Outcome | None:
    """"ငွေလွှဲပြီးပါပြီ" without a photo: ask for the screenshot (being checked: "we'll check")."""
    if order is None or order.status not in ("waiting_payment", "photo_received"):
        return None  # no payment info sent yet / already paid: a person answers
    if order.status == "photo_received":
        return Outcome("hold", "💬 Reply “we'll check”", texts["hold_check"], "hold",
                       "The screenshot is waiting in Payments.", order.id)
    return Outcome("hold", "📷 Ask for the screenshot", texts["ask_screenshot"], "hold",
                   "Says they paid; the screenshot is what counts.", order.id)


_WHAT = {"buy": "add items", "previous_item": "add earlier items", "remove": "remove items",
         "change_info": "change address / phone", "address": "new address / phone"}


def _hold_request(session: Session, message: Message, order: Order, intent: str,
                  texts: dict[str, str]) -> Outcome:
    """The payment screenshot is being checked: change nothing, "we'll check", Needs you (4.10)."""
    event = steps.record_request(session, order, message, _WHAT.get(intent, intent))
    return Outcome("hold", "⏸ Reply “we'll check” + Needs you", texts["hold_check"], "hold",
                   f"Payment screenshot sent: nothing is changed. Needs you: {_WHAT.get(intent, intent)}.",
                   order.id, {"events": [event.id]})


def _locked(session: Session, message: Message, order: Order, intent: str, texts: dict[str, str]) -> Outcome:
    """Paid orders are locked (owner rule, 4.10): the locked reply, nothing changed, Needs you."""
    event = steps.record_request(session, order, message, _WHAT.get(intent, intent))
    return Outcome("locked", f"🔒 Reply “Order #{order.order_no} can't be changed” + Needs you",
                   steps.locked_line(texts, order), "hold",
                   f"Order #{order.order_no} is paid: nothing is changed. Needs you: {_WHAT.get(intent, intent)}.",
                   order.id, {"events": [event.id]})


def _keep_waiting(session: Session, order: Order, before: dict, old_total: int, undo: dict) -> None:
    """Items changed while waiting for payment: still waiting (payment info goes again with the new
    total); the change is kept for the payment card."""
    order.status = "waiting_payment"
    order.confirmed_at = _dt(before["confirmed_at"])
    order.payment_info_sent_at = datetime.now(UTC)
    order.offer = order.offer_at = None
    event = steps.record_total(session, order, old_total)
    if event is not None:
        undo.setdefault("events", []).append(event.id)


def _buy(session: Session, message: Message, customer: Customer, order: Order | None,
         items: list[ParseItem], texts: dict[str, str], dropped: list[str]) -> Outcome | None:
    """Add what we know; unknown and unpriced items become red rows named in the reply;
    out-of-stock items are not added (out-of-stock line instead)."""
    if not items or any(i.from_context or (not i.product_id and not i.unknown_text) for i in items):
        return None  # a guessed or unnamed product: use the chat
    waiting = order is not None and order.status == "waiting_payment"
    if waiting and any(not i.product_id for i in items):
        return None  # unknown item while waiting for payment: "we'll check" + teaching card (auto mode)
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
    if waiting and (out_of_stock or sellable < len(add)):
        return None  # no price / out of stock while waiting for payment: a person answers
    created = order is None
    locked = steps.locked_order(session, customer.id, steps.SHIPPING_LOCKED) if created else None
    order = order or cart.open_cart(session, customer.id, create=True)
    if order.status not in ("cart", "confirmed", "waiting_payment"):
        return None
    before = _order_state(order)
    old_total = order.total_mmk
    more = bool(MORE_RE.search(message.normalized_text or ""))
    changed = cart.add_items(session, order, add, message.id, more=more)
    order.list_sent_at = datetime.now(UTC)
    undo = {"added": [i for i in changed if i > 0], "removed": [-i for i in changed if i < 0],
            "order": before, "created_order": created}
    if waiting:  # docs/SPEC-v4.10-interruptions.md: same order, new total, payment info again
        _keep_waiting(session, order, before, old_total, undo)
        view = cart.view(session, order)
        return Outcome("cart_add", "🛒 Add + 💳 payment info with the new total",
                       "\n".join([cart.payment_text(session, order, texts, changed=True), *dropped]), "payment_info",
                       f"Adds to the order waiting for payment; new total {view.total:,} ကျပ်.", order.id, undo)
    notes = []
    for w in out_of_stock:
        product = session.get(Product, w.product_id)
        notes.append(render(texts["out_of_stock"], product=product.name,
                            size=size_label(None if w.is_full_bottle else w.size_ml, product.full_size_ml)))
    lines = [cart.cart_text(session, order, texts, notes + dropped)]
    if locked is not None:  # the paid order is locked: this is a NEW order
        lines.insert(0, render(texts["locked_new_order"], order_no=str(locked.order_no)))
    view = cart.view(session, order)
    partial = sellable < len(items)
    label = (f"🛒 Add {sellable} known item{'s' if sellable > 1 else ''} + send list" if partial
             else "🛒 Add to cart + send list")
    note = f"Cart total {view.total:,} ကျပ်."
    if view.problems:
        note += " To check (red in the cart): " + ", ".join(view.problems) + "."
    if locked is not None:
        note = f"Order #{locked.order_no} is paid and locked: a NEW order. " + note
    return Outcome("cart_add", label, "\n".join(lines), "cart", note, order.id, undo)


def _previous(session: Session, message: Message, customer: Customer, order: Order | None, result: ParseResult,
              texts: dict[str, str]) -> Outcome | None:
    """"ဟိုနေ့ကဟာ ထပ်ယူမယ်": one earlier item -> add it; several -> ask which (numbered)."""
    found = previous.candidates(session, message)
    qty = result.quantity or 1
    if len(found) == 1:
        c = found[0]
        item = ParseItem(product_id=c.product_id, size_ml=c.size_ml, is_full_bottle=c.is_full_bottle, quantity=qty,
                         unknown_text=None, from_context=False)
        product = session.get(Product, c.product_id)
        line = render(texts["previous_item_line"], product=product.name,
                      size=size_label(None if c.is_full_bottle else c.size_ml, product.full_size_ml))
        outcome = _buy(session, message, customer, order, [item], texts, [line])
        if outcome is not None:
            outcome.label = "🛒 Add the earlier item + send list"
        return outcome
    if not found:
        return None  # nothing earlier: Needs you (teaching card)
    options = [c.as_option() for c in found[:previous.MAX_OPTIONS]]
    prompt = ChoicePrompt(customer_id=customer.id, message_id=message.id, options=options, quantity=qty,
                          expires_at=datetime.now(UTC) + previous.PROMPT_TTL)
    session.add(prompt)
    session.flush()
    lines = "\n".join(f"{n}. {previous.label(session, o)}" for n, o in enumerate(options, 1))
    return Outcome("choose_previous", "🔢 Ask which earlier item", render(texts["choose_previous"], options=lines),
                   "choice", f"{len(options)} earlier items; their answer “1”, “1 နဲ့ 2”, “အကုန်” adds them.",
                   undo={"prompt": prompt.id})


def _change(session: Session, message: Message, customer: Customer, texts: dict[str, str],
            address_override: str | None) -> Outcome | None:
    """"လိပ်စာ ပြောင်းချင်ပါတယ်" (docs/SPEC-v4.8-change-info.md): ask for the new address / phone; the
    order waits for it (no payment info meanwhile). With the new info in the same message
    ("လိပ်စာအသစ် ဗဟန်း …"): replace at once. An order already sent out: nothing (Needs you)."""
    order = change.target_order(session, customer.id)
    if order is None or order.status in change.SENT:
        return None
    kind = change_kind(message.normalized_text or "") or "unclear"
    before = _order_state(order)
    phones, read = contact_in(session, message)
    read = _override(read, address_override)
    if phones or read:
        order.change_wanted = kind
        return _contact(session, message, customer, order, phones, read, texts, before, True)
    order.change_wanted, order.change_asked_at = kind, datetime.now(UTC)
    cart.touch(session, order)
    key, what = {"address": ("ask_new_address", "address"), "phone": ("ask_new_phone", "phone")}.get(
        kind, ("ask_new_contact", "address + phone"))
    note = f"The customer wants to change the {what}. Payment info waits for the new one."
    if order.status in change.AFTER_PAYMENT:
        note += " Already paid: the new one is saved on the order and shown in Needs you to check."
    return Outcome("change_info", f"📍 Ask for the new {what}", texts[key], "contact", note, order.id,
                   {"order": before})


def _contact(session: Session, message: Message, customer: Customer, order: Order, phones: list[str],
             read: address.Check | None, texts: dict[str, str], before: dict, replace: bool = False) -> Outcome | None:
    """Save phone(s) and/or address, then ask for what is still missing (phone first) or
    send payment info when everything is ready.

    replace (docs/SPEC-v4.8-change-info.md): after "change my address / phone", or with "ဒီလိပ်စာကို
    ပို့ပေးပါ …" / "this address": the new address replaces the order's and the customer's; a new
    phone becomes the order's only phone and the customer's phone 1. A phone without change words
    is added (as before). The reply starts with "လိပ်စာ ပြင်ပြီးပါပြီ – …"; payment info follows if
    it was not sent yet (never sent twice).

    docs/SPEC-v4.12-address-payment-ai.md: only a sure, valid reading is saved; anything else waits
    for a person (Needs you "📍 check address")."""
    if read is not None and read.status == "partial" and read.source != "admin":
        return _ask_missing(session, message, customer, order, phones, read, texts, before)
    if read is not None and not read.sure:
        if read.source == "admin":  # the admin's corrected address must pass the validator too
            raise Refused("Not saved: " + read.why)
        return None
    new_text = read.parts.full_text if read is not None else None
    text_norm = message.normalized_text or ""
    want = order.change_wanted
    replace = replace or bool(want) or replace_words(text_norm) or bool(read and read.is_change_request) or (
        order.status == "waiting_payment" and bool(new_text) and bool(order.address) and new_text != order.address)
    undo = {"order": before, "customer": {"address": customer.address, "address_parts": customer.address_parts,
                                          "address_invalid": customer.address_invalid},
            "phones": [list(r) for r in cart.phone_rows(session, customer.id)]}
    old_address = order.address or customer.address
    old_phones = list(order.phones or []) or cart.customer_phones(session, customer.id)
    agreed = order.status == "cart"  # Step 4d: a phone or address while "cart" = the customer agrees
    if agreed:
        cart.confirm(session, order)
    replace_phone = bool(phones) and (want in ("phone", "both", "unclear") or bool(CHANGE_PHONE_RE.search(text_norm)))
    if replace_phone:
        added = cart.replace_phones(session, order, customer, phones, message.id)
        phones_new_on_order = added != before["phones"]
    else:
        added = cart.add_phones(session, order, customer, phones, message.id) if phones else []
        phones_new_on_order = bool(set(order.phones or []) - set(before["phones"]))
    new_address = new_text if new_text and (new_text != order.address or order.address_invalid
                                            or (replace and new_text != old_address)) else None
    if new_address:
        cart.set_address(session, order, customer, read)
    if want and (new_address or phones_new_on_order):
        order.change_wanted = order.change_asked_at = None  # the new info came
    if not phones_new_on_order and not new_address:
        return None  # nothing new
    if order.status == "confirmed":  # a returning customer: keep the saved part they didn't change
        cart.use_saved_contact(session, order, customer)
    updated = []
    if replace and new_address:
        updated.append(render(texts["address_updated"], address=new_address))
    if replace_phone and phones_new_on_order:
        updated.append(render(texts["phone_updated"], phone=", ".join(added)))
    shown_phones = ", ".join(added or [p for p in order.phones if p in phones])
    parts = ([f"📞 {'Replace' if replace_phone else 'Save'} phone{'s' if len(phones) > 1 else ''}"]
             if phones_new_on_order else []) + (
        [f"📍 {'Replace' if updated and replace else 'Save'} address"] if new_address else [])
    label, text, reply_kind = ("✅ " if agreed else "") + " & ".join(parts), None, None
    if order.status == "confirmed":
        if phones_new_on_order and not new_address and not cart.order_address(order):
            text = render(texts["phone_saved_ask_address"], phones=shown_phones)
            reply_kind, label = "contact", label + " + ask address"
        else:
            text, reply_kind, suffix = _ask_next(session, order, texts)
            label += suffix
        if updated:  # "လိပ်စာ ပြင်ပြီးပါပြီ – …" first, then payment info / the next question
            text, reply_kind = "\n".join(updated + ([text] if text else [])), reply_kind or "contact"
            label += " + confirm the change" if reply_kind == "contact" else ""
    elif order.status == "waiting_payment":  # payment info already sent: not again (amount unchanged)
        if updated:
            text, reply_kind, label = "\n".join(updated), "contact", label + " + confirm the change"
        elif added:
            text, reply_kind = render(texts["phone_added"], phone=", ".join(added)), "contact"
            label += " + reply"
    elif order.status in change.AFTER_PAYMENT and updated:
        text, reply_kind, label = "\n".join(updated), "contact", label + " + confirm the change"
    if (new_address and old_address and new_address != old_address) or (replace_phone and phones_new_on_order):
        event = OrderEvent(order_id=order.id, from_status=order.status, to_status=order.status, kind="contact",
                           previous={"address": old_address, "phones": old_phones,
                                     "new_address": order.address, "new_phones": list(order.phones or []),
                                     "message_id": message.id})
        session.add(event)
        session.flush()
        undo["events"] = [event.id]
    saved = ", ".join(x for x in (shown_phones if phones_new_on_order else "", new_address or "") if x)
    problems = cart.view(session, order).problems
    note = (("Counts as agreement: cart confirmed. " if agreed else "") + f"Saves: {saved}."
            + (f" Replaces the old one{'s' if replace_phone and len(old_phones) > 1 else ''}." if updated else "")
            + (" Paid already: Needs you shows the change to check." if order.status in change.AFTER_PAYMENT else "")
            + (f" Still to check before payment: {', '.join(problems)}." if problems else ""))
    return Outcome("contact", label, text, reply_kind, note, order.id, undo, address=new_address)


def _ask_missing(session: Session, message: Message, customer: Customer, order: Order, phones: list[str],
                 read: address.Check, texts: dict[str, str], before: dict) -> Outcome:
    """docs/SPEC-v4.12-address-payment-ai.md N1: a street / number without the township (or city): keep
    it on the order for 24 h and ask "ဘယ်မြို့နယ်လဲ"; the answer is merged with it (address.read_message)."""
    undo = {"order": before, "phones": [list(r) for r in cart.phone_rows(session, customer.id)]}
    agreed = order.status == "cart"  # like an address: the customer agrees to the list
    if agreed:
        cart.confirm(session, order)
    added = cart.add_phones(session, order, customer, phones, message.id) if phones else []
    order.address_partial, order.address_partial_at = {**read.parts.to_json(), "_ask": read.ask}, datetime.now(UTC)
    cart.touch(session, order)
    what = "city" if read.ask == "ask_city" else "township"
    text = "\n".join(([render(texts["phone_added"], phone=", ".join(added))] if added else []) + [texts[read.ask]])
    session.add(AuditLog(user_id=None, action=f"address.{read.ask}", details={
        "message_id": message.id, "order_id": order.id, "source": read.source}))
    label = ("✅ " if agreed else "") + ("📞 Save phone & " if added else "") + f"📍 Ask the {what}"
    return Outcome("contact", label, text, "ask_address",
                   f"Address without the {what} ({read.parts.full_text}): kept 24 h; the answer completes it.",
                   order.id, undo)


# ---------- suggest / perform / undo ----------

def _eligible(session: Session, message: Message, result: ParseResult | None, now: datetime) -> bool:
    if message.direction != "in" or result is None or not result.is_current:
        return False
    if result.method != "human" and result.confidence < NEEDS_REVIEW_BELOW and not _resolved(session, message, result) \
            and faq.for_message(session, message, result) is None:
        return False
    if session.scalar(select(exists().where(QuickAction.message_id == message.id, QuickAction.undone_at.is_(None),
                                            QuickAction.kind != "teach"))):
        return False  # already handled with a one-tap action (a teaching card alone is not an answer)
    if session.scalar(select(exists().where(Outbox.customer_id == message.customer_id,
                                            Outbox.status.in_(("queued", "sending"))))):
        return False  # a reply is waiting to go out: don't race it
    from app.learning import cards  # late import: cards uses the unknown-item helpers of this package

    if cards.waiting_for_price(session, message.id):
        return False  # a staff member added a product without a price: the owner prices it first
    if result.intent in ("ask_price", "ask_stock"):
        return True
    if now - message.received_at > CONTEXT_WINDOW:
        return False
    # cart actions only for messages newer than the customer's last one-tap action
    last = session.scalar(select(Message.received_at).join(QuickAction, QuickAction.message_id == Message.id)
                          .where(QuickAction.customer_id == message.customer_id, QuickAction.undone_at.is_(None),
                                 QuickAction.kind != "teach")
                          .order_by(Message.received_at.desc()).limit(1))
    return last is None or message.received_at > last


def _resolved(session: Session, message: Message, result: ParseResult) -> bool:
    """Low confidence only because of unknown items that are clear by now: a buy (partial
    cart: unknown items become red rows) or items the admin resolved ("we don't have it")."""
    items = _items(session, result)
    if not items or any(i.from_context or (not i.product_id and not i.unknown_text) for i in items):
        return False
    if any(u.partial for u in unknown.open_unknowns(session, message)):
        return False  # 4.1 "hawas for him": not certain, the whole message waits for an admin
    return result.intent == "buy" or (result.intent in ("ask_price", "ask_stock")
                                      and not unknown.open_unknowns(session, message))


def _with_greeting(session: Session, outcome: Outcome, customer_id: int, texts: dict[str, str], now: datetime):
    if outcome.text and outcome.kind != "greeting":
        outcome.text = compose.with_greeting(outcome.text, texts, compose.needs_greeting(session, customer_id, now))
    return outcome


def learned_used(session: Session, message: Message, result: ParseResult) -> list[int]:
    """Learned patterns this message's answer relies on: nicknames / intent phrases of the
    parse, and not_stocked patterns that answer its unknown items."""
    ids = list(result.learned_ids or [])
    return ids + [p.id for p in unknown.learned_not_stocked(session, message.id).values() if p.id not in ids]


def describe(p: LearnedPattern, session: Session) -> str:
    if p.kind == "nickname":
        product = session.get(Product, p.product_id)
        return f"“{p.text}” = {product.name if product else '?'}"
    if p.kind == "intent_phrase":
        return f"“{p.text}” = {p.intent.replace('_', ' ')}"
    return f"“{p.text}” = we don't sell it"


def suggest(session: Session, message: Message, result: ParseResult | None, texts: dict[str, str],
            now: datetime | None = None, address_override: str | None = None) -> Suggestion | None:
    """address_override: the admin's corrected address (Needs you "📍 check address")."""
    now = now or datetime.now(UTC)
    if not _eligible(session, message, result, now):
        return None
    savepoint = session.begin_nested()
    try:
        outcome = _apply(session, message, result, texts, address_override)
        if outcome is not None:
            _with_greeting(session, outcome, message.customer_id, texts, now)
            outcome.text, _ = steps.with_resume(session, outcome.kind, outcome.text, message.customer_id, texts, now)
    finally:
        savepoint.rollback()
    if outcome is None:
        return None
    waiting = patterns.not_certain(session, learned_used(session, message, result))
    if waiting:
        outcome.label = "📘 " + outcome.label
        outcome.note = ("📘 learned (waiting approval): " + ", ".join(describe(p, session) for p in waiting)
                        + ". " + outcome.note).strip()
    return Suggestion(outcome.kind, outcome.label, outcome.text, outcome.note,
                      fingerprint(outcome.kind, outcome.text), _edit_url(message, outcome), outcome.address,
                      bool(waiting))


def _edit_url(message: Message, outcome: Outcome) -> str | None:
    if outcome.kind == "price":
        return f"/chats/{message.customer_id}?{outcome.edit_query}#reply"
    return f"/chats/{message.customer_id}?tab=cart#cart"


def perform(session: Session, message: Message, expect: str, user: User | None, texts: dict[str, str],
            address: str | None = None, delay: timedelta = timedelta(seconds=UNDO_SECONDS),
            decided_at: datetime | None = None) -> QuickAction:
    """Do the action the button showed (address: the admin's edited address, if any).
    user None = auto mode (app/orders/auto.py), which passes its own random delay.
    decided_at: the time suggest() used (greeting / resume line windows), so both see the same clock.
    Raises Refused if the reply changed meanwhile."""
    auto = user is None
    user_id = None if auto else user.id
    session.execute(select(Customer.id).where(Customer.id == message.customer_id).with_for_update())
    now = datetime.now(UTC)
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    if not _eligible(session, message, result, now):
        raise Refused("Not possible any more (already handled, or a reply is waiting to go out).")
    outcome = _apply(session, message, result, texts, address_override=address)
    resumed = False
    if outcome is not None:
        _with_greeting(session, outcome, message.customer_id, texts, decided_at or now)
        outcome.text, resumed = steps.with_resume(session, outcome.kind, outcome.text, message.customer_id, texts,
                                                  decided_at or now)
    if outcome is None or fingerprint(outcome.kind, outcome.text) != expect:
        raise Refused("Not sent: the reply changed (price, cart or parse). Check and try again.")
    review = session.scalar(select(MessageReview).where(MessageReview.message_id == message.id))
    outcome.undo["review"] = review.status if review else "new"
    if resumed:  # the resume line went out: not again for 10 minutes (4.10)
        customer = session.get(Customer, message.customer_id)
        outcome.undo["resume_line_at"] = _iso(customer.resume_line_at)
        customer.resume_line_at = decided_at or now
    used = learned_used(session, message, result)
    if used:
        outcome.undo["learned"] = used  # "handled by learned patterns" counter (Learning page)
        waiting = [p.id for p in patterns.not_certain(session, used) if p.status == "pending"]
        if waiting and not auto:  # an admin accepted the 📘 suggestion unchanged
            outcome.undo["learned_confirmed"] = waiting
            outcome.undo["learned_approved"] = patterns.confirm_uses(session, waiting, user)
        outcome.undo["unknown_requests"] = _record_learned_not_stocked(session, message, user_id)
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


def _record_learned_not_stocked(session: Session, message: Message, user_id: int | None) -> list[int]:
    """Items answered by a learned not_stocked pattern count in "Wanted but not stocked"."""
    rows = []
    hits = unknown.learned_not_stocked(session, message.id)
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    items = {normalize(i.unknown_text): i for i in _items(session, result) if i.unknown_text} if hits else {}
    for norm, pattern in hits.items():
        if session.scalar(select(UnknownRequest.id).where(UnknownRequest.message_id == message.id,
                                                          UnknownRequest.normalized_text == norm)):
            continue
        item = items.get(norm)
        row = UnknownRequest(message_id=message.id, customer_id=message.customer_id,
                             text=(item.unknown_text if item else pattern.text)[:255], normalized_text=norm, size_ml=item.size_ml if item else None,
                             is_full_bottle=item.is_full_bottle if item else False, resolution="not_stocked",
                             resolved_by=user_id)
        session.add(row)
        session.flush()
        rows.append(row.id)
    return rows


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
            customer.address_parts = u["customer"].get("address_parts")
            customer.address_invalid = u["customer"].get("address_invalid", False)
        if "order" in u:
            o = u["order"]
            order.status, order.address, order.phones = o["status"], o["address"], o.get("phones", [])
            if "address_parts" in o:
                order.address_parts, order.address_invalid = o["address_parts"], o["address_invalid"]
                order.address_partial, order.address_partial_at = o["address_partial"], _dt(o["address_partial_at"])
            if "closed_at" in o:
                order.closed_at = _dt(o["closed_at"])
                if order.status != "cancelled":
                    order.cancel_note = None
            order.confirmed_at, order.payment_info_sent_at, order.list_sent_at = (
                _dt(o["confirmed_at"]), _dt(o["payment_info_sent_at"]), _dt(o["list_sent_at"]))
            if "change_wanted" in o:
                order.change_wanted, order.change_asked_at = o["change_wanted"], _dt(o.get("change_asked_at"))
            if "offer" in o:
                order.offer, order.offer_at = o["offer"], _dt(o.get("offer_at"))
        if u.get("created_order") and cart.view(session, order).empty:
            cart.cancel(session, order)
        cart.touch(session, order)
    if "resume_line_at" in u:
        session.get(Customer, action.customer_id).resume_line_at = _dt(u["resume_line_at"])
    for event_id in u.get("events") or []:  # the contact change / request / total change never happened
        event = session.get(OrderEvent, event_id)
        if event is not None:
            session.delete(event)
    if u.get("prompt"):
        prompt = session.get(ChoicePrompt, u["prompt"])
        if prompt is not None:
            session.delete(prompt)
    if u.get("learned_confirmed"):
        patterns.unconfirm_uses(session, u["learned_confirmed"], u.get("learned_approved") or [])
    for row_id in u.get("unknown_requests") or []:
        row = session.get(UnknownRequest, row_id)
        if row is not None:
            session.delete(row)
    if u.get("teach"):
        from app.learning import cards  # late import: cards uses this module

        cards.undo(session, u["teach"])
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
