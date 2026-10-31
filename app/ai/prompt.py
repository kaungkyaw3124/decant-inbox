"""The request: a STATIC part first (instructions + product list + FAQ titles, identical for
every message so the provider's prompt cache applies), then the DYNAMIC part (the message,
the last 10 messages of the chat, the cart, the last paid order). Everything that comes from
a chat goes through privacy.mask(); customer names, photos and payment details never go out."""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.privacy import mask
from app.ai.types import ACTIONS, INTENTS, LEARN_KINDS
from app.models import FaqEntry, LearnedPattern, Message, Order, OrderItem, Outbox, Product, ProductAlias
from app.models.orders import OPEN_STATUSES, PAID_STATUSES
from app.pricing.prices import current_prices

HISTORY = 10
HISTORY_CHARS = 300
MESSAGE_CHARS = 1500
PRIVATE_REPLY_KINDS = ("payment_info", "payment", "contact", "ask_address", "ask_phone")


@dataclass(frozen=True)
class CatalogProduct:
    id: int
    brand: str
    name: str
    nicknames: tuple[str, ...]
    sizes: tuple[str, ...]  # "2ml", "5ml", "10ml", "full"
    in_stock: bool
    full_size_ml: int | None = None


@dataclass(frozen=True)
class Catalog:
    products: tuple[CatalogProduct, ...]
    not_sold: tuple[str, ...]  # approved "we don't sell" words
    faq_titles: tuple[str, ...]

    def by_id(self) -> dict[int, CatalogProduct]:
        return {p.id: p for p in self.products}

    @property
    def all_sizes(self) -> list[str]:
        sizes = {s for p in self.products for s in p.sizes} | {"2ml", "5ml", "10ml", "full"}
        return sorted(sizes, key=lambda s: (s == "full", int(s[:-2]) if s != "full" else 0))


def size_key(size_ml: int | None, is_full: bool) -> str | None:
    if is_full:
        return "full"
    return f"{size_ml}ml" if size_ml else None


def load_catalog(session: Session) -> Catalog:
    products = session.scalars(select(Product).where(Product.active).order_by(Product.id)).all()
    prices = current_prices(session, [p.id for p in products])
    names: dict[int, list[str]] = {}
    for pid, text in session.execute(select(ProductAlias.product_id, ProductAlias.alias_text)
                                     .order_by(ProductAlias.id)):
        names.setdefault(pid, []).append(text)
    for pid, text in session.execute(select(LearnedPattern.product_id, LearnedPattern.text).where(
            LearnedPattern.kind == "nickname", LearnedPattern.status == "approved").order_by(LearnedPattern.id)):
        names.setdefault(pid, []).append(text)
    out = []
    for p in products:
        sold = prices.get(p.id, [])
        sizes = tuple(dict.fromkeys(size_key(x.size_ml, x.size_ml is None) for x in sold))
        nicknames = tuple(dict.fromkeys(n.strip().lower() for n in names.get(p.id, []) if n.strip()))
        out.append(CatalogProduct(p.id, p.brand, p.name, nicknames, sizes, any(x.in_stock for x in sold),
                                   p.full_size_ml))
    not_sold = tuple(session.scalars(select(LearnedPattern.text).where(
        LearnedPattern.kind == "not_stocked", LearnedPattern.status == "approved").order_by(LearnedPattern.id)))
    faq = tuple(session.scalars(select(FaqEntry.title).where(FaqEntry.active).order_by(FaqEntry.sort_order)))
    return Catalog(tuple(out), not_sold, faq)


