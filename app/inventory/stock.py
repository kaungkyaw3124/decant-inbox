"""docs/SPEC-v5.1-inventory.md: stock in ml — availability, deducting packed orders, history.

- Available ml of a perfume = open bottles' remaining + sealed bottles' size. A decant size is sellable when
  available ml >= size + spill (settings, default 0.3 ml) and a vial of that size is in stock (a vial size the
  shop never entered is not checked, so the shop can start gradually). A full bottle needs a sealed bottle.
- Products WITHOUT any bottle keep the manual in_stock flag of the price list (pricing.prices applies this).
- sync(order): an order that is packed / sent out / delivered holds its stock; any other status holds none.
  Called after every status change, undo and cancel, so packing deducts, and undo / cancel give it back.
  Pouring takes the oldest open bottle first, then opens the next sealed one. Never negative: not enough stock
  -> StockError (the "Packed" button says so).
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AppSetting, Bottle, Order, OrderItem, Product, StockMove, User, Vial

SETTING = "inventory"
DEFAULTS = {"spill_ml": 0.3, "low_ml": 10, "low_vials": 10}
HOLDS = ("packed", "sent_out", "delivered")


class StockError(Exception):
    pass


def settings(session: Session) -> dict:
    row = session.get(AppSetting, SETTING)
    return {**DEFAULTS, **(row.value if row else {})}


def save_settings(session: Session, values: dict, user: User | None) -> None:
    stmt = insert(AppSetting).values(key=SETTING, value={**settings(session), **values},
                                     updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


@dataclass
class Level:
    product_id: int
    open_ml: float = 0.0
    sealed: list[int] = field(default_factory=list)  # sizes of the sealed bottles

    @property
    def available_ml(self) -> float:
        return self.open_ml + sum(self.sealed)


def levels(session: Session, product_ids: list[int] | None = None) -> dict[int, Level]:
    """Products that have bottles (any status) -> their level. Products with no bottle are absent."""
    query = select(Bottle.product_id, Bottle.status, Bottle.size_ml, Bottle.remaining_ml)
    if product_ids is not None:
        query = query.where(Bottle.product_id.in_(product_ids))
    found: dict[int, Level] = {}
    for pid, status, size, remaining in session.execute(query):
        level = found.setdefault(pid, Level(pid))
        if status == "open":
            level.open_ml += float(remaining)
        elif status == "sealed":
            level.sealed.append(size)
    return found


def vials(session: Session) -> dict[int, int]:
    return dict(session.execute(select(Vial.size_ml, Vial.count)).all())


def sellable(level: Level, size_ml: int | None, vial_counts: dict[int, int], spill: float) -> bool:
    if size_ml is None:  # the full bottle
        return bool(level.sealed)
    if size_ml in vial_counts and vial_counts[size_ml] < 1:
        return False
    return level.available_ml + 1e-9 >= size_ml + spill


def _move(session: Session, kind: str, user: User | None, reason: str, **values) -> None:
    session.add(StockMove(kind=kind, user_id=user.id if user else None, reason=reason[:200], **values))


def _out_now(session: Session, order_id: int) -> list[StockMove]:
    """The order's decant moves since its last give-back (empty = its stock is not out)."""
    last_return = session.scalar(select(func.coalesce(func.max(StockMove.id), 0)).where(
        StockMove.order_id == order_id, StockMove.kind == "return"))
    return list(session.scalars(select(StockMove).where(StockMove.order_id == order_id, StockMove.kind == "decant",
                                                        StockMove.id > last_return).order_by(StockMove.id)))


def sync(session: Session, order: Order, user: User | None) -> None:
    """Make the order's stock match its status (idempotent). Raises StockError when short."""
    out = _out_now(session, order.id)
    if order.status in HOLDS and not out:
        _take(session, order, user)
    elif order.status not in HOLDS and out:
        _give_back(session, order, out, user)


def _items(session: Session, order: Order) -> list[OrderItem]:
    return list(session.scalars(select(OrderItem).where(OrderItem.order_id == order.id,
                                                        OrderItem.removed_at.is_(None))))


