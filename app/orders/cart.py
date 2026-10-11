"""Cart: add/remove items, totals, state changes, and the cart / payment-info texts.

Nothing here sends anything: callers queue replies in the outbox. Every change bumps
orders.updated_at (carts idle for 3 days become "abandoned").
Changing the items of a confirmed cart sends it back to "cart" (the customer must
confirm the new list).
"""
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Customer, Order, OrderItem, PaymentMethod, Product
from app.models.orders import OPEN_STATUSES
from app.pricing.prices import current_prices, format_mmk, size_label
from app.replies.templates import render

IDLE_AFTER = timedelta(days=3)
MAX_QTY = 20


@dataclass(frozen=True)
class WantedItem:
    product_id: int
    size_ml: int | None
    is_full_bottle: bool = False
    quantity: int = 1


@dataclass
class CartView:
    order: Order
    lines: list[tuple[OrderItem, Product]]
    total: int
    unpriced: list[str] = field(default_factory=list)  # red: blocks payment info

    @property
    def empty(self) -> bool:
        return not self.lines


def open_cart(session: Session, customer_id: int, create: bool = False, lock: bool = False) -> Order | None:
    query = select(Order).where(Order.customer_id == customer_id, Order.status.in_(OPEN_STATUSES))
    order = session.scalar(query.with_for_update() if lock else query)
    if order is None and create:
        order = Order(customer_id=customer_id, status="cart")
        session.add(order)
        session.flush()
    return order


def _price(prices: dict, product: Product, size_ml: int | None, full: bool) -> tuple[int | None, bool]:
    """(unit price, in stock) of a size; full bottle also when size == bottle size."""
    for p in prices.get(product.id, []):
        if (full and p.size_ml is None) or (not full and p.size_ml == size_ml):
            return p.price_mmk, p.in_stock
    return None, True


def normalize_wanted(session: Session, item: WantedItem) -> WantedItem:
    """100ml of a 100ml bottle = full bottle."""
    product = session.get(Product, item.product_id)
    if not item.is_full_bottle and item.size_ml and product.full_size_ml == item.size_ml:
        return WantedItem(item.product_id, None, True, item.quantity)
    return item


def add_items(session: Session, order: Order, wanted: list[WantedItem], source_message_id: int | None) -> list[int]:
    """Add items (same product+size again -> quantity goes up). Returns new/changed item ids."""
    prices = current_prices(session, [w.product_id for w in wanted])
    changed = []
    for w in (normalize_wanted(session, w) for w in wanted):
        existing = session.scalar(select(OrderItem).where(
            OrderItem.order_id == order.id, OrderItem.removed_at.is_(None), OrderItem.product_id == w.product_id,
            OrderItem.size_ml.is_(None) if w.is_full_bottle else OrderItem.size_ml == w.size_ml,
            OrderItem.is_full_bottle == w.is_full_bottle))
        if existing is not None:
            # replace instead of stacking: a new line keeps the undo simple and exact
            existing.removed_at = datetime.now(UTC)
            quantity = min(existing.quantity + w.quantity, MAX_QTY)
        else:
            quantity = min(w.quantity, MAX_QTY)
        price, _ = _price(prices, session.get(Product, w.product_id), w.size_ml, w.is_full_bottle)
        item = OrderItem(order_id=order.id, product_id=w.product_id, size_ml=w.size_ml,
                         is_full_bottle=w.is_full_bottle, quantity=quantity, unit_price_mmk=price,
                         source_message_id=source_message_id)
        session.add(item)
        session.flush()
        changed.append(item.id)
        if existing is not None:
            changed.append(-existing.id)  # negative = removed by this change (for undo)
    touch(session, order, items_changed=True)
    return changed


def remove_items(session: Session, order: Order, wanted: list[WantedItem]) -> list[int]:
    """Remove matching items: product + size, or every size of the product if no size given."""
    removed = []
    now = datetime.now(UTC)
    for w in (normalize_wanted(session, w) for w in wanted):
        query = select(OrderItem).where(OrderItem.order_id == order.id, OrderItem.removed_at.is_(None),
                                        OrderItem.product_id == w.product_id)
        if w.is_full_bottle:
            query = query.where(OrderItem.is_full_bottle)
        elif w.size_ml:
            query = query.where(OrderItem.size_ml == w.size_ml)
        for item in session.scalars(query):
            item.removed_at = now
            removed.append(item.id)
    if removed:
        touch(session, order, items_changed=True)
    return removed


def remove_item_ids(session: Session, order: Order, ids: list[int]) -> None:
    session.execute(update(OrderItem).where(OrderItem.order_id == order.id, OrderItem.id.in_(ids))
                    .values(removed_at=datetime.now(UTC)))
    touch(session, order, items_changed=True)


def restore_item_ids(session: Session, order: Order, ids: list[int]) -> None:
    session.execute(update(OrderItem).where(OrderItem.order_id == order.id, OrderItem.id.in_(ids))
                    .values(removed_at=None))
    touch(session, order, items_changed=True)