INSTRUCTIONS = """\
You help a small perfume DECANT shop in Myanmar read customer messages from Telegram. Messages
mix Burmese and English, have typos, missing spaces and wrong spellings. You ONLY understand the
message and answer with JSON. You never talk to the customer. Our own code writes every reply.

Answer for the CUSTOMER MESSAGE only. The recent chat, the cart and the last paid order are
context to understand it (e.g. "that one", "the previous one", "10ml too").

## intent (exactly one)
- buy: wants to order / add to cart (ဝယ်မယ်, ယူမယ်, ယူပါမယ်, ရောယူမယ်, မှာမယ်, ထည့်ပေး, ပေးပါ with a product, order, want).
- ask_price: asks the price (ဈေး, ဘယ်လောက်, price, how much). A price question with a product is ask_price, not buy.
- ask_stock: asks if we have it (ရှိလား, ရလား about a perfume or size, available, in stock).
- remove: no longer wants a NAMED item that is in the cart (မယူတော့ဘူး, ဖြုတ်ပေး, cancel + product).
- modify_cart: ONE message that both removes an item from the cart AND adds or asks about another one
  ("Y edp မယူတော့ဘူး liquid brun 10ml ယူပါမယ်"). Every item then needs its action.
- cancel_order: cancels the whole order, no product named.
- confirm: agrees to the list / order (ok, ဟုတ်ကဲ့, အဆင်ပြေတယ်).
- done: says that is all (ဒါပဲ, ဒါပါပဲ).
- payment_sent: says they paid / transferred the money (ငွေလွှဲပြီးပါပြီ, paid) without a screenshot.
- address: sends a delivery address and/or phone ([PHONE], [ADDRESS] or a township name). The word for
  "address" alone (လိပ်စာ, address, ပို့ပေးပါ) is NOT an address.
- change_info: wants to CHANGE the delivery address or phone (လိပ်စာ ပြောင်းချင်, လိပ်စာအသစ်, ဖုန်းအသစ်,
  change address), or answers "no" to "send to this phone / address?". If the new address / phone is
  in the same message, still change_info.
- ask_delivery: asks when the parcel arrives / whether it was sent.
- order_start: wants to order but names NO product and no size (မှာချင်လို့ပါ, ဝယ်ချင်လို့, order တင်ချင်,
  အော်ဒါတင်ချင်, "want to order", "can I order"), with or without hi. items = [].
- greeting: only a greeting (hi, မင်္ဂလာပါ) or a greeting with a very general "what do you have".
- previous_item: wants the same item(s) as before (ဟိုနေ့ကဟာ, အရင်ကဟာ, same as last time). Fill items from
  the LAST PAID ORDER or the CART in the context (product_id and size from there; qty from the message).
  If nothing in the context fits, items = [].
- question: any other question a person must answer: how a perfume smells, lasts, which occasion or
  season, original or not, recommendations, shop questions (delivery fee, location, payment).
- other: thanks, stickers, chit-chat, anything else.

## items (one per product + size the message names; [] if none)
- product_id: ONLY an id from the PRODUCT LIST. Match by brand, name, nicknames, Burmese spelling or an
  obvious typo of THE SAME perfume ("stonger with u intense" = Stronger With You Intensely,
  "savage" = Sauvage, "ysl edp" = Y Eau de Parfum, "ဘလူးဒီချန်နယ်" = Bleu de Chanel).
- A WRONG PRODUCT IS MUCH WORSE THAN NULL. Different versions are different perfumes: "for him",
  "intense", "elixir", "absolu", "parfum", "noir", "sport", "night", other flankers or a different
  brand are NOT the listed product unless that exact version is in the list. If the perfume is not in
  the list: product_id = null and not_in_list = the customer's words for it (e.g. "hawas for him",
  "liquid brun"). If you cannot tell which listed product they mean: product_id = null and
  unclear_text = their words. Never set both product_id and not_in_list.
- A BRAND NAME ALONE ("ysl", "dior", "armani", "jpg", "chanel") is NOT a product when the list has more
  than one product of that brand: product_id = null, unclear_text = their words, and candidates = those
  products when there are 2 or 3 of them (the shop then asks the customer to choose, so your confidence is
  how sure you are that it is ONE OF THE CANDIDATES, usually high). More than 3: candidates = [] and
  confidence < 0.6. Use the brand as a product only when the recent chat or the cart shows which one is
  meant (e.g. "ysl" with only Y Eau de Parfum in the cart). Never pick the most popular one.
- A product named in an EARLIER message (recent chat / cart) may be meant by "it", "this one",
  "10ml too" or a size alone: use it only when that is clear.
- size: "2ml", "5ml", "10ml" ... or "full" for a full bottle (အပြည့်, ဗူးလိုက်, full bottle, full size, or the
  bottle size itself). null when no size is said. Never guess a size.
- The delivery ADDRESS and PHONE are never items: street numbers, "str", "st", "street", "လမ်း", "x", house
  numbers and phone digits ("66 str 28 str", "no 12", "၆၆ လမ်း", "73x45", "09…") give no product, size or qty.
- qty: number of pieces (၂ခု / 2 ခု / x2 / 2 pcs = 2). Default 1. "5ml" is a size, not a quantity.
- For remove: the item(s) from the cart that the customer no longer wants (size from the cart if not said).
  Only products that are in the CART NOW can be removed.
- action: what to do with THIS item: "add" (buy / add to the cart), "remove" (take it out of the cart) or
  "ask_price" (price / stock question). Required for modify_cart; for other intents it may be null.
- candidates: when the words clearly mean ONE of 2-3 listed products but you cannot tell which (a brand
  name alone, "ysl 10ml" = Y Eau de Parfum or Libre): product_id = null, unclear_text = their words,
  candidates = those 2-3 product ids (most likely first). Otherwise [].

## learn (0-3 entries; words worth remembering so the shop's rules understand them next time)
- nickname: the customer's words for a LISTED product that are not already one of its nicknames,
  e.g. "ysl edp" -> Y Eau de Parfum. product_id required.
- not_stocked: the customer's words for a perfume that is NOT in the list (same text as not_in_list).
- intent_phrase: a short phrase that clearly says what they want and that ordinary keywords may miss,
  e.g. "လေးထည့်ထားပေး" -> buy. intent required (buy, ask_price, ask_stock, remove, cancel_order,
  ask_delivery, greeting, previous_item, change_info).
- text must be copied EXACTLY from the customer message (same spelling). No sizes, numbers or
  [PHONE]/[ADDRESS]. Leave learn empty when nothing is new.
- Only SHORT reusable words: a product name or nickname, or an intent phrase of at most 4 words. Never
  the whole message or a whole sentence, never particles alone (နော်, ဗျ, ရှင့်, ပါ).

## confidence, reason, draft_answer
- confidence 0-1: how sure you are that intent AND every item are right (for an item with candidates: that
  it is one of them). Use < 0.6 when guessing.
- reason: short English, max 20 words, e.g. "ysl edp = Y EDP; 10ml; ယူပါမယ် = buy".
- draft_answer: only for intent "question": a short, polite Burmese answer from the shop (ending
  with ရှင့် / နော်) that a staff member will check before sending. No prices, no stock or delivery
  promises, no invented facts. If you do not know, null. For every other intent: null.
"""

