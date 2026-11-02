"""Current prices and how they are shown. size_ml None = full bottle everywhere here."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProductPrice

DEFAULT_SIZES = (2, 5, 10)  # always offered as columns in the Excel export


@dataclass(frozen=True)
class Price:
    size_ml: int | None  # None = full bottle
    price_mmk: int | None  # None = no longer sold
    in_stock: bool
    effective_from: datetime


def latest_prices(session: Session, product_ids: list[int] | None = None) -> dict[int, dict[int | None, Price]]:
    """Newest row per (product, size), including "no longer sold" rows (price None)."""
    query = (select(ProductPrice)
             .distinct(ProductPrice.product_id, ProductPrice.size_ml)  # NULL sizes group together
             .order_by(ProductPrice.product_id, ProductPrice.size_ml,
                       ProductPrice.effective_from.desc(), ProductPrice.id.desc()))
    if product_ids is not None:
        query = query.where(ProductPrice.product_id.in_(product_ids))
    result: dict[int, dict[int | None, Price]] = {}
    for row in session.scalars(query):
        result.setdefault(row.product_id, {})[row.size_ml] = Price(
            row.size_ml, row.price_mmk, row.in_stock, row.effective_from)
    return with_stock(session, result)


def with_stock(session: Session, result: dict[int, dict[int | None, Price]]) -> dict[int, dict[int | None, Price]]:
    """docs/SPEC-v5.1 I1: perfumes with bottles in the stock list are in stock only when the stock can fill the
    size; perfumes without bottles keep the price list's manual in_stock flag."""
    from app.inventory import stock  # late import: inventory -> models only

    levels = stock.levels(session, list(result))
    if not levels:
        return result
    vials, spill = stock.vials(session), stock.settings(session)["spill_ml"]
    for pid, level in levels.items():
        for size, p in result.get(pid, {}).items():
            result[pid][size] = Price(p.size_ml, p.price_mmk, stock.sellable(level, size, vials, spill), p.effective_from)
    return result


def current_prices(session: Session, product_ids: list[int] | None = None) -> dict[int, list[Price]]:
    """Sizes currently sold, per product: decants by size, then the full bottle."""
    return {
        pid: sorted((p for p in sizes.values() if p.price_mmk is not None), key=size_sort_key)
        for pid, sizes in latest_prices(session, product_ids).items()
    }


def size_sort_key(price: Price) -> tuple[int, int]:
    return (1, 0) if price.size_ml is None else (0, price.size_ml)


def format_mmk(amount: int) -> str:
    return f"{amount:,}"


def size_label(size_ml: int | None, full_size_ml: int | None) -> str:
    if size_ml is not None:
        return f"{size_ml}ml"
    return f"Full {full_size_ml}ml" if full_size_ml else "Full bottle"