def refill_prices(session: Session, order: Order) -> int:
    """Give unpriced items the current price (e.g. after it was added to the price list)."""
    items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id, OrderItem.removed_at.is_(None),
                                                    OrderItem.unit_price_mmk.is_(None))).all()
    prices = current_prices(session, [i.product_id for i in items])
    filled = 0
    for item in items:
        price, _ = _price(prices, session.get(Product, item.product_id), item.size_ml, item.is_full_bottle)
        if price is not None:
            item.unit_price_mmk = price
            filled += 1
    if filled:
        touch(session, order)
    return filled


def touch(session: Session, order: Order, items_changed: bool = False) -> None:
    session.flush()
    order.updated_at = datetime.now(UTC)
    order.total_mmk = view(session, order).total
    if items_changed and order.status in ("confirmed", "waiting_payment"):
        order.status, order.confirmed_at, order.payment_info_sent_at = "cart", None, None


def view(session: Session, order: Order) -> CartView:
    rows = session.execute(
        select(OrderItem, Product).join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order.id, OrderItem.removed_at.is_(None)).order_by(OrderItem.id)).all()
    total = sum((i.unit_price_mmk or 0) * i.quantity for i, _ in rows)
    unpriced = [f"{p.name} {item_size(i, p)}" for i, p in rows if i.unit_price_mmk is None]
    return CartView(order, [(i, p) for i, p in rows], total, unpriced)


def item_size(item: OrderItem, product: Product) -> str:
    label = size_label(None if item.is_full_bottle else item.size_ml, product.full_size_ml)
    return f"{label} × {item.quantity}" if item.quantity > 1 else label


# ---------- state ----------

def missing_contact(order: Order, customer: Customer) -> list[str]:
    missing = []
    if not order.address:
        missing.append("address")
    if not (order.phone or customer.phone):
        missing.append("phone")
    return missing


def payment_problems(session: Session, order: Order, customer: Customer) -> list[str]:
    """Why "Send payment info" is not possible yet (empty list = ready)."""
    cart = view(session, order)
    problems = []
    if cart.empty:
        problems.append("The cart is empty.")
    if order.status not in ("confirmed", "waiting_payment"):
        problems.append("The customer has not confirmed the cart yet.")
    if cart.unpriced:
        problems.append("No price for: " + ", ".join(cart.unpriced) + ".")
    for what in missing_contact(order, customer):
        problems.append(f"No {what} yet.")
    if not session.scalar(select(PaymentMethod.id).where(PaymentMethod.active).limit(1)):
        problems.append("No active payment method (Settings).")
    return problems


def confirm(session: Session, order: Order) -> None:
    order.status, order.confirmed_at = "confirmed", datetime.now(UTC)
    touch(session, order)


def set_contact(session: Session, order: Order, customer: Customer, address: str | None, phone: str | None) -> None:
    """Saves on the order and on the customer ("same address as last time" next time)."""
    if address is not None:
        order.address = customer.address = address
    if phone is not None:
        order.phone = customer.phone = phone
    touch(session, order)


def payment_info_sent(session: Session, order: Order, customer: Customer) -> None:
    order.status, order.payment_info_sent_at = "waiting_payment", datetime.now(UTC)
    order.phone = order.phone or customer.phone
    touch(session, order)


def cancel(session: Session, order: Order) -> None:
    order.status, order.closed_at = "cancelled", datetime.now(UTC)
    touch(session, order)


def abandon_idle(session: Session, now: datetime | None = None) -> int:
    """Carts nobody touched for 3 days (not yet waiting for payment) -> abandoned."""
    now = now or datetime.now(UTC)
    return session.execute(update(Order).where(
        Order.status.in_(("cart", "confirmed")), Order.updated_at < now - IDLE_AFTER)
        .values(status="abandoned", closed_at=now)).rowcount


# ---------- texts ----------

def item_lines(session: Session, order: Order, texts: dict[str, str]) -> list[str]:
    return [render(texts["cart_line"], product=p.name, size=item_size(i, p),
                   price=format_mmk((i.unit_price_mmk or 0) * i.quantity))
            for i, p in view(session, order).lines]


def cart_text(session: Session, order: Order, texts: dict[str, str]) -> str:
    cart = view(session, order)
    return "\n".join(item_lines(session, order, texts) + [render(texts["cart_total"], total=format_mmk(cart.total))])


def payment_text(session: Session, order: Order, texts: dict[str, str]) -> str:
    cart = view(session, order)
    methods = session.scalars(select(PaymentMethod).where(PaymentMethod.active)
                              .order_by(PaymentMethod.sort_order, PaymentMethod.id)).all()
    return "\n".join(
        item_lines(session, order, texts)
        + [render(texts["payment_total"], total=format_mmk(cart.total))]
        + [render(texts["payment_method_line"], name=m.name, account_number=m.account_number,
                  account_name=m.account_name) for m in methods]
        + [texts["payment_info_footer"]])


_PHONE_IN_TEXT = re.compile(r"(?:\+?95[\s-]?|0)9(?:[\s-]?[\d၀-၉]){7,9}")


def address_from_message(raw_text: str) -> str:
    """The message as the address, without the phone number (it is stored separately)."""
    text = _PHONE_IN_TEXT.sub(" ", raw_text.translate(str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")))
    return re.sub(r"[ \t]+", " ", text).strip(" ,\n")[:500]