# docs/SPEC-v4.12-address-payment-ai.md N1 (only when the owner allows addresses to be sent: ai_address)
ADDRESS_INSTRUCTIONS = """
## address (a delivery address, or part of one, in the CUSTOMER MESSAGE; else null)
- Fill it when the message gives WHERE to deliver: house / building number, street, ward (ရပ်ကွက်), township
  (မြို့နယ်), city, landmark. Also when it is only a part, e.g. a street and number without the township,
  or only a township answering our question "which township?" (see WE ASKED). Words that only SAY
  "address" / "send here" / "change the address" (လိပ်စာ, ပို့ပေးပါ, ဒီကိုပို့ပေးပါ, လိပ်စာ ပြောင်းချင်ပါတယ်,
  new address) are NOT an address: address = null and, for a change request, intent change_info.
- full_text: ONLY the address, copied from the message as written (same spelling, same digits - Burmese
  digits stay Burmese), in the customer's order. Leave out [PHONE], ဖုန်း / phone words, ကိုပို့ပေးပါ,
  ဒီလိပ်စာကို, "new address:", greetings, product names and everything else that is not the address.
- house_no, street, ward_or_quarter, township, city, landmark: the parts as written (null if not given).
  township: the township NAME only (e.g. "ဗဟန်း", "Yankin"), without မြို့နယ် / township. Do not guess a
  township that is not written; a well-known ward or street does not tell the township.
- missing: what a delivery still needs: "township" when there is no township, "city" when there is
  neither a township nor a city (outside Yangon a town name is the city), "street" / "house_no" when not
  given. [] when complete.
- Mandalay (and other towns) use NUMBERED streets instead of a township: "73 x 45", "73x45", "၇၃ လမ်း x ၄၅ လမ်း",
  "73, 45 လမ်း", "၇၃ လမ်း (၄၅ x ၄၆ ကြား)", "between 73 & 74", "၇၃ နဲ့ ၇၄ ကြား". street = those numbers as written;
  city = Mandalay (or the town). City + such a street is a complete address: missing = [] (no township needed).
- is_change_request: true when the customer says this REPLACES the address we have (new / changed /
  "send it here instead").
- confidence 0-1: how sure you are that full_text is exactly the address and the parts are right.
"""