def _take(session: Session, order: Order, user: User | None) -> None:
    spill = settings(session)["spill_ml"]
    label = f"order #{order.order_no}"
    stocked = levels(session, [i.product_id for i in _items(session, order) if i.product_id])
    counts = vials(session)
    short = []
    for item in _items(session, order):
        if item.product_id not in stocked:
            continue  # no bottles entered for this perfume: manual stock
        qty = item.quantity
        if item.is_full_bottle or item.size_ml is None:
            sealed = session.scalars(select(Bottle).where(Bottle.product_id == item.product_id,
                                                          Bottle.status == "sealed").order_by(Bottle.id)
                                     .with_for_update().limit(qty)).all()
            if len(sealed) < qty:
                short.append(f"{_name(session, item.product_id)} full bottle")
                continue
            for b in sealed:
                _move(session, "decant", user, label, product_id=item.product_id, bottle_id=b.id,
                      ml_change=-Decimal(b.remaining_ml), order_id=order.id)
                b.remaining_ml, b.status = 0, "empty"
            continue
        if item.size_ml in counts:
            if counts[item.size_ml] < qty:
                short.append(f"{item.size_ml}ml vials")
                continue
            session.execute(Vial.__table__.update().where(Vial.size_ml == item.size_ml)
                            .values(count=Vial.count - qty))
            counts[item.size_ml] -= qty
            _move(session, "decant", user, label, vial_size=item.size_ml, count_change=-qty, order_id=order.id)
        need = Decimal(str((item.size_ml + spill) * qty))
        if not _pour(session, item.product_id, need, user, label, order.id):
            short.append(f"{_name(session, item.product_id)} {item.size_ml}ml")
    if short:
        raise StockError("Not enough stock: " + ", ".join(short) + ". Add stock (Products → Stock) first.")


def _pour(session: Session, product_id: int, need: Decimal, user, label: str, order_id: int) -> bool:
    bottles = session.scalars(select(Bottle).where(Bottle.product_id == product_id, Bottle.status.in_(("open", "sealed")))
                              .order_by(case((Bottle.status == "open", 0), else_=1), Bottle.opened_at, Bottle.id)
                              .with_for_update()).all()  # the oldest open bottle first, then sealed ones
    if sum(Decimal(b.remaining_ml) for b in bottles) < need:
        return False
    for b in bottles:
        if need <= 0:
            break
        if b.status == "sealed":
            b.status, b.opened_at = "open", datetime.now(UTC)
        take = min(Decimal(b.remaining_ml), need)
        b.remaining_ml = Decimal(b.remaining_ml) - take
        need -= take
        if b.remaining_ml <= 0:
            b.status = "empty"
        _move(session, "decant", user, label, product_id=product_id, bottle_id=b.id, ml_change=-take,
              order_id=order_id)
    return True


def _give_back(session: Session, order: Order, out: list[StockMove], user: User | None) -> None:
    """Undo / cancel after packing: the order's decant moves in reverse (into the same bottles / vials)."""
    for m in out:
        if m.bottle_id:
            b = session.get(Bottle, m.bottle_id, with_for_update=True)
            b.remaining_ml = Decimal(b.remaining_ml) - Decimal(m.ml_change)
            # a full bottle sold and given back was never opened: sealed again
            b.status = "sealed" if b.opened_at is None else "open"
        if m.vial_size:
            session.execute(Vial.__table__.update().where(Vial.size_ml == m.vial_size)
                            .values(count=Vial.count - m.count_change))
        _move(session, "return", user, f"order #{order.order_no} {order.status}", product_id=m.product_id,
              bottle_id=m.bottle_id, vial_size=m.vial_size, ml_change=-Decimal(m.ml_change),
              count_change=-m.count_change, order_id=order.id)


def _name(session: Session, product_id: int) -> str:
    return session.get(Product, product_id).name


# ---------- the Stock screen: add / open / adjust, vials, reorder list, value, history ----------

def add_bottles(session: Session, product_id: int, size_ml: int, count: int, cost_mmk: int | None,
                remaining_ml: float | None, user: User | None, reason: str = "purchase") -> list[Bottle]:
    if size_ml <= 0 or count <= 0 or count > 50:
        raise StockError("Bottle size and count must be more than 0 (max 50 bottles at once).")
    if remaining_ml is not None and not 0 <= remaining_ml <= size_ml:
        raise StockError("Remaining ml must be between 0 and the bottle size.")
    added = []
    for _ in range(count):
        left = Decimal(str(size_ml if remaining_ml is None else remaining_ml))
        b = Bottle(product_id=product_id, size_ml=size_ml, remaining_ml=left, cost_mmk=cost_mmk,
                   status="sealed" if left >= size_ml else ("open" if left > 0 else "empty"),
                   opened_at=None if left >= size_ml else datetime.now(UTC))
        session.add(b)
        session.flush()
        _move(session, "purchase", user, reason, product_id=product_id, bottle_id=b.id, ml_change=left)
        added.append(b)
    return added


def open_bottle(session: Session, bottle: Bottle, user: User | None) -> None:
    if bottle.status != "sealed":
        raise StockError("Only a sealed bottle can be opened.")
    bottle.status, bottle.opened_at = "open", datetime.now(UTC)
    _move(session, "adjust", user, "opened", product_id=bottle.product_id, bottle_id=bottle.id)


