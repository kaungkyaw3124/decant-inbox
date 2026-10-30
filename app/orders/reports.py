"""Reports. "Wanted but not stocked" (docs/SPEC-v3.md 6.5): products customers asked for that
we don't have (unknown items the admin marked "We don't have it") and sizes that are out
of stock right now, with how often and by how many customers they were asked for."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Customer, Message, ParseItem, ParseResult, Product, UnknownRequest
from app.pricing.prices import latest_prices, size_label

ASK_INTENTS = ("buy", "ask_price", "ask_stock")


@dataclass
class Wanted:
    name: str
    kind: str  # not_stocked | out_of_stock
    times: int
    customers: int
    last_asked: datetime


def wanted(session: Session) -> list[Wanted]:
    rows = []
    not_test = Message.customer_id.not_in(select(Customer.id).where(Customer.is_tester))  # docs/SPEC-v4.14
    for name, times, customers, last in session.execute(
            select(func.max(UnknownRequest.text), func.count(), func.count(UnknownRequest.customer_id.distinct()),
                   func.max(Message.received_at))
            .join(Message, Message.id == UnknownRequest.message_id)
            .where(UnknownRequest.resolution == "not_stocked", not_test).group_by(UnknownRequest.normalized_text)):
        rows.append(Wanted(name, "not_stocked", times, customers, last))

    # asks for a size that is out of stock now
    stock = {pid: {size: p.in_stock for size, p in sizes.items() if p.price_mmk is not None}
             for pid, sizes in latest_prices(session).items()}
    asked: dict[tuple[int, int | None], list] = {}
    for item, message in session.execute(
            select(ParseItem, Message).join(ParseResult, ParseResult.id == ParseItem.parse_result_id)
            .join(Message, Message.id == ParseResult.message_id)
            .where(ParseResult.is_current, ParseResult.intent.in_(ASK_INTENTS), Message.direction == "in", not_test,
                   ParseItem.product_id.is_not(None), ParseItem.from_context.is_(False))):
        size = None if item.is_full_bottle else item.size_ml
        if (item.size_ml or item.is_full_bottle) and stock.get(item.product_id, {}).get(size) is False:
            asked.setdefault((item.product_id, size), []).append(message)
    products = {p.id: p for p in session.scalars(select(Product).where(
        Product.id.in_({pid for pid, _ in asked})))} if asked else {}
    for (pid, size), messages in asked.items():
        product = products[pid]
        rows.append(Wanted(f"{product.name} {size_label(size, product.full_size_ml)}", "out_of_stock",
                           len({m.id for m in messages}), len({m.customer_id for m in messages}),
                           max(m.received_at for m in messages)))
    return sorted(rows, key=lambda w: (-w.times, -w.customers, w.name.lower()))