ADDRESS_PARTS = ("house_no", "street", "ward_or_quarter", "township", "city", "landmark", "full_text")


def static_part(catalog: Catalog, with_address: bool = False) -> str:
    lines = [INSTRUCTIONS + (ADDRESS_INSTRUCTIONS if with_address else ""),
             "## PRODUCT LIST (id | brand | name | nicknames | sizes sold)"]
    for p in catalog.products:
        stock = "" if p.in_stock else " | out of stock now"
        sizes = [f"full ({p.full_size_ml}ml bottle)" if s == "full" and p.full_size_ml else s for s in p.sizes]
        lines.append(f"{p.id} | {p.brand} | {p.name} | {', '.join(p.nicknames) or '-'} | "
                     f"{', '.join(sizes) or 'no price yet'}{stock}")
    if catalog.not_sold:
        lines += ["", "## WE DO NOT SELL (not_in_list): " + "; ".join(catalog.not_sold)]
    if catalog.faq_titles:
        lines += ["", "## SHOP FAQ TOPICS (the shop has ready answers): " + "; ".join(catalog.faq_titles)]
    return "\n".join(lines)


def address_schema() -> dict:
    return {"anyOf": [{"type": "null"}, {
        "type": "object", "additionalProperties": False,
        "required": [*ADDRESS_PARTS, "missing", "is_change_request", "confidence"],
        "properties": {**{k: {"type": ["string", "null"]} for k in ADDRESS_PARTS},
                       "missing": {"type": "array", "items": {"type": "string",
                                                              "enum": ["township", "city", "street", "house_no"]}},
                       "is_change_request": {"type": "boolean"}, "confidence": {"type": "number"}}}]}


def schema(catalog: Catalog, with_address: bool = False) -> dict:
    """Strict JSON schema: every field required, null where allowed; product ids and sizes are
    enums, so the model cannot even write an unknown id. with_address: the 4.12 "address" answer."""
    ids = [p.id for p in catalog.products]
    out = _schema(catalog, ids)
    if with_address:
        out["required"].append("address")
        out["properties"]["address"] = address_schema()
    return out


def _schema(catalog: Catalog, ids: list[int]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "items", "learn", "confidence", "reason", "draft_answer"],
        "properties": {
            "intent": {"type": "string", "enum": list(INTENTS)},
            "items": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["product_id", "size", "qty", "not_in_list", "unclear_text", "action", "candidates"],
                "properties": {
                    "product_id": {"type": ["integer", "null"], "enum": [*ids, None]},
                    "size": {"type": ["string", "null"], "enum": [*catalog.all_sizes, None]},
                    "qty": {"type": "integer"},
                    "not_in_list": {"type": ["string", "null"]},
                    "unclear_text": {"type": ["string", "null"]},
                    "action": {"type": ["string", "null"], "enum": [*ACTIONS, None]},
                    "candidates": {"type": "array", "items": {"type": "integer", "enum": ids}},
                }}},
            "learn": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["text", "kind", "product_id", "intent"],
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": list(LEARN_KINDS)},
                    "product_id": {"type": ["integer", "null"], "enum": [*ids, None]},
                    "intent": {"type": ["string", "null"], "enum": [*INTENTS, None]},
                }}},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "draft_answer": {"type": ["string", "null"]},
        },
    }


