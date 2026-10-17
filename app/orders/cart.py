"""Cart: add/remove items, totals, state changes, phones/address, and the cart /
payment-info texts.

Nothing here sends anything: callers queue replies in the outbox. Every change bumps
orders.updated_at (carts idle for 3 days become "abandoned").
Changing the items of a confirmed cart sends it back to "cart" (the customer must
confirm the new list).
Items can be "unknown" (a product we don't have in the list: unknown_text) or without a
price; both stay on the cart as red rows, are named in the cart reply, and block payment
info until an admin resolves them.
"""
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import Customer, CustomerPhone, Order, OrderItem, PaymentMethod, Product
from app.models.orders import MAX_PHONES, OPEN_STATUSES
from app.orders import address
from app.pricing.prices import current_prices, format_mmk, size_label
from app.replies.templates import render

IDLE_AFTER = timedelta(days=3)
MAX_QTY = 20


@dataclass(frozen=True)
class WantedItem:
    product_id: int | None  # None = unknown_text
    size_ml: int | None
    is_full_bottle: bool = False
    quantity: int = 1
    unknown_text: str | None = None


@dataclass
class CartView:
    order: Order
    lines: list[tuple[OrderItem, Product | None]]
    total: int  # priced items only
    unpriced: list[str] = field(default_factory=list)  # red: no price yet
    unknown: list[str] = field(default_factory=list)  # red: not in the product list

    @property
    def empty(self) -> bool:
        return not self.lines

    @property
    def problems(self) -> list[str]:
        """Names of items we must check before payment ("hawas ice 10ml")."""
        return self.unknown + self.unpriced


def open_cart(session: Session, customer_id: int, create: bool = False, lock: bool = False) -> Order | None:
    query = select(Order).where(Order.customer_id == customer_id, Order.status.in_(OPEN_STATUSES))
    order = session.scalar(query.with_for_update() if lock else query)
    if order is None and create:
        order = Order(customer_id=customer_id, status="cart", phones=[])
        session.add(order)
        session.flush()
    return order


def price_of(session: Session, product_id: int, size_ml: int | None, full: bool) -> tuple[int | None, bool]:
    """(unit price, in stock) of a size; None price = not sold / no price."""
    for p in current_prices(session, [product_id]).get(product_id, []):
        if (full and p.size_ml is None) or (not full and p.size_ml == size_ml):
            return p.price_mmk, p.in_stock
    return None, True


def normalize_wanted(session: Session, item: WantedItem) -> WantedItem:
    """100ml of a 100ml bottle = full bottle."""
    if item.product_id is None:
        return item
    product = session.get(Product, item.product_id)
    if not item.is_full_bottle and item.size_ml and product.full_size_ml == item.size_ml:
        return WantedItem(item.product_id, None, True, item.quantity)
    return item


def add_items(session: Session, order: Order, wanted: list[WantedItem], source_message_id: int | None,
              more: bool = True) -> list[int]:
    """Add items to the cart (never replaces it). The same product+size again: quantities
    added up when `more` (the admin's own add, or the customer said ထပ် / more), otherwise
    the line stays as it is (a customer repeating their order). Returns new item ids, and
    -id for lines this replaced (for undo)."""
    changed = []
    for w in (normalize_wanted(session, w) for w in wanted):
        existing = None
        if w.product_id is not None:
            existing = session.scalar(select(OrderItem).where(
                OrderItem.order_id == order.id, OrderItem.removed_at.is_(None), OrderItem.product_id == w.product_id,
                OrderItem.size_ml.is_(None) if w.is_full_bottle else OrderItem.size_ml == w.size_ml,
                OrderItem.is_full_bottle == w.is_full_bottle))
        if existing is not None and not more:
            continue  # already in the cart: keep one line
        quantity = min((existing.quantity if existing else 0) + w.quantity, MAX_QTY)
        if existing is not None:
            existing.removed_at = datetime.now(UTC)  # a new line keeps the undo simple and exact
        price = price_of(session, w.product_id, w.size_ml, w.is_full_bottle)[0] if w.product_id else None
        item = OrderItem(order_id=order.id, product_id=w.product_id, unknown_text=w.unknown_text,
                         size_ml=w.size_ml, is_full_bottle=w.is_full_bottle, quantity=quantity,
                         unit_price_mmk=price, source_message_id=source_message_id)
        session.add(item)
        session.flush()
        changed.append(item.id)
        if existing is not None:
            changed.append(-existing.id)
    touch(session, order, items_changed=True)
    return changed


