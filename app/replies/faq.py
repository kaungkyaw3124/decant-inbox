"""FAQ auto-answers (docs/SPEC-v3.md Step 7).

Settings > FAQ holds entries {title, keywords, answer, active}. A message gets an FAQ answer
only when it names no product and no size and is not part of the order flow (intent other /
unknown, or a price / stock / delivery question the normal flow can't answer). Several
entries match -> the one with the most keywords wins. If a product IS named, the normal
reply wins and the FAQ match is only a hint in "Needs you".
Keywords are read from the database every time, so edits work at once.
"""
import re
from dataclasses import dataclass

from sqlalchemy import String, exists, select
from sqlalchemy.orm import Session

from app.models import FaqEntry, Message, Order, ParseItem, ParseResult
from app.models.orders import OPEN_STATUSES
from app.parser.normalize import normalize

FAQ_INTENTS = ("other", "unknown", "ask_price", "ask_stock", "ask_delivery")
FIRST_INTENTS = ("other", "unknown")  # the FAQ answer comes before anything else
MAX_KEYWORDS = 30
# The seed (docs/SPEC-v3.md); also inserted by migration db0641e10ac5. Owner edits later.
SEED = (
    ("Delivery time", "ဘယ်နှစ်ရက်, ဘယ်လောက်ကြာ, delivery time, ရောက်ဖို့",
     "ရန်ကုန်မြို့တွင်း ၁-၂ ရက်၊ နယ်ကို ၃-၅ ရက်လောက် ကြာပါတယ်နော်။"),
    ("Authentic", "authentic, original, စစ်လား, အစစ်လား, tester",
     "အားလုံး authentic (original) ပစ္စည်းတွေ ကနေ ခွဲထည့်ပေးတာပါနော်။"),
    ("Payment", "ဘယ်လိုပေးရ, ငွေဘယ်လိုလွှဲ, cod, kpay ရလား",
     "KPay / AYA Pay နဲ့ ကြိုလွှဲပေးရပါတယ်။ ပို့ခကိုတော့ ပစ္စည်းရောက်မှ ပေးရပါတယ်နော်။"),
    ("Location", "ဘယ်မှာလဲ, ဆိုင်, location, လာယူ", "Online ကနေ ပို့ပေးတာပါနော်။"),
    # docs/SPEC-v4.20 A2/A6 (migration c5d8e1f2a904): the safe default until the owner writes the fee table here
    DELIVERY_FEE := ("Delivery fee", "ပို့ခ, ပို့ဆောင်ခ, deli fee, delivery fee, delivery charge, shipping fee, ship fee",
                     "ပို့ခကို admin က အတည်ပြုပေးပါမယ်နော်။ ပို့ခကိုတော့ ပစ္စည်းရောက်မှ ပေးရပါတယ်။"),
)


@dataclass(frozen=True)
class Match:
    entry: FaqEntry
    keywords: tuple[str, ...]  # the normalized keywords found in the message

    @property
    def words(self) -> set[str]:
        return {w for k in self.keywords for w in k.split()}


def split_keywords(text: str) -> list[str]:
    """"a, b ၊ c" -> normalized keywords, no duplicates."""
    found = []
    for part in re.split(r"[,၊\n]", text):
        key = normalize(part)
        if key and key not in found:
            found.append(key)
    return found


def _found(keyword: str, text: str) -> bool:
    if re.search(r"[a-z0-9]", keyword):  # Latin words must stand alone ("cod" not in "code")
        return re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", text) is not None
    # a Burmese keyword ends on a whole syllable: "ပို့ခ" (fee) is not in "ပို့ချင်" (want to send)
    return re.search(re.escape(keyword) + _MARK_AFTER, text) is not None


_MARK_AFTER = "(?![\u102b-\u103e\u1056-\u1059\u105e-\u1060\u1062-\u1064\u1067-\u106d\u1071-\u1074\u1082-\u108d\u108f\u109a-\u109d])"


def best(session: Session, normalized_text: str) -> Match | None:
    """The active entry with the most keywords in the text (ties: the first in the list)."""
    text = normalized_text or ""
    winner: Match | None = None
    for entry in session.scalars(select(FaqEntry).where(FaqEntry.active)
                                 .order_by(FaqEntry.sort_order, FaqEntry.id)):
        hits = tuple(k for k in split_keywords(entry.keywords) if _found(k, text))
        if hits and (winner is None or len(hits) > len(winner.keywords)):
            winner = Match(entry, hits)
    return winner


