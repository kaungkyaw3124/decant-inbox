"""Database side of parsing, shared by the worker and scripts/reparse_all.py.

Writes only parse_results (and refreshes messages.normalized_text). Never replaces a
human result: once someone has edited a message in the dashboard, rules leave it alone.
"""
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.models import Message, ParseResult, Product, ProductAlias
from app.parser.normalize import normalize
from app.parser.rules import PARSER_VERSION, Alias, ParseOutcome, parse


def load_aliases(session: Session) -> list[Alias]:
    rows = session.execute(
        select(ProductAlias.product_id, ProductAlias.normalized_alias)
        .join(Product, Product.id == ProductAlias.product_id)
        .where(Product.active)
    )
    return [Alias(product_id, alias) for product_id, alias in rows]


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


def _same(result: ParseResult, outcome: ParseOutcome) -> bool:
    return (
        result.parser_version == PARSER_VERSION
        and (result.intent, result.product_id, result.size_ml, result.quantity, result.confidence)
        == (outcome.intent, outcome.product_id, outcome.size_ml, outcome.quantity, outcome.confidence)
    )


def parse_message(session: Session, message: Message, aliases: list[Alias]) -> str:
    """Parse one message and store the result. Returns what happened:
    new | changed | unchanged | human (kept the human edit)."""
    normalized = normalize(message.raw_text)
    if message.normalized_text != normalized:
        message.normalized_text = normalized

    current = current_result(session, message.id)
    if current is not None and current.method == "human":
        return "human"
    outcome = parse(normalized, aliases)
    if current is not None and _same(current, outcome):
        return "unchanged"
    if current is not None:
        session.execute(update(ParseResult).where(ParseResult.id == current.id).values(is_current=False))
        session.flush()  # the partial unique index allows one current row per message
    session.add(ParseResult(
        message_id=message.id,
        intent=outcome.intent,
        product_id=outcome.product_id,
        size_ml=outcome.size_ml,
        quantity=outcome.quantity,
        confidence=outcome.confidence,
        method="rules",
        parser_version=PARSER_VERSION,
        is_current=True,
    ))
    return "new" if current is None else "changed"