def remove_items(session: Session, order: Order, wanted: list[WantedItem]) -> list[int]:
    """Remove matching items: product + size, or every size of the product if no size given."""
    removed = []
    now = datetime.now(UTC)
    for w in (normalize_wanted(session, w) for w in wanted):
        if w.product_id is None:
            continue
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
    items = session.scalars(select(OrderItem).where(
        OrderItem.order_id == order.id, OrderItem.removed_at.is_(None), OrderItem.product_id.is_not(None),
        OrderItem.unit_price_mmk.is_(None))).all()
    filled = 0
    for item in items:
        price, _ = price_of(session, item.product_id, item.size_ml, item.is_full_bottle)
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
        select(OrderItem, Product).outerjoin(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order.id, OrderItem.removed_at.is_(None)).order_by(OrderItem.id)).all()
    total = sum((i.unit_price_mmk or 0) * i.quantity for i, _ in rows)
    unknown = [item_name(i, p) for i, p in rows if p is None]
    unpriced = [item_name(i, p) for i, p in rows if p is not None and i.unit_price_mmk is None]
    return CartView(order, [(i, p) for i, p in rows], total, unpriced, unknown)


def item_size(item: OrderItem, product: Product | None) -> str:
    if product is None and not item.size_ml and not item.is_full_bottle:
        label = ""
    else:
        label = size_label(None if item.is_full_bottle else item.size_ml, product.full_size_ml if product else None)
    return f"{label} × {item.quantity}".strip() if item.quantity > 1 else label


def item_name(item: OrderItem, product: Product | None) -> str:
    return f"{product.name if product else item.unknown_text} {item_size(item, product)}".strip()


# ---------- phones and address ----------

def customer_phones(session: Session, customer_id: int) -> list[str]:
    return list(session.scalars(select(CustomerPhone.phone).where(CustomerPhone.customer_id == customer_id)
                                .order_by(CustomerPhone.position, CustomerPhone.id)))


def phone_rows(session: Session, customer_id: int) -> list[tuple[str, int | None]]:
    return [tuple(r) for r in session.execute(
        select(CustomerPhone.phone, CustomerPhone.source_message_id).where(CustomerPhone.customer_id == customer_id)
        .order_by(CustomerPhone.position, CustomerPhone.id))]


def set_customer_phones(session: Session, customer: Customer, rows: list[tuple[str, int | None]]) -> None:
    """Replace the customer's phone list (order kept, max 3) and keep customers.phone = first."""
    session.execute(delete(CustomerPhone).where(CustomerPhone.customer_id == customer.id))
    session.flush()
    for position, (phone, source) in enumerate(rows[:MAX_PHONES], start=1):
        session.add(CustomerPhone(customer_id=customer.id, phone=phone, position=position, source_message_id=source))
    customer.phone = rows[0][0] if rows else None
    session.flush()


def add_phones(session: Session, order: Order | None, customer: Customer, phones: list[str],
               source_message_id: int | None) -> list[str]:
    """Add new numbers (no duplicates, max 3) to the customer and copy the list to the order.
    Returns the numbers that were added."""
    rows = phone_rows(session, customer.id)
    known = {p for p, _ in rows}
    added = [p for p in phones if p not in known][:MAX_PHONES - len(rows)]
    set_customer_phones(session, customer, rows + [(p, source_message_id) for p in added])
    if order is not None:
        order.phones = customer_phones(session, customer.id)
        touch(session, order)
    return added


