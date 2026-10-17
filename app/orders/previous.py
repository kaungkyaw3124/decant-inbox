""""The previous one" (docs/SPEC-v4.md 4.3): "ဟိုနေ့ကဟာ ထပ်ယူမယ်" without guessing.

Candidates (product + size, no duplicates, newest first): the items of the customer's last
PAID order, their current / last cart, and products they asked about (with a size) in the
last 30 days.
  1 candidate   -> added like a buy, the list says "{product} {size} (အရင်ယူထားတဲ့ဟာ) ..."
  2-5           -> numbered list ("choose_previous") + a choice_prompts row; the customer's next
                   message "1", "၁", "1 နဲ့ 2", "အကုန်" (within 24 h) picks; anything else is
                   parsed normally
  0             -> Needs you (teaching card)
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChoicePrompt, Message, Order, OrderItem, ParseItem, ParseResult, Product
from app.models.orders import OPEN_STATUSES, PAID_STATUSES
from app.parser.normalize import normalize
from app.parser.rules import ParsedItem, ParseOutcome, parse_choice
from app.pricing.prices import size_label

ASKED_WINDOW = timedelta(days=30)
PROMPT_TTL = timedelta(hours=24)
MAX_OPTIONS = 5
ASK_INTENTS = ("buy", "ask_price", "ask_stock")


@dataclass(frozen=True)
class Candidate:
    product_id: int
    size_ml: int | None
    is_full_bottle: bool
    at: datetime

    @property
    def key(self) -> tuple:
        return self.product_id, None if self.is_full_bottle else self.size_ml, self.is_full_bottle

    def as_option(self) -> dict:
        return {"product_id": self.product_id, "size_ml": self.size_ml, "is_full_bottle": self.is_full_bottle}


def candidates(session: Session, message: Message) -> list[Candidate]:
    """The customer's earlier items, newest first, at most MAX_OPTIONS + 1 (more = too many)."""
    found: list[Candidate] = []
    before = message.received_at
    paid = session.scalar(select(Order).where(Order.customer_id == message.customer_id,
                                              Order.status.in_(PAID_STATUSES), Order.paid_at < before)
                          .order_by(Order.paid_at.desc()).limit(1))
    cart = session.scalar(select(Order).where(Order.customer_id == message.customer_id,
                                              Order.status.in_(OPEN_STATUSES + ("abandoned",)),
                                              Order.created_at < before)
                          .order_by(Order.created_at.desc()).limit(1))
    for order in (paid, cart):
        if order is None:
            continue
        for item in session.scalars(select(OrderItem).where(OrderItem.order_id == order.id,
                                                            OrderItem.removed_at.is_(None),
                                                            OrderItem.product_id.is_not(None))):
            found.append(Candidate(item.product_id, item.size_ml, item.is_full_bottle,
                                   order.paid_at if order is paid else item.created_at))
    for item, received in session.execute(
            select(ParseItem, Message.received_at).join(ParseResult, ParseResult.id == ParseItem.parse_result_id)
            .join(Message, Message.id == ParseResult.message_id)
            .where(Message.customer_id == message.customer_id, Message.direction == "in", Message.id != message.id,
                   Message.received_at < before, Message.received_at >= before - ASKED_WINDOW,
                   ParseResult.is_current, ParseResult.intent.in_(ASK_INTENTS), ParseItem.product_id.is_not(None),
                   ParseItem.from_context.is_(False))):
        if item.size_ml or item.is_full_bottle:
            found.append(Candidate(item.product_id, item.size_ml, item.is_full_bottle, received))
    newest: dict[tuple, Candidate] = {}
    for c in sorted(found, key=lambda c: c.at, reverse=True):
        newest.setdefault(c.key, c)
    active = set(session.scalars(select(Product.id).where(Product.active)))
    return [c for c in newest.values() if c.product_id in active][:MAX_OPTIONS + 1]


