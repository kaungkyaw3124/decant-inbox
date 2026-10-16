"""Teaching cards (docs/SPEC-v4.md 4.2): a message the app can't handle becomes 1-3 simple
questions (Burmese first, the most likely answer first). The admin's answers

1. finish THIS customer's request: a human parse result (method=human), then the normal
   one-tap code continues (cart / reply, sent with the usual 10 s Undo), and
2. teach the app for next time: learned_patterns rows (pending, taught_by).

Questions:
  product  an unknown / partial / fuzzy / guessed name: "“{words}” ဆိုတာ ဘယ်ပစ္စည်းလဲ?"
           -> a product, 🔍 any product, ➕ new product, 🚫 we don't sell it
  intent   product known but intent other/unknown, or nothing understood: "ဖောက်သည်က ဘာလုပ်ချင်တာလဲ?"
  size     a buy without a size: the sizes sold + full bottle
Undo (the action's Undo button) also removes the patterns and resolutions the card created
and puts the old parse back.
"""
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session

from app.learning import patterns
from app.models import (
    AICall, AuditLog, Customer, Message, MessageReview, ParseItem, ParseResult, Product, ProductAlias, ProductPrice,
    QuickAction, UnknownRequest, User,
)
from app.orders import previous, unknown
from app.parser.normalize import normalize
from app.parser.rules import PRODUCT_INTENTS, find_phones
from app.pricing.prices import current_prices, size_label
from app.replies import faq

MAX_QUESTIONS = 3
MAX_OPTIONS = 3
ASK_PRODUCT_MATCHES = ("fuzzy", "context", "ambiguous", "multiple")
# Q-intent answers: value, Burmese label (English in brackets for the owner)
INTENT_CHOICES = (
    ("buy", "ဝယ်မယ်"),
    ("ask_price", "ဈေးမေးတာ"),
    ("ask_stock", "ရှိလားမေးတာ"),
    ("remove", "ဖြုတ်မယ်"),
    ("cancel_order", "အော်ဒါ ပယ်ဖျက်"),
    ("ask_delivery", "ပစ္စည်းရောက်ပြီလားမေး"),
    ("previous_item", "အရင်ကဟာ ပြန်ယူမယ်"),
    ("change_info", "လိပ်စာ / ဖုန်း ပြောင်းချင်"),
    ("greeting", "နှုတ်ဆက်တာ"),
    ("question", "မေးခွန်း — ကိုယ်တိုင်ဖြေမယ်"),
    ("ignore", "ဘာမှမလုပ်နဲ့"),
)
INTENT_VALUES = tuple(v for v, _ in INTENT_CHOICES)
COMMON_SIZES = (2, 5, 10)


class CardError(Exception):
    """The answers can't be used (shown to the admin)."""


@dataclass
class ProductQuestion:
    position: int
    words: str  # what the customer wrote
    size_ml: int | None
    is_full_bottle: bool
    kind: str  # unknown | partial | fuzzy | context | ambiguous | multiple | none
    options: list[Product]  # most likely first
    nickname: str  # proposed text to learn ("" = nothing)


@dataclass
class SizeQuestion:
    position: int
    label: str  # the product, as far as known
    sizes: list[int | None]  # None = full bottle


@dataclass
class Card:
    message: Message
    result: ParseResult
    products: list[ProductQuestion] = field(default_factory=list)
    ask_intent: bool = False
    sizes: list[SizeQuestion] = field(default_factory=list)
    phrase: str = ""  # proposed intent phrase
    ai: object | None = None  # app.ai.hints.Hint: the AI's answers, pre-selected (docs/SPEC-v4.6-ai.md S3)

    @property
    def count(self) -> int:
        return len(self.products) + int(self.ask_intent) + len(self.sizes)


def _items(session: Session, result: ParseResult) -> list[ParseItem]:
    return list(session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)
                                .order_by(ParseItem.position)))


def handled(session: Session, message: Message) -> bool:
    """Answered with a one-tap action / card, or marked done / ignored."""
    acted = session.scalar(select(exists().where(QuickAction.message_id == message.id, QuickAction.undone_at.is_(None))))
    review = session.scalar(select(MessageReview.status).where(MessageReview.message_id == message.id))
    return bool(acted) or review in ("done", "ignored")


