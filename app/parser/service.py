"""Database side of parsing, shared by the worker and scripts/reparse_all.py.

Writes parse_results + parse_items (and refreshes messages.normalized_text), and the
customer's phone when a message contains one (newest message wins). Never replaces a
human result: once someone has edited a message in the dashboard, rules leave it alone.
"""
from dataclasses import astuple
from datetime import timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.models import Customer, Message, ParseItem, ParseResult, Product, ProductAlias
from app.parser.normalize import normalize
from app.parser.rules import PARSER_VERSION, Alias, ParsedItem, ParseOutcome, parse

CONTEXT_WINDOW = timedelta(hours=24)


def load_aliases(session: Session) -> list[Alias]:
    rows = session.execute(
        select(ProductAlias.product_id, ProductAlias.normalized_alias)
        .join(Product, Product.id == ProductAlias.product_id)
        .where(Product.active)
    )
    return [Alias(product_id, alias) for product_id, alias in rows]


def load_full_sizes(session: Session) -> dict[int, int]:
    """Bottle size per product (from the price list): "100ml" of a 100ml bottle = full bottle."""
    return dict(session.execute(select(Product.id, Product.full_size_ml)
                                .where(Product.active, Product.full_size_ml.is_not(None))).all())


def unparsed_message_ids(session: Session, limit: int, skip: set[int] = frozenset()) -> list[int]:
    has_result = exists().where(ParseResult.message_id == Message.id, ParseResult.is_current)
    query = select(Message.id).where(~has_result, Message.direction == "in")  # only customers' messages
    if skip:
        query = query.where(Message.id.not_in(skip))
    return list(session.scalars(query.order_by(Message.id).limit(limit)))


def current_result(session: Session, message_id: int) -> ParseResult | None:
    return session.scalar(select(ParseResult).where(
        ParseResult.message_id == message_id, ParseResult.is_current
    ))


def context_product(session: Session, message: Message) -> int | None:
    """The product the customer mentioned last, in the 24 h before this message."""
    return session.scalar(
        select(ParseResult.product_id).join(Message, Message.id == ParseResult.message_id)
        .where(Message.customer_id == message.customer_id, Message.direction == "in",
               Message.received_at < message.received_at,
               Message.received_at >= message.received_at - CONTEXT_WINDOW,
               ParseResult.is_current, ParseResult.product_id.is_not(None))
        .order_by(Message.received_at.desc(), Message.id.desc()).limit(1))


def stored_items(session: Session, result_id: int) -> tuple[ParsedItem, ...]:
    rows = session.scalars(select(ParseItem).where(ParseItem.parse_result_id == result_id)
                           .order_by(ParseItem.position))
    return tuple(ParsedItem(r.product_id, r.size_ml, r.is_full_bottle, r.quantity, r.unknown_text,
                            r.from_context) for r in rows)


def _same(session: Session, result: ParseResult, outcome: ParseOutcome) -> bool:
    def key(items) -> list[tuple]:
        return [astuple(i)[:6] for i in items]  # without the match kind (not stored)

    return (
        result.parser_version == PARSER_VERSION
        and (result.intent, result.product_id, result.size_ml, result.quantity, result.confidence, result.phone)
        == (outcome.intent, outcome.product_id, outcome.size_ml, outcome.quantity, outcome.confidence, outcome.phone)
        and key(stored_items(session, result.id)) == key(outcome.items)
    )


def save_phone(session: Session, message: Message, phone: str) -> None:
    """Newest message with a number wins (reparse in any order gives the same result)."""
    customer = session.get(Customer, message.customer_id)
    if customer.phone_message_id is not None and customer.phone_message_id != message.id:
        source = session.get(Message, customer.phone_message_id)
        if source is not None and (source.received_at, source.id) > (message.received_at, message.id):
            return
    customer.phone, customer.phone_message_id = phone, message.id


def add_items(session: Session, result_id: int, items) -> None:
    for position, item in enumerate(items):
        session.add(ParseItem(
            parse_result_id=result_id, position=position, product_id=item.product_id, size_ml=item.size_ml,
            is_full_bottle=item.is_full_bottle, quantity=item.quantity,
            unknown_text=item.unknown_text[:255] if item.unknown_text else None, from_context=item.from_context))


def parse_message(session: Session, message: Message, aliases: list[Alias],
                  full_sizes: dict[int, int] | None = None) -> str:
    """Parse one message and store the result. Returns what happened:
    new | changed | unchanged | human (kept the human edit)."""
    normalized = normalize(message.raw_text, keep_newlines=True)
    if message.normalized_text != normalized:
        message.normalized_text = normalized

    current = current_result(session, message.id)
    if current is not None and current.method == "human":
        return "human"
    if full_sizes is None:
        full_sizes = load_full_sizes(session)
    outcome = parse(normalized, aliases, full_sizes, context_product(session, message))
    if outcome.phone:
        save_phone(session, message, outcome.phone)
    if current is not None and _same(session, current, outcome):
        return "unchanged"
    if current is not None:
        session.execute(update(ParseResult).where(ParseResult.id == current.id).values(is_current=False))
        session.flush()  # the partial unique index allows one current row per message
    result = ParseResult(
        message_id=message.id,
        intent=outcome.intent,
        product_id=outcome.product_id,
        size_ml=outcome.size_ml,
        quantity=outcome.quantity,
        confidence=outcome.confidence,
        method="rules",
        parser_version=PARSER_VERSION,
        is_current=True,
        phone=outcome.phone,
    )
    session.add(result)
    session.flush()
    add_items(session, result.id, outcome.items)
    return "new" if current is None else "changed"