def replace_phones(session: Session, order: Order, customer: Customer, phones: list[str],
                   source_message_id: int | None) -> list[str]:
    """docs/SPEC-v4.8-change-info.md: "my new number is …": the order has ONLY the new number(s); on
    the customer they become phone 1 (2, …) and the old ones stay below (max 3)."""
    new = list(dict.fromkeys(phones))[:MAX_PHONES]
    rows = [r for r in phone_rows(session, customer.id) if r[0] not in new]
    set_customer_phones(session, customer, [(p, source_message_id) for p in new] + rows)
    order.phones = new
    touch(session, order)
    return new


def set_address(session: Session, order: Order, customer: Customer, check: address.Check) -> None:
    """Saved on the order and on the customer (offered again next time). Only a VALID address
    (docs/SPEC-v4.12-address-payment-ai.md: the validator has the final say)."""
    if not check.valid:
        raise ValueError(check.why or "not a valid address")
    order.address = customer.address = check.parts.full_text
    order.address_parts = customer.address_parts = check.parts.to_json()
    order.address_invalid = customer.address_invalid = False
    order.address_partial = order.address_partial_at = None
    touch(session, order)


def saved_address(customer: Customer) -> str | None:
    """The customer's address from last time, unless it failed the validator (never offered again)."""
    return customer.address if customer.address and not customer.address_invalid else None


def order_address(order: Order) -> str | None:
    """The order's address if it is usable (present and not marked invalid)."""
    return order.address if order.address and not order.address_invalid else None


def use_saved_contact(session: Session, order: Order, customer: Customer) -> None:
    """"Same phone & address as last time": fills what the order is missing."""
    if not order.phones:
        order.phones = customer_phones(session, customer.id)
    if not order_address(order) and saved_address(customer):
        order.address, order.address_parts = customer.address, customer.address_parts
        order.address_invalid = False
    touch(session, order)


def has_saved_contact(session: Session, order: Order, customer: Customer) -> bool:
    """Saved info that would fill something the order is missing."""
    return bool((not order.phones and customer_phones(session, customer.id))
                or (not order_address(order) and saved_address(customer)))


def missing_contact(order: Order) -> list[str]:
    """What to ask next, phone first (an invalid address counts as missing)."""
    return [what for what, ok in (("phone", order.phones), ("address", order_address(order))) if not ok]


def address_problem(order: Order) -> str | None:
    """docs/SPEC-v4.12-address-payment-ai.md N2: why the address blocks payment info / approval /
    the confirmation (None = fine)."""
    if order.address_invalid and order.address:
        return "The address is not valid: fix it in the cart panel."
    if not order.address:
        return "No address yet."
    return None


def payment_problems(session: Session, order: Order, customer: Customer | None = None) -> list[str]:
    """Why "Send payment info" is not possible yet (empty list = ready)."""
    cart = view(session, order)
    problems = []
    if cart.empty:
        problems.append("The cart is empty.")
    if order.status not in ("confirmed", "waiting_payment"):
        problems.append("The customer has not confirmed the cart yet.")
    if cart.unknown:
        problems.append("Not in the product list: " + ", ".join(cart.unknown) + ".")
    if cart.unpriced:
        problems.append("No price for: " + ", ".join(cart.unpriced) + ".")
    if not order.phones:
        problems.append("No phone yet.")
    if why := address_problem(order):
        problems.append(why)
    if not session.scalar(select(PaymentMethod.id).where(PaymentMethod.active).limit(1)):
        problems.append("No active payment method (Settings).")
    return problems


# ---------- state ----------

def confirm(session: Session, order: Order) -> None:
    order.status, order.confirmed_at = "confirmed", datetime.now(UTC)
    touch(session, order)


def payment_info_sent(session: Session, order: Order) -> None:
    order.status, order.payment_info_sent_at = "waiting_payment", datetime.now(UTC)
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
    """One line per priced item (unknown / unpriced items are named in the note)."""
    return [render(texts["cart_line"], product=p.name, size=item_size(i, p),
                   price=format_mmk(i.unit_price_mmk * i.quantity))
            for i, p in view(session, order).lines if p is not None and i.unit_price_mmk is not None]


