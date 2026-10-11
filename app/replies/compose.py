"""Build reply texts from templates + current prices. The admin always sees and can edit
the result before it is sent; nothing here sends anything."""
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Message, Outbox, ParseResult, Product
from app.pricing.prices import current_prices, format_mmk, size_label
from app.replies.templates import render

GREETING_GAP = timedelta(hours=6)
CONTEXT_WINDOW = timedelta(hours=24)
MAX_PRICE_ITEMS = 3


def needs_greeting(session: Session, customer_id: int, now: datetime | None = None) -> bool:
    """Greet only if we have not messaged this customer in the last 6 h (from the
    dashboard or from the phone)."""
    since = (now or datetime.now(UTC)) - GREETING_GAP
    sent = session.scalar(select(exists().where(
        Message.customer_id == customer_id, Message.direction == "out", Message.received_at >= since)))
    queued = session.scalar(select(exists().where(
        Outbox.customer_id == customer_id, Outbox.status.in_(("queued", "sending", "sent")),
        Outbox.created_at >= since)))
    return not (sent or queued)


def with_greeting(body: str, texts: dict[str, str], greet: bool) -> str:
    return f"{texts['greeting']}\n{body}" if greet and body else body


@dataclass
class PriceItem:
    product_id: int
    size: str  # "all" | "full" | "<ml>"


@dataclass
class Composed:
    text: str = ""
    problems: list[str] = field(default_factory=list)  # red; block sending
    notes: list[str] = field(default_factory=list)  # yellow; informational


def _tidy(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def price_reply(session: Session, items: list[PriceItem], texts: dict[str, str]) -> Composed:
    out = Composed()
    lines: list[str] = []
    products = {p.id: p for p in session.scalars(select(Product).where(
        Product.id.in_([i.product_id for i in items])))}
    prices = current_prices(session, list(products))
    for item in items:
        product = products.get(item.product_id)
        if product is None:
            continue
        sold = prices.get(product.id, [])
        if not sold:
            out.problems.append(f"{product.name}: no prices yet. Add them in the price list (Excel).")
            continue
        if item.size == "all":
            in_stock = [p for p in sold if p.in_stock]
            if not in_stock:
                lines.append(_tidy(render(texts["out_of_stock"], product=product.name, size="")))
                out.notes.append(f"{product.name} is out of stock: the out-of-stock reply is used.")
                continue
            lines.append(render(texts["price_list_header"], product=product.name))
            lines += [render(texts["price_list_line"], size=size_label(p.size_ml, product.full_size_ml),
                             price=format_mmk(p.price_mmk)) for p in in_stock]
            continue
        if item.size == "full":
            match = next((p for p in sold if p.size_ml is None), None)
        else:
            ml = int(item.size)
            match = next((p for p in sold if p.size_ml == ml), None)
            if match is None and ml == product.full_size_ml:
                match = next((p for p in sold if p.size_ml is None), None)
        if match is None:
            wanted = "full bottle" if item.size == "full" else f"{item.size}ml"
            have = ", ".join(size_label(p.size_ml, product.full_size_ml) for p in sold)
            out.problems.append(f"{product.name} {wanted} has no price. Sizes sold: {have}.")
            continue
        label = size_label(match.size_ml, product.full_size_ml)
        if not match.in_stock:
            lines.append(render(texts["out_of_stock"], product=product.name, size=label))
            out.notes.append(f"{product.name} {label} is out of stock: the out-of-stock reply is used.")
            continue
        lines.append(render(texts["price_one"], product=product.name, size=label, price=format_mmk(match.price_mmk)))
    out.text = "\n".join(lines)
    return out


def recent_requests(session: Session, customer_id: int, now: datetime | None = None) -> list[PriceItem]:
    """Products (and sizes) the customer mentioned in the last 24 h, newest first:
    the default selection for a price reply."""
    since = (now or datetime.now(UTC)) - CONTEXT_WINDOW
    rows = session.execute(
        select(ParseResult.product_id, ParseResult.size_ml)
        .join(Message, Message.id == ParseResult.message_id)
        .where(Message.customer_id == customer_id, Message.direction == "in", Message.received_at >= since,
               ParseResult.is_current, ParseResult.product_id.is_not(None))
        .order_by(Message.received_at.desc(), Message.id.desc())
    ).all()
    items: list[PriceItem] = []
    for product_id, size_ml in rows:
        if any(i.product_id == product_id for i in items):
            continue
        items.append(PriceItem(product_id, str(size_ml) if size_ml else "all"))
        if len(items) == MAX_PRICE_ITEMS:
            break
    return items
