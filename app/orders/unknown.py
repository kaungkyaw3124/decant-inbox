"""Unknown items: a customer asked for something that is not in the product list.

The admin resolves each one (docs/SPEC-orders.md Step 4c):
  map         "It's in my list"  -> the customer's words become a learned alias
  new_product "New product"      -> product + price(s) + alias
  not_stocked "We don't have it" -> the item is dropped; the reply says we don't have it
Then the message is re-parsed at once, so the one-tap button / auto mode continues
exactly as if the message had been recognised. Every resolution is kept in
unknown_requests (not_stocked rows = "wanted but not stocked", Step 6).
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rapidfuzz import fuzz
from sqlalchemy import and_, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Message, ParseItem, ParseResult, Product, ProductAlias, ProductPrice, UnknownRequest, User,
)
from app.parser.normalize import normalize
from app.parser.service import load_aliases, load_full_sizes, parse_message

NEEDS_YOU_WINDOW = timedelta(days=3)
QUESTION_INTENTS = ("buy", "ask_price", "ask_stock")


@dataclass(frozen=True)
class Unknown:
    position: int
    text: str
    size_ml: int | None
    is_full_bottle: bool


def open_unknowns(session: Session, message: Message) -> list[Unknown]:
    """Unknown items of the message's current parse that nobody has resolved yet."""
    result = session.scalar(select(ParseResult).where(ParseResult.message_id == message.id, ParseResult.is_current))
    if result is None or result.intent not in QUESTION_INTENTS:
        return []
    from app.replies import faq  # late import: faq -> models only, but keep this module light

    if faq.for_message(session, message, result) is not None:
        return []  # "kpay ရလား": an FAQ question, not an unknown product
    done = set(session.scalars(select(UnknownRequest.normalized_text).where(UnknownRequest.message_id == message.id)))
    return [Unknown(i.position, i.unknown_text, i.size_ml, i.is_full_bottle) for i in session.scalars(
        select(ParseItem).where(ParseItem.parse_result_id == result.id, ParseItem.unknown_text.is_not(None))
        .order_by(ParseItem.position)) if normalize(i.unknown_text) not in done]


def not_stocked_texts(session: Session, message_id: int) -> set[str]:
    return set(session.scalars(select(UnknownRequest.normalized_text).where(
        UnknownRequest.message_id == message_id, UnknownRequest.resolution == "not_stocked")))


def messages_needing_you(session: Session, now: datetime | None = None) -> list[Message]:
    """Recent incoming messages with unresolved unknown items (newest first)."""
    now = now or datetime.now(UTC)
    resolved = exists().where(and_(UnknownRequest.message_id == Message.id,
                                   UnknownRequest.normalized_text == ParseItem.unknown_text))
    rows = session.scalars(
        select(Message).join(ParseResult, and_(ParseResult.message_id == Message.id, ParseResult.is_current))
        .join(ParseItem, ParseItem.parse_result_id == ParseResult.id)
        .where(Message.direction == "in", Message.received_at >= now - NEEDS_YOU_WINDOW,
               ParseResult.intent.in_(QUESTION_INTENTS), ParseItem.unknown_text.is_not(None), ~resolved)
        .order_by(Message.received_at.desc()).distinct()).all()
    return sorted({m for m in rows if open_unknowns(session, m)}, key=lambda m: m.received_at, reverse=True)


def suggestions(session: Session, text: str, limit: int = 5) -> list[Product]:
    """Active products most like the customer's words (fuzzy), best first."""
    target = normalize(text)
    scored = []
    for product in session.scalars(select(Product).where(Product.active)):
        names = [normalize(product.name), normalize(f"{product.brand} {product.name}")]
        score = max(fuzz.WRatio(target, n) for n in names)
        scored.append((score, product))
    return [p for _, p in sorted(scored, key=lambda sp: -sp[0])[:limit]]


def _record(session: Session, message: Message, item: Unknown, resolution: str, product_id: int | None,
            user: User) -> None:
    session.execute(insert(UnknownRequest).values(
        message_id=message.id, customer_id=message.customer_id, text=item.text[:255],
        normalized_text=normalize(item.text)[:255], size_ml=item.size_ml, is_full_bottle=item.is_full_bottle,
        resolution=resolution, product_id=product_id, resolved_by=user.id,
    ).on_conflict_do_nothing(index_elements=["message_id", "normalized_text"]))
    session.add(AuditLog(user_id=user.id, action=f"unknown.{resolution}", details={
        "message_id": message.id, "text": item.text, "product_id": product_id}))


def _add_alias(session: Session, product_id: int, text: str) -> None:
    norm = normalize(text)
    if len(norm) >= 2:
        session.execute(insert(ProductAlias).values(
            product_id=product_id, alias_text=text.strip(), normalized_alias=norm, source="learned",
        ).on_conflict_do_nothing())


def reparse(session: Session, message: Message) -> None:
    """Re-parse now (the worker would do it within seconds after an alias change)."""
    session.flush()
    parse_message(session, message, load_aliases(session), load_full_sizes(session))


def map_to_product(session: Session, message: Message, item: Unknown, product_id: int, user: User) -> None:
    _add_alias(session, product_id, item.text)
    _record(session, message, item, "mapped", product_id, user)
    reparse(session, message)


def new_product(session: Session, message: Message, item: Unknown, user: User, brand: str, name: str,
                prices: dict[int | None, int], full_size_ml: int | None, in_stock: bool) -> Product:
    """prices: size_ml -> price (None = full bottle)."""
    product = Product(brand=brand, name=name, source="manual", active=True, full_size_ml=full_size_ml)
    session.add(product)
    session.flush()
    now = datetime.now(UTC)
    for size, price in prices.items():
        session.add(ProductPrice(product_id=product.id, size_ml=size, is_full_bottle=size is None,
                                 price_mmk=price, in_stock=in_stock, effective_from=now, created_by=user.id))
    _add_alias(session, product.id, name)
    _add_alias(session, product.id, item.text)
    _record(session, message, item, "new_product", product.id, user)
    reparse(session, message)
    return product


def not_stocked(session: Session, message: Message, item: Unknown, user: User) -> None:
    _record(session, message, item, "not_stocked", None, user)
