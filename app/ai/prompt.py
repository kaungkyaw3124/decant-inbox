"""The request: a STATIC part first (instructions + product list + FAQ titles, identical for
every message so the provider's prompt cache applies), then the DYNAMIC part (the message,
the last 10 messages of the chat, the cart, the last paid order). Everything that comes from
a chat goes through privacy.mask(); customer names, photos and payment details never go out."""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.privacy import mask
from app.ai.types import INTENTS, LEARN_KINDS
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
  than one product of that brand: product_id = null, unclear_text = their words, confidence < 0.6. Use
  the brand only when the recent chat or the cart shows which of them is meant (e.g. "ysl" with only
  Y Eau de Parfum in the cart). Never pick the most popular one.
- A product named in an EARLIER message (recent chat / cart) may be meant by "it", "this one",
  "10ml too" or a size alone: use it only when that is clear.
- size: "2ml", "5ml", "10ml" ... or "full" for a full bottle (အပြည့်, ဗူးလိုက်, full bottle, full size, or the
  bottle size itself). null when no size is said. Never guess a size.
- qty: number of pieces (၂ခု / 2 ခု / x2 / 2 pcs = 2). Default 1. "5ml" is a size, not a quantity.
- For remove: the item(s) from the cart that the customer no longer wants (size from the cart if not said).

## learn (0-3 entries; words worth remembering so the shop's rules understand them next time)
- nickname: the customer's words for a LISTED product that are not already one of its nicknames,
  e.g. "ysl edp" -> Y Eau de Parfum. product_id required.
- not_stocked: the customer's words for a perfume that is NOT in the list (same text as not_in_list).
- intent_phrase: a short phrase that clearly says what they want and that ordinary keywords may miss,
  e.g. "လေးထည့်ထားပေး" -> buy. intent required (buy, ask_price, ask_stock, remove, cancel_order,
  ask_delivery, greeting, previous_item, change_info).
- text must be copied EXACTLY from the customer message (same spelling). No sizes, numbers or
  [PHONE]/[ADDRESS]. Leave learn empty when nothing is new.

## confidence, reason, draft_answer
- confidence 0-1: how sure you are that intent AND every item are right. Use < 0.6 when guessing.
- reason: short English, max 20 words, e.g. "ysl edp = Y EDP; 10ml; ယူပါမယ် = buy".
- draft_answer: only for intent "question": a short, polite Burmese answer from the shop (ending
  with ရှင့် / နော်) that a staff member will check before sending. No prices, no stock or delivery
  promises, no invented facts. If you do not know, null. For every other intent: null.
"""


def static_part(catalog: Catalog) -> str:
    lines = [INSTRUCTIONS, "## PRODUCT LIST (id | brand | name | nicknames | sizes sold)"]
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


def schema(catalog: Catalog) -> dict:
    """Strict JSON schema: every field required, null where allowed; product ids and sizes are
    enums, so the model cannot even write an unknown id."""
    ids = [p.id for p in catalog.products]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "items", "learn", "confidence", "reason", "draft_answer"],
        "properties": {
            "intent": {"type": "string", "enum": list(INTENTS)},
            "items": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["product_id", "size", "qty", "not_in_list", "unclear_text"],
                "properties": {
                    "product_id": {"type": ["integer", "null"], "enum": [*ids, None]},
                    "size": {"type": ["string", "null"], "enum": [*catalog.all_sizes, None]},
                    "qty": {"type": "integer"},
                    "not_in_list": {"type": ["string", "null"]},
                    "unclear_text": {"type": ["string", "null"]},
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


def _item_line(names: dict[int, str], item: OrderItem) -> str:
    name = names.get(item.product_id) or (item.unknown_text or "?")
    size = "full" if item.is_full_bottle else (f"{item.size_ml}ml" if item.size_ml else "")
    return f"{name} {size} x{item.quantity or 1}".replace("  ", " ")


def build_context(session: Session, message: Message) -> Context:
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
            body = mask(m.raw_text)[:HISTORY_CHARS]
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

    return Context(mask(message.raw_text)[:MESSAGE_CHARS], tuple(history), lines(cart), lines(paid))


def dynamic_part(ctx: Context) -> str:
    return "\n".join([
        "RECENT CHAT (oldest first; C = customer, S = shop):",
        *(ctx.history or ("(none)",)),
        "",
        "CART NOW: " + ("; ".join(ctx.cart) if ctx.cart else "(empty)"),
        "LAST PAID ORDER: " + ("; ".join(ctx.last_paid) if ctx.last_paid else "(none)"),
        "",
        "CUSTOMER MESSAGE:",
        "<<<",
        ctx.message,
        ">>>",
    ])