def _current(session: Session, message: Message) -> ParseResult | None:
    return session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))


def _items(session: Session, result: ParseResult) -> list[ParseItem]:
    return list(session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result.id)))


def _names_something(match: Match, items: list[ParseItem]) -> bool:
    """A product, a size, or words that are not part of the FAQ keywords ("kpay" in
    "kpay ရလား" is the keyword, not an unknown product)."""
    for i in items:
        if i.product_id or i.size_ml or i.is_full_bottle:
            return True
        if i.unknown_text and not set(normalize(i.unknown_text).split()) <= match.words:
            return True
    return False


def for_message(session: Session, message: Message, result: ParseResult | None = None) -> Match | None:
    """The FAQ answer this message should get, or None."""
    if message.direction != "in" or message.kind != "text":
        return None
    result = result or _current(session, message)
    if result is None or result.intent not in FAQ_INTENTS + ("address",):
        return None
    if result.intent == "address" and _order_open(session, message.customer_id):
        return None  # an address for the open order (docs/SPEC-v4.20: "delivery fee to mandalay?" without one)
    match = best(session, message.normalized_text)
    if match is None or _names_something(match, _items(session, result)):
        return None
    return match


def _order_open(session: Session, customer_id: int) -> bool:
    return bool(session.scalar(select(exists().where(Order.customer_id == customer_id,
                                                     Order.status.in_(OPEN_STATUSES)))))


def hint(session: Session, message: Message, result: ParseResult | None = None) -> Match | None:
    """An FAQ question inside a message the normal flow handles (a product is named)."""
    result = result or _current(session, message)
    if result is None or message.direction != "in":
        return None
    match = best(session, message.normalized_text)
    if match is None or for_message(session, message, result) is not None:
        return None
    return match


# ---------- hints, sending, settings ----------

HINT_WINDOW_HOURS = 24


def hints(session: Session, now) -> list[tuple]:
    """"Needs you" hints: (message, customer, match) for messages of the last 24 h whose FAQ
    question was not answered (normal flow handled the product part), until an FAQ answer
    is sent for it or the admin marks it done."""
    from datetime import timedelta

    from sqlalchemy import exists

    from app.models import AuditLog, Customer, Outbox

    answered = exists().where(Outbox.source_message_id == Message.id, Outbox.reply_kind == "faq",
                              Outbox.status != "cancelled")
    dismissed = exists().where(AuditLog.action == "faq.hint_done",
                               AuditLog.details["message_id"].astext == Message.id.cast(String))
    rows = session.execute(select(Message, Customer, ParseResult).join(Customer, Customer.id == Message.customer_id)
                           .join(ParseResult, (ParseResult.message_id == Message.id) & ParseResult.is_current)
                           .where(Message.direction == "in", Message.kind == "text", Customer.ignored.is_(False),
                                  Message.received_at >= now - timedelta(hours=HINT_WINDOW_HOURS),
                                  ~answered, ~dismissed).order_by(Message.received_at.desc())).all()
    found = []
    for message, customer, result in rows:
        match = hint(session, message, result)
        if match is not None:
            found.append((message, customer, match))
    return found


def validate(title: str, keywords: str, answer: str) -> dict:
    """Cleaned fields, or ValueError with a message for the admin."""
    title, answer = title.strip(), answer.replace("\r\n", "\n").strip()
    keys = split_keywords(keywords)
    if not title or len(title) > 64:
        raise ValueError("Title: 1-64 characters.")
    if not keys:
        raise ValueError("Add at least one keyword (comma separated).")
    if len(keys) > MAX_KEYWORDS or any(len(k) < 2 for k in keys):
        raise ValueError(f"Keywords: at most {MAX_KEYWORDS}, each at least 2 characters.")
    if not answer or len(answer) > 2000:
        raise ValueError("Answer: 1-2000 characters.")
    return {"title": title, "keywords": ", ".join(k.strip() for k in re.split(r"[,၊\n]", keywords) if k.strip()),
            "answer": answer}
