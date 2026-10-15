"""Cost prices (docs/SPEC-v3.md Step 8).

bottle_cost = what the owner paid for a full bottle (Excel column, history in product_costs).
Cost of one decant = bottle_cost / full_size_ml * size_ml + the vial cost of that size
(Settings, default 0); a full bottle costs bottle_cost. Unknown (no bottle cost or no bottle
size) = None, shown as "—". The cost is stamped on the order items when the order is paid.
"""
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AppSetting, Order, OrderItem, Product, ProductCost, User

VIAL_SETTING = "vial_costs"
MAX_VIAL_COST = 1_000_000


def current_costs(session: Session, product_ids: list[int] | None = None) -> dict[int, int]:
    """Newest bottle cost per product."""
    query = (select(ProductCost.product_id, ProductCost.bottle_cost_mmk).distinct(ProductCost.product_id)
             .order_by(ProductCost.product_id, ProductCost.effective_from.desc(), ProductCost.id.desc()))
    if product_ids is not None:
        query = query.where(ProductCost.product_id.in_(product_ids))
    return dict(session.execute(query).all())


def vial_costs(session: Session) -> dict[int, int]:
    """Vial / packaging cost per decant size in ml (missing = 0)."""
    row = session.get(AppSetting, VIAL_SETTING)
    return {int(k): int(v) for k, v in (row.value if row else {}).items()}


def set_vial_costs(session: Session, values: dict[int, int], user: User | None) -> None:
    for size, cost in values.items():
        if not 0 <= cost <= MAX_VIAL_COST:
            raise ValueError(f"Vial cost for {size}ml must be 0-{MAX_VIAL_COST:,}")
    value = {str(k): v for k, v in sorted(values.items()) if v}
    stmt = insert(AppSetting).values(key=VIAL_SETTING, value=value, updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


def unit_cost(full_size_ml: int | None, size_ml: int | None, is_full_bottle: bool, bottle_cost: int | None,
              vials: dict[int, int]) -> int | None:
    """Cost of one item (C2: 300,000 / 100 ml × 5 ml + 500 vial = 15,500)."""
    if bottle_cost is None:
        return None
    if is_full_bottle:
        return bottle_cost
    if not full_size_ml or not size_ml:
        return None
    return round(bottle_cost * size_ml / full_size_ml) + vials.get(size_ml, 0)


def stamp(session: Session, order: Order, only_missing: bool = True) -> int:
    """Copy today's costs onto the order's items (when it is paid). Returns items stamped."""
    rows = session.execute(select(OrderItem, Product).join(Product, Product.id == OrderItem.product_id).where(
        OrderItem.order_id == order.id, OrderItem.removed_at.is_(None))).all()
    costs = current_costs(session, [p.id for _, p in rows])
    vials = vial_costs(session)
    stamped = 0
    for item, product in rows:
        if only_missing and item.unit_cost_mmk is not None:
            continue
        cost = unit_cost(product.full_size_ml, item.size_ml, item.is_full_bottle, costs.get(product.id), vials)
        if cost is not None:
            item.unit_cost_mmk = cost
            stamped += 1
    return stamped