@dataclass(frozen=True)
class Context:
    """The dynamic part, already masked."""
    message: str
    history: tuple[str, ...]  # "C: ..." / "S: ..."
    cart: tuple[str, ...]  # "Sauvage Eau de Parfum 5ml x1"
    last_paid: tuple[str, ...]
    with_address: bool = False  # docs/SPEC-v4.12: addresses as written + the "address" answer
    asked: str | None = None  # what we asked the customer for: "address" | "township" | "city" | None
    partial_address: str | None = None  # the address part we have (waiting for the township / city)


def _item_line(names: dict[int, str], item: OrderItem) -> str:
    name = names.get(item.product_id) or (item.unknown_text or "?")
    size = "full" if item.is_full_bottle else (f"{item.size_ml}ml" if item.size_ml else "")
    return f"{name} {size} x{item.quantity or 1}".replace("  ", " ")


def build_context(session: Session, message: Message, with_address: bool = False) -> Context:
    rows = session.scalars(select(Message).where(
        Message.customer_id == message.customer_id, Message.id != message.id,
        Message.received_at <= message.received_at, Message.received_at >= message.received_at - timedelta(days=7))
        .order_by(Message.received_at.desc(), Message.id.desc()).limit(HISTORY)).all()
    private = set(session.scalars(select(Outbox.sent_message_id).where(
        Outbox.sent_message_id.in_([m.id for m in rows]), Outbox.reply_kind.in_(PRIVATE_REPLY_KINDS))))
    history = []
    for m in reversed(rows):
        who = "C" if m.direction == "in" else "S"
        if m.kind != "text":
            body = "[photo]"
        elif m.id in private:
            body = "[contact / payment details]"
        else:
            body = mask(m.raw_text, with_address)[:HISTORY_CHARS]
        history.append(f"{who}: {body}")
    names = dict(session.execute(select(Product.id, Product.name)).all())
    cart = session.scalar(select(Order).where(Order.customer_id == message.customer_id,
                                              Order.status.in_(OPEN_STATUSES)))
    paid = session.scalar(select(Order).where(Order.customer_id == message.customer_id,
                                              Order.status.in_(PAID_STATUSES), Order.paid_at < message.received_at)
                          .order_by(Order.paid_at.desc()).limit(1))

    def lines(order: Order | None) -> tuple[str, ...]:
        if order is None:
            return ()
        return tuple(_item_line(names, i) for i in session.scalars(select(OrderItem).where(
            OrderItem.order_id == order.id, OrderItem.removed_at.is_(None)).order_by(OrderItem.id)))

    asked = partial = None
    if with_address:
        from app.orders import address  # late import: orders -> parser -> ai

        asked, partial = address.asked_for(session, message.customer_id, cart, message.received_at)
    return Context(mask(message.raw_text, with_address)[:MESSAGE_CHARS], tuple(history), lines(cart), lines(paid),
                   with_address, asked, mask(partial, True) if partial else None)


def dynamic_part(ctx: Context) -> str:
    return "\n".join([
        "RECENT CHAT (oldest first; C = customer, S = shop):",
        *(ctx.history or ("(none)",)),
        "",
        "CART NOW: " + ("; ".join(ctx.cart) if ctx.cart else "(empty)"),
        "LAST PAID ORDER: " + ("; ".join(ctx.last_paid) if ctx.last_paid else "(none)"),
        *(["WE ASKED: " + {"address": "the delivery address", "township": "the township of this address: ",
                           "city": "the city of this address: "}[ctx.asked] + (ctx.partial_address or "")]
          if ctx.with_address and ctx.asked else []),
        "",
        "CUSTOMER MESSAGE:",
        "<<<",
        ctx.message,
        ">>>",
    ])