def label(session: Session, option: dict) -> str:
    product = session.get(Product, option["product_id"])
    size = size_label(None if option["is_full_bottle"] else option["size_ml"], product.full_size_ml)
    return f"{product.name} {size}"


def open_prompt(session: Session, message: Message) -> ChoicePrompt | None:
    """The numbered list this message may answer (sent before it, not expired, not answered by
    another message)."""
    prompt = session.scalar(select(ChoicePrompt).where(
        ChoicePrompt.customer_id == message.customer_id, ChoicePrompt.created_at < message.received_at,
        ChoicePrompt.expires_at > message.received_at).order_by(ChoicePrompt.id.desc()).limit(1))
    if prompt is None or prompt.answered_message_id not in (None, message.id):
        return None
    return prompt


def _named(session: Session, prompt: ChoicePrompt, normalized: str) -> list[int] | None:
    """docs/SPEC-v4.11-ai-first.md L3: the answer names exactly one option ("libre ပါ")."""
    from app.models import ProductAlias  # late import

    ids = [o["product_id"] for o in prompt.options]
    names: dict[int, set[str]] = {pid: set() for pid in ids}
    for pid, name in session.execute(select(Product.id, Product.name).where(Product.id.in_(ids))):
        names[pid].add(normalize(name))
    for pid, alias in session.execute(select(ProductAlias.product_id, ProductAlias.normalized_alias)
                                      .where(ProductAlias.product_id.in_(ids))):
        names[pid].add(alias)
    text = f" {normalized} "
    hits = [n for n, pid in enumerate(ids, 1)
            if any(f" {w} " in text for w in names[pid] if w and not any(
                w in other for q, others in names.items() if q != pid for other in others))]
    return hits if len(hits) == 1 else None


def as_choice(session: Session, message: Message, normalized: str) -> ParseOutcome | None:
    """"1" / "1 နဲ့ 2" / "အကုန်" answering an open numbered list -> a buy of those items. A product
    choice (docs/SPEC-v4.11-ai-first.md L3) continues its own action with the message's other items."""
    if message.direction != "in":
        return None
    prompt = open_prompt(session, message)
    if prompt is None:
        return None
    if prompt.kind == "product":
        return _product_choice(session, message, prompt, normalized)
    picked = parse_choice(normalized, len(prompt.options))
    if not picked:
        return None
    prompt.answered_message_id = message.id
    items = tuple(ParsedItem(o["product_id"], None if o["is_full_bottle"] else o["size_ml"], o["is_full_bottle"],
                             prompt.quantity, match="choice")
                  for o in (prompt.options[n - 1] for n in picked))
    first = items[0]
    return ParseOutcome("buy", first.product_id, first.size_ml, first.quantity, 1.0, items)


ACTION_INTENT = {"add": "buy", "ask_price": "ask_price", "remove": "remove"}


def _product_choice(session: Session, message: Message, prompt: ChoicePrompt, normalized: str) -> ParseOutcome | None:
    picked = parse_choice(normalized, len(prompt.options)) or _named(session, prompt, normalized)
    if not picked or len(picked) != 1:
        return None
    prompt.answered_message_id = message.id
    o = prompt.options[picked[0] - 1]
    chosen = [(o["product_id"], None if o["is_full_bottle"] else o["size_ml"], o["is_full_bottle"], prompt.quantity,
               prompt.action)]
    rest = [(p["product_id"], p["size_ml"], p["is_full_bottle"], p.get("quantity", 1), p.get("action"))
            for p in prompt.pending or []]
    actions = {a for *_, a in chosen + rest}
    mixed = len(actions) > 1
    items = tuple(ParsedItem(pid, size, full, qty, match="choice", action=action if mixed else None)
                  for pid, size, full, qty, action in chosen + rest)
    intent = "modify_cart" if mixed else ACTION_INTENT.get(prompt.action, "buy")
    first = items[0]
    return ParseOutcome(intent, first.product_id, first.size_ml, first.quantity, 1.0, items)