def adjust_bottle(session: Session, bottle: Bottle, remaining_ml: float, reason: str, user: User | None) -> None:
    """Count / spill / gift: set what is really left (the difference goes into the history)."""
    if not reason.strip():
        raise StockError("Write why (count, spill, gift, ...).")
    if not 0 <= remaining_ml <= bottle.size_ml:
        raise StockError("Remaining ml must be between 0 and the bottle size.")
    new = Decimal(str(remaining_ml))
    change = new - Decimal(bottle.remaining_ml)
    bottle.remaining_ml = new
    if new <= 0:
        bottle.status = "empty"
    elif bottle.status == "empty" or (bottle.status == "sealed" and new < bottle.size_ml):
        bottle.status, bottle.opened_at = "open", bottle.opened_at or datetime.now(UTC)
    kind = "waste" if change < 0 and "spill" in reason.lower() else "adjust"
    _move(session, kind, user, reason.strip(), product_id=bottle.product_id, bottle_id=bottle.id, ml_change=change)


def change_vials(session: Session, size_ml: int, change: int, cost_each: int | None, reason: str,
                 user: User | None) -> None:
    if size_ml <= 0 or size_ml > 100:
        raise StockError("Vial size must be 1-100 ml.")
    row = session.get(Vial, size_ml, with_for_update=True)
    if row is None:
        row = Vial(size_ml=size_ml, count=0, cost_each_mmk=cost_each)
        session.add(row)
    if row.count + change < 0:
        raise StockError(f"Only {row.count} vials of {size_ml} ml.")
    row.count += change
    if cost_each is not None:
        row.cost_each_mmk = cost_each
    _move(session, "purchase" if change > 0 else "adjust", user, reason or "vials", vial_size=size_ml,
          count_change=change)


def low_threshold(cfg: dict, product_id: int) -> float:
    return float(cfg.get("low_ml_products", {}).get(str(product_id), cfg["low_ml"]))


def overview(session: Session) -> dict:
    """Everything the Stock screen shows (I3)."""
    from datetime import timedelta

    from app.pricing.prices import current_prices

    cfg = settings(session)
    lv = levels(session)
    products = {p.id: p for p in session.scalars(select(Product).where(Product.id.in_(list(lv))))}
    prices = current_prices(session, list(lv))
    bottles = {}
    for b in session.scalars(select(Bottle).where(Bottle.status != "empty").order_by(Bottle.status, Bottle.opened_at,
                                                                                      Bottle.id)):
        bottles.setdefault(b.product_id, []).append(b)
    since = datetime.now(UTC) - timedelta(days=30)
    sold = dict(session.execute(select(StockMove.product_id, -func.sum(StockMove.ml_change)).where(
        StockMove.kind == "decant", StockMove.created_at >= since, StockMove.product_id.is_not(None))
        .group_by(StockMove.product_id)).all())
    rows = []
    for pid, level in lv.items():
        full = sum(b.size_ml for b in bottles.get(pid, [])) or 1
        rows.append({"product": products[pid], "level": level, "bottles": bottles.get(pid, []),
                     "percent": min(100, round(100 * level.available_ml / full)),
                     "sizes": [p for p in prices.get(pid, []) if p.in_stock],
                     "low": level.available_ml < low_threshold(cfg, pid), "threshold": low_threshold(cfg, pid),
                     "sold_30d": float(sold.get(pid) or 0)})
    rows.sort(key=lambda r: (r["product"].brand, r["product"].name))
    vial_rows = session.scalars(select(Vial).order_by(Vial.size_ml)).all()
    low_vials = [v for v in vial_rows if v.count < int(cfg.get("low_vials_sizes", {}).get(str(v.size_ml),
                                                                                           cfg["low_vials"]))]
    value = sum(float(b.remaining_ml) / b.size_ml * (b.cost_mmk or 0) for bs in bottles.values() for b in bs) + sum(
        v.count * (v.cost_each_mmk or 0) for v in vial_rows)
    return {"rows": rows, "vials": vial_rows, "reorder": sorted([r for r in rows if r["low"]],
                                                                key=lambda r: -r["sold_30d"]),
            "low_vials": low_vials, "value": round(value), "cfg": cfg}


def history_query() -> Select:
    """Stock moves, newest first (the Stock page pages them)."""
    return (select(StockMove, Product, User).outerjoin(Product, Product.id == StockMove.product_id)
            .outerjoin(User, User.id == StockMove.user_id).order_by(StockMove.id.desc()))


def low_lines(session: Session) -> list[str]:
    """For the daily alert (I4): what to reorder."""
    o = overview(session)
    return ([f"{r['product'].name}: {r['level'].available_ml:.0f} ml left" for r in o["reorder"]]
            + [f"{v.size_ml} ml vials: {v.count} left" for v in o["low_vials"]])


def apply_import(session: Session, bottles: list, vials_rows: list, user: User | None) -> dict[str, int]:
    for r in bottles:
        add_bottles(session, r.product_id, r.bottle_ml, 1, r.cost_mmk, r.remaining_ml, user, "stock import")
    for v in vials_rows:
        change_vials(session, v.size_ml, v.count, v.cost_each_mmk, "stock import", user)
    return {"bottles": len(bottles), "vials": sum(v.count for v in vials_rows)}