def propose_phrase(session: Session, text: str, names: list[str]) -> str:
    """The message minus product names, sizes, numbers, phones and punctuation."""
    out = text or ""
    for phone in find_phones(out):
        out = out.replace(phone, " ")
    vocabulary = [n for n in names if n] + [a for a, in session.execute(select(ProductAlias.normalized_alias))]
    for name in sorted(set(vocabulary), key=len, reverse=True):
        out = re.sub(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", " ", out)
    out = re.sub(r"\d+\s*(?:mls?|ခု|ဗူး)?|[^\w\s\u1000-\u109f]|[_၊။]", " ", out)  # keep Burmese marks
    return " ".join(out.split())[:120]


def _options(session: Session, words: str, first: int | None) -> list[Product]:
    return unknown.suggestions(session, words or "", MAX_OPTIONS, first=first)


def sizes_for(session: Session, product_id: int | None) -> list[int | None]:
    if product_id is None:
        return [*COMMON_SIZES, None]
    sold = [p.size_ml for p in current_prices(session, [product_id]).get(product_id, [])]
    return sold or [*COMMON_SIZES, None]


def build(session: Session, message: Message) -> Card | None:
    """The questions for this message, or None if nothing needs asking."""
    if message.direction != "in" or message.kind != "text" or handled(session, message):
        return None
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    if result is None or result.method == "human" or result.intent in ("greeting", "address", "confirm", "done"):
        return None
    card = Card(message, result)
    items = _items(session, result)
    open_texts = {u.position for u in unknown.open_unknowns(session, message)}
    for item in items:
        words = item.name_text or item.unknown_text or ""
        kind = None
        first = None
        if item.unknown_text and item.position in open_texts:
            kind, first = ("partial", item.candidate_product_id) if item.candidate_product_id else ("unknown", None)
            words = item.unknown_text if kind == "partial" else words
        elif item.product_id and item.match in ASK_PRODUCT_MATCHES:
            kind, first = item.match, item.product_id
        elif item.match == "ambiguous" or (not item.product_id and not item.unknown_text
                                           and result.intent in PRODUCT_INTENTS):
            kind = "ambiguous" if item.match == "ambiguous" else "none"
        if kind is None:
            continue
        shown = words or (message.raw_text or "")[:60]
        card.products.append(ProductQuestion(item.position, shown, item.size_ml, item.is_full_bottle, kind,
                                             _options(session, shown, first), words))
    if result.intent == "previous_item" and not items and not previous.candidates(session, message):
        words = (message.raw_text or "")[:60]  # "ဟိုနေ့ကဟာ" but no history: which product?
        options = _options(session, words, None)
        card.products.append(ProductQuestion(0, words, None, False, "previous", options, ""))
        card.sizes.append(SizeQuestion(0, options[0].name if options else "",
                                       sizes_for(session, options[0].id if options else None)))
    has_product = any(i.product_id for i in items) or bool(card.products)
    no_faq = faq.for_message(session, message, result) is None
    if result.intent in ("other", "unknown") and no_faq and (has_product or not items):
        card.ask_intent = True
        names = [i.name_text or i.unknown_text or "" for i in items]
        card.phrase = propose_phrase(session, message.normalized_text, names)
    if result.intent in ("buy", "unknown", "other"):
        for item in items:
            if item.size_ml or item.is_full_bottle:
                continue
            question = next((q for q in card.products if q.position == item.position), None)
            if item.product_id is None and question is None:
                continue
            pid = item.product_id if item.product_id and question is None else (
                question.options[0].id if question and question.options else None)
            product = session.get(Product, pid) if pid else None
            card.sizes.append(SizeQuestion(item.position, product.name if product else "", sizes_for(session, pid)))
    # at most 3 questions: names first, then what they want, then sizes
    card.products = card.products[:MAX_QUESTIONS]
    card.ask_intent = card.ask_intent and len(card.products) < MAX_QUESTIONS
    card.sizes = card.sizes[:MAX_QUESTIONS - len(card.products) - int(card.ask_intent)]
    from app.ai import hints  # late import: ai -> learning

    hints.apply(session, card)
    return card if card.count else None


TEACH_WINDOW = timedelta(days=3)
MAX_TEACH = 20


def to_teach(session: Session, now: datetime | None = None) -> list[tuple[Message, Card]]:
    """"Needs you": recent messages with a teaching card, newest first."""
    now = now or datetime.now(UTC)
    acted = exists().where(QuickAction.message_id == Message.id, QuickAction.undone_at.is_(None))
    reviewed = exists().where(MessageReview.message_id == Message.id, MessageReview.status.in_(("done", "ignored")))
    unsure = exists().where(ParseItem.parse_result_id == ParseResult.id, or_(
        ParseItem.unknown_text.is_not(None), ParseItem.product_id.is_(None), ParseItem.match.in_(ASK_PRODUCT_MATCHES)))
    ai_hint = exists().where(AICall.message_id == Message.id, AICall.ok, AICall.decision == "shadow")
    rows = session.scalars(
        select(Message).join(ParseResult, and_(ParseResult.message_id == Message.id, ParseResult.is_current))
        .join(Customer, Customer.id == Message.customer_id)
        .where(Message.direction == "in", Message.kind == "text", Message.received_at >= now - TEACH_WINDOW,
               Customer.ignored.is_(False), ParseResult.method != "human", ~acted, ~reviewed,
               or_(ParseResult.intent.in_(("other", "unknown", "previous_item")), unsure, ai_hint))
        .order_by(Message.received_at.desc()).limit(MAX_TEACH * 3)).all()
    found = []
    unanswered: set[int] | None = None
    for message in rows:
        card = build(session, message)
        if card is None:
            continue
        ai_knows = card.ai is not None and card.ai.intent not in (None, "ignore")
        if not card.products and not card.sizes and not ai_knows:  # only "what do they want?" ("ကျေးဇူးပါ"):
            if unanswered is None:  # listed once nobody answered it for a while, like the safety net
                from app.orders import followups  # late import: followups imports the orders package

                unanswered = {mid for row in followups.unanswered(session, now) for mid in row.message_ids}
            if message.id not in unanswered:
                continue
        found.append((message, card))
        if len(found) >= MAX_TEACH:
            break
    return found


# ---------- answers ----------

@dataclass
class NewProduct:
    brand: str
    name: str
    price: int | None  # for the asked size (owner only)
    full_size_ml: int | None


@dataclass
class Answers:
    products: dict[int, str] = field(default_factory=dict)  # position -> product id | "new" | "not_stocked"
    new_products: dict[int, NewProduct] = field(default_factory=dict)
    intent: str | None = None
    sizes: dict[int, str] = field(default_factory=dict)  # position -> "5" | "full"
    learn: bool = True
    nicknames: dict[int, str] = field(default_factory=dict)
    phrase: str = ""
    via_ai: bool = False  # the card showed the AI's answers: patterns are "AI + <user>"
    draft: str = ""  # the (edited) AI draft answer to a question


def _int(value: str, low: int, high: int) -> int | None:
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return int(digits) if digits and low <= int(digits) <= high else None


def read_form(form) -> Answers:
    """Answers from the card form (see _card.html)."""
    a = Answers(learn=form.get("learn") == "1", phrase=str(form.get("phrase", "")).strip(),
                intent=str(form.get("intent") or "") or None, via_ai=str(form.get("ai_call") or "").isdigit(),
                draft=str(form.get("draft") or "").replace("\r\n", "\n").strip())
    for key in form.keys():
        if m := re.fullmatch(r"p(\d+)", key):
            pos = int(m.group(1))
            search = str(form.get(f"search{pos}") or "")
            a.products[pos] = search if search.isdigit() else str(form.get(key))
            a.nicknames[pos] = str(form.get(f"nick{pos}", "")).strip()
            if a.products[pos] == "new":
                a.new_products[pos] = NewProduct(str(form.get(f"brand{pos}", "")).strip(),
                                                 str(form.get(f"name{pos}", "")).strip(),
                                                 _int(form.get(f"price{pos}"), 1, 100_000_000),
                                                 _int(form.get(f"bottle{pos}"), 1, 1000))
        elif m := re.fullmatch(r"size(\d+)", key):
            a.sizes[int(m.group(1))] = str(form.get(key))
    return a


@dataclass
class Applied:
    result: ParseResult | None  # the new human parse (None for question / ignore)
    intent: str
    undo: dict  # what Undo reverses (patterns, resolutions, parse)
    learned: list[str] = field(default_factory=list)  # lines for the admin ("📘 'ysl edp' = Y EDP")
    via_ai: bool = False
    warnings: list[str] = field(default_factory=list)
    price_needed: list[Product] = field(default_factory=list)  # staff added it without a price


def _make_product(session: Session, new: NewProduct, size_ml: int | None, full: bool, user: User) -> Product:
    if not new.brand or not new.name:
        raise CardError("ပစ္စည်းအသစ်: brand နဲ့ နာမည် ထည့်ပါ။")
    if session.scalar(select(Product.id).where(Product.brand == new.brand, Product.name == new.name)):
        raise CardError(f"{new.name} ရှိပြီးသားပါ — 🔍 ရှာမယ် ကနေ ရွေးပါ။")
    owner = user.role == "owner"
    if owner and (size_ml or full) and new.price is None:
        raise CardError("ပစ္စည်းအသစ်: မေးတဲ့ size ရဲ့ ဈေး ထည့်ပါ။")
    product = Product(brand=new.brand, name=new.name, source="manual", active=True,
                      full_size_ml=new.full_size_ml if owner else None)
    session.add(product)
    session.flush()
    if owner and new.price is not None:
        session.add(ProductPrice(product_id=product.id, size_ml=None if full else size_ml, is_full_bottle=full,
                                 price_mmk=new.price, in_stock=True, effective_from=datetime.now(UTC),
                                 created_by=user.id))
    session.add(ProductAlias(product_id=product.id, alias_text=new.name, normalized_alias=normalize(new.name),
                             source="learned"))
    session.flush()
    session.add(AuditLog(user_id=user.id, action="product.add", details={
        "product_id": product.id, "from": "teaching card", "price": new.price if owner else None}))
    return product


def _resolution(session: Session, message: Message, words: str, size_ml, full: bool, resolution: str,
                product_id: int | None, user: User) -> int | None:
    norm = normalize(words)[:255]
    if not norm or session.scalar(select(UnknownRequest.id).where(UnknownRequest.message_id == message.id,
                                                                  UnknownRequest.normalized_text == norm)):
        return None
    row = UnknownRequest(message_id=message.id, customer_id=message.customer_id, text=words[:255],
                         normalized_text=norm, size_ml=size_ml, is_full_bottle=full, resolution=resolution,
                         product_id=product_id, resolved_by=user.id)
    session.add(row)
    session.flush()
    return row.id


def apply(session: Session, message: Message, answers: Answers, user: User) -> Applied:
    """Save the answers: human parse result, resolutions, learned patterns. The caller then
    runs the normal one-tap action (or rolls back for a preview)."""
    card = build(session, message)
    if card is None:
        raise CardError("ဒီစာကို ဖြေပြီးသားပါ။")
    if card.ask_intent and answers.intent not in INTENT_VALUES:
        raise CardError("ဖောက်သည်က ဘာလုပ်ချင်တာလဲ — တစ်ခု ရွေးပါ။")
    intent = answers.intent if card.ask_intent else card.result.intent
    undo: dict = {"patterns": [], "unknown_requests": [], "prev_result": card.result.id, "corrections": []}
    if intent in ("question", "ignore"):
        return Applied(None, intent, undo)
    for q in card.products:
        if not answers.products.get(q.position):
            raise CardError(f"“{q.words}” ဆိုတာ ဘယ်ပစ္စည်းလဲ — တစ်ခု ရွေးပါ။")
    for q in card.sizes:
        if answers.sizes.get(q.position) is None:
            raise CardError("Size ရွေးပါ။")

    if card.result.intent == "previous_item" and card.products:
        intent = "buy"  # the admin named the earlier item
    applied = Applied(None, intent, undo, via_ai=answers.via_ai)
    learned_before = list(card.result.learned_ids or [])
    items = _items(session, card.result)
    known = {i.position for i in items}
    items += [ParseItem(position=q.position, product_id=None, size_ml=None, is_full_bottle=False,
                        quantity=card.result.quantity or 1, unknown_text=None, from_context=False, match="none")
              for q in card.products if q.position not in known]  # "previous" questions have no item yet
    new_items = []
    for item in items:
        pid, unknown_text, match = item.product_id, item.unknown_text, item.match
        size, full = item.size_ml, item.is_full_bottle
        if item.position in answers.sizes:
            choice = answers.sizes[item.position]
            size, full = (None, True) if choice == "full" else (_int(choice, 1, 999), False)
            match = "human" if pid else match
        q = next((q for q in card.products if q.position == item.position), None)
        if q is not None:
            answer = answers.products[q.position]
            words = q.words
            nickname = answers.nicknames.get(q.position, q.nickname) if answers.learn else ""
            if answer == "not_stocked":
                # an AI card: the confirmed words are the customer's own ("hawas for him", not "hawas him")
                words_ai = answers.nicknames.get(q.position, "") if answers.via_ai else ""
                pid, unknown_text, match = None, words_ai or unknown_text or words, "human"
                rid = _resolution(session, message, unknown_text, size, full, "not_stocked", None, user)
                if rid:
                    undo["unknown_requests"].append(rid)
                if nickname:
                    _learn(session, applied, "not_stocked", nickname, user, message, f"“{nickname}” = မရှိဘူး")
            else:
                if answer == "new":
                    new = answers.new_products.get(q.position) or NewProduct("", "", None, None)
                    product = _make_product(session, new, size, full, user)
                    if not session.scalar(select(exists().where(ProductPrice.product_id == product.id))):
                        applied.price_needed.append(product)
                    resolution = "new_product"
                else:
                    product = session.get(Product, int(answer)) if answer.isdigit() else None
                    if product is None or not product.active:
                        raise CardError("ဒီပစ္စည်း မတွေ့ပါ။")
                    resolution = "mapped"
                pid, unknown_text, match = product.id, None, "human"
                if item.unknown_text or resolution == "new_product":  # history; new_product = "price needed"
                    rid = _resolution(session, message, item.unknown_text or words, size, full, resolution,
                                      product.id, user)
                    if rid:
                        undo["unknown_requests"].append(rid)
                if nickname:
                    _learn(session, applied, "nickname", nickname, user, message, f"“{nickname}” = {product.name}",
                           product_id=product.id)
        new_items.append(ParseItem(position=item.position, product_id=pid, size_ml=None if full else size,
                                   is_full_bottle=full, quantity=item.quantity, unknown_text=unknown_text,
                                   from_context=False if match == "human" else item.from_context, match=match,
                                   name_text=item.name_text))
    if card.ask_intent and answers.learn and answers.phrase and intent in patterns.LEARNABLE_INTENTS:
        _learn(session, applied, "intent_phrase", answers.phrase, user, message,
               f"“{answers.phrase}” = {dict(INTENT_CHOICES)[intent]}", intent=intent)

    # a learned (pending) pattern the admin did not follow counts as a correction
    wrong = []
    for p in session.scalars(select(patterns.LearnedPattern).where(
            patterns.LearnedPattern.id.in_(learned_before), patterns.LearnedPattern.status == "pending")):
        if (p.kind == "nickname" and p.product_id not in {i.product_id for i in new_items}) or \
                (p.kind == "intent_phrase" and p.intent != intent):
            wrong.append(p.id)
    if wrong:
        patterns.add_corrections(session, wrong, user, message.id)
        undo["corrections"] = wrong

    session.execute(update(ParseResult).where(ParseResult.id == card.result.id).values(is_current=False))
    session.flush()
    first = next((i for i in new_items if i.product_id), new_items[0] if new_items else None)
    result = ParseResult(message_id=message.id, intent=intent, product_id=first.product_id if first else None,
                         size_ml=first.size_ml if first else None, quantity=first.quantity if first else 1,
                         confidence=1.0, method="human", parser_version="human", is_current=True,
                         phone=card.result.phone, learned_ids=[])
    session.add(result)
    session.flush()
    for item in new_items:
        item.parse_result_id = result.id
        session.add(item)
    session.flush()
    undo["new_result"] = result.id
    applied.result = result
    session.add(AuditLog(user_id=user.id, action="learning.card", details={
        "message_id": message.id, "intent": intent, "patterns": undo["patterns"],
        "resolutions": undo["unknown_requests"]}))
    return applied


def _learn(session: Session, applied: Applied, kind: str, text: str, user: User, message: Message, line: str,
           **target) -> None:
    taught = patterns.teach(session, kind, text, user, message_id=message.id, via_ai=applied.via_ai, **target)
    if taught.status == "saved":
        applied.undo["patterns"].append(taught.pattern.id)
        applied.learned.append("📘 " + line)
    elif taught.status == "conflict":
        applied.warnings.append("⚠️ " + taught.note)


def undo(session: Session, info: dict) -> None:
    """Reverse what a card saved (called from actions.undo)."""
    patterns.remove_taught(session, info.get("patterns") or [])
    for row_id in info.get("unknown_requests") or []:
        row = session.get(UnknownRequest, row_id)
        if row is not None:
            session.delete(row)
    for p in session.scalars(select(patterns.LearnedPattern).where(
            patterns.LearnedPattern.id.in_(info.get("corrections") or []))):
        p.corrections = max(p.corrections - 1, 0)
    new, prev = info.get("new_result"), info.get("prev_result")
    if new and prev and session.scalar(select(ParseResult.is_current).where(ParseResult.id == new)):
        session.execute(update(ParseResult).where(ParseResult.id == new).values(is_current=False))
        session.flush()
        session.execute(update(ParseResult).where(ParseResult.id == prev).values(is_current=True))


# ---------- what will happen (preview line) ----------

def item_names(session: Session, result: ParseResult) -> str:
    names = []
    for item in _items(session, result):
        if item.product_id:
            product = session.get(Product, item.product_id)
            size = size_label(None if item.is_full_bottle else item.size_ml, product.full_size_ml) \
                if (item.size_ml or item.is_full_bottle) else ""
            names.append(f"{product.name} {size}".strip())
    return ", ".join(names)


def preview_line(session: Session, applied: Applied, suggestion) -> str:
    """One Burmese sentence: what pressing ✅ will do."""
    if applied.intent == "ignore":
        return "ဘာမှ မပို့ပါ — ဒီစာကို ပြီးပြီ (done) လို့ မှတ်မယ်။"
    if applied.intent == "question":
        return "Chat ကိုဖွင့်ပြီး ကိုယ်တိုင် ဖြေမယ်။"
    if applied.price_needed:
        names = ", ".join(p.name for p in applied.price_needed)
        return f"{names} ကို ထည့်ပြီး ပိုင်ရှင်ကို ဈေးမေးမယ်။ ဈေးရရင် စာရင်း အလိုအလျောက် ပို့မယ်။"
    names = item_names(session, applied.result) if applied.result else ""
    if suggestion is None:
        return "ဘာမှ အလိုအလျောက် မပို့နိုင်ပါ — Chat ထဲမှာ ကိုယ်တိုင် ဖြေပေးပါ။"
    return {
        "cart_add": f"{names} ကို ခြင်းထဲထည့်ပြီး စာရင်းပို့မယ်။",
        "price": f"{names} ဈေးနှုန်း ပို့မယ်။",
        "cart_remove": f"{names} ကို ခြင်းထဲက ဖြုတ်ပြီး စာရင်းပို့မယ်။",
        "not_stocked": "မရှိဘူးလို့ ပြန်ပြောမယ်။",
        "greeting": "နှုတ်ဆက်စာ ပြန်ပို့မယ်။",
        "delivery": "ပို့ဆောင်မှု အခြေအနေ ပြန်ပြောမယ်။",
        "cancel_order": "အော်ဒါကို ပယ်ဖျက်ပြီး ပြန်ပြောမယ်။",
        "faq": "FAQ အဖြေ ပို့မယ်။",
        "cart_list": "ခြင်းထဲက စာရင်း ပို့မယ်။",
    }.get(suggestion.kind, suggestion.label)


# ---------- price needed (a staff member added a product without a price) ----------

def price_needed(session: Session) -> list[tuple[UnknownRequest, Product, Message]]:
    """Products added from a card without a price, with the message waiting for them."""
    has_price = exists().where(ProductPrice.product_id == Product.id, ProductPrice.price_mmk.is_not(None))
    answered = exists().where(QuickAction.message_id == UnknownRequest.message_id, QuickAction.undone_at.is_(None),
                              QuickAction.kind != "teach")
    return session.execute(
        select(UnknownRequest, Product, Message).join(Product, Product.id == UnknownRequest.product_id)
        .join(Message, Message.id == UnknownRequest.message_id)
        .where(UnknownRequest.resolution == "new_product", Product.active, ~has_price, ~answered)
        .order_by(UnknownRequest.id)).all()


def waiting_for_price(session: Session, message_id: int) -> bool:
    """The message names a product added from a card that has no price yet (it waits)."""
    has_price = exists().where(ProductPrice.product_id == UnknownRequest.product_id,
                               ProductPrice.price_mmk.is_not(None))
    return bool(session.scalar(select(exists().where(
        UnknownRequest.message_id == message_id, UnknownRequest.resolution == "new_product", ~has_price))))