def cart_text(session: Session, order: Order, texts: dict[str, str], notes: list[str] | None = None) -> str:
    """Items, total, items we must check, and the next question (Step 4d: the list asks for
    the phone directly; then the address; a returning customer is asked to confirm the
    saved phone and address)."""
    cart = view(session, order)
    lines = item_lines(session, order, texts) + [render(texts["cart_total"], total=format_mmk(cart.total))]
    if cart.problems:
        lines.append(render(texts["unknown_items_note"], names=", ".join(cart.problems)))
    lines += notes or []  # e.g. out of stock / we don't have it: before the question
    lines.append(closing_line(session, order, texts))
    return "\n".join(lines)


def closing_line(session: Session, order: Order, texts: dict[str, str]) -> str:
    """The question that ends a cart list: phone, else address, else "same as last time?". While the
    customer's new address / phone is awaited (4.8): ask for it, never offer the old one."""
    if order.change_wanted:
        return texts[{"address": "ask_new_address", "phone": "ask_new_phone"}.get(order.change_wanted,
                                                                                 "ask_new_contact")]
    customer = session.get(Customer, order.customer_id)
    phones = order.phones or customer_phones(session, customer.id)
    known = order_address(order) or saved_address(customer)
    if not phones:
        return texts["cart_ask_phone"]
    if not known:
        return texts["ask_address"]
    return render(texts["cart_returning"], phones=", ".join(phones), address=known)


def payment_text(session: Session, order: Order, texts: dict[str, str], changed: bool = False) -> str:
    """changed: the order changed after payment info was sent (docs/SPEC-v4.10-interruptions.md):
    "စုစုပေါင်း အသစ် … ကျပ်ပါ။" instead of the normal total line."""
    cart = view(session, order)
    methods = session.scalars(select(PaymentMethod).where(PaymentMethod.active)
                              .order_by(PaymentMethod.sort_order, PaymentMethod.id)).all()
    return "\n".join(
        item_lines(session, order, texts)
        + [render(texts["cart_total_changed" if changed else "payment_total"], total=format_mmk(cart.total))]
        + [render(texts["payment_method_line"], name=m.name, account_number=m.account_number,
                  account_name=m.account_name) for m in methods]
        + [texts["payment_info_footer"]])


_PHONE_IN_TEXT = re.compile(r"(?:\+?95[\s-]?|0)9(?:[\s-]?\d){7,9}")
TRAILING_ASK = re.compile(r"\s*(?:ကို)?\s*ပို့ပေးပါ(?:နော်|ရှင့်|ရှင်|ခင်ဗျာ)?\s*[။.!]*\s*$")
# "ဒီလိပ်စာကိုပို့ပေးပါ - …", "လိပ်စာအသစ်က …", "new address: …" (docs/SPEC-v4.8-change-info.md): not part of it
LEADING_ASK = re.compile(
    r"^\s*(?:(?:ဒီ\s*)?လိပ်စာ\s*(?:အသစ်)?\s*(?:ကိုပဲ|ကို|က)?\s*(?:ပြောင်း(?:ချင်|မယ်)?(?:ပါ)?(?:တယ်)?\s*)?"
    r"(?:ပို့\s*(?:ပေး)?\s*ပါ(?:နော်|ရှင့်)?)?|ဒီ\s*ကို\s*(?:ပဲ\s*)?ပို့\s*(?:ပေး)?\s*ပါ|"
    r"(?:(?:this|new|my|change)\s+)?address(?:\s+is)?)\s*[:：\-–,။]*\s*", re.IGNORECASE)
_PHONE_WORDS = re.compile(
    r"(?i)(?:ဖုန်းနံပါတ်|ဖုန်း|(?<![a-z])(?:phone(?:\s*no)?|ph(?:\s*no)?|tel)(?![a-z])\.?)\s*[:：-]?\s*")


def address_from_message(raw_text: str) -> str:
    """The message as the address: without phone numbers and without a trailing
    "ကိုပို့ပေးပါ" (Burmese digits become 0-9)."""
    text = raw_text.translate(str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789"))
    text = _PHONE_WORDS.sub(" ", _PHONE_IN_TEXT.sub(" ", text))
    text = TRAILING_ASK.sub("", re.sub(r"[ \t]+", " ", text).strip(" ,\n"))
    text = LEADING_ASK.sub("", text, count=1)
    return text.strip(" ,\n")[:500]
