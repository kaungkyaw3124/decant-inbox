from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

# cart -> confirmed -> waiting_payment -> photo_received -> paid -> delivered (docs/SPEC-orders.md)
ORDER_STATUSES = ("cart", "confirmed", "waiting_payment", "photo_received", "paid", "delivered",
                  "cancelled", "abandoned")
OPEN_STATUSES = ("cart", "confirmed", "waiting_payment", "photo_received")
QUICK_KINDS = ("price", "cart_add", "cart_remove", "cart_list", "confirm", "address", "contact", "not_stocked")
UNKNOWN_RESOLUTIONS = ("mapped", "new_product", "not_stocked")
AUTO_STATUSES = ("replied", "skipped")
MAX_PHONES = 3


class Order(Base):
    """A cart until paid; the Order ID (order_no) is given when a payment is approved (Step 5)."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status"),
        # one open cart per customer
        Index("uq_orders_open_per_customer", "customer_id", unique=True,
              postgresql_where=text(f"status IN {OPEN_STATUSES}")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), server_default="cart", default="cart")
    order_no: Mapped[int | None] = mapped_column(Integer, unique=True)
    total_mmk: Mapped[int] = mapped_column(Integer, server_default="0", default=0)  # priced items only
    address: Mapped[str | None] = mapped_column(Text)  # for this order (copied to the customer)
    phones: Mapped[list[str]] = mapped_column(ARRAY(String(20)), server_default="{}", default=list)  # copy
    list_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last cart list reply
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_info_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # cancelled/abandoned
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 default=func.now())  # last change: idle carts expire


class OrderItem(Base):
    """Removed items are kept (removed_at) so the history of the cart stays visible."""

    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("product_id IS NOT NULL OR unknown_text IS NOT NULL",
                                      name="product_or_unknown"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))  # None = unknown_text
    unknown_text: Mapped[str | None] = mapped_column(String(255))  # asked for, not in our list: blocks payment
    size_ml: Mapped[int | None] = mapped_column(Integer)  # None with is_full_bottle
    is_full_bottle: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    quantity: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    unit_price_mmk: Mapped[int | None] = mapped_column(Integer)  # price when added; None = no price yet
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    created_at: Mapped[datetime] = created_at_column()
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerPhone(Base):
    """A customer's phone numbers (max 3, first = main), saved when an admin taps "Save phone"."""

    __tablename__ = "customer_phones"
    __table_args__ = (UniqueConstraint("customer_id", "phone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    phone: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    created_at: Mapped[datetime] = created_at_column()


class QuickAction(Base):
    """A one-tap action on a customer message, with what is needed to undo it exactly."""

    __tablename__ = "quick_actions"
    __table_args__ = (CheckConstraint(f"kind IN {QUICK_KINDS}", name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    kind: Mapped[str] = mapped_column(String(20))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    outbox_id: Mapped[int | None] = mapped_column(ForeignKey("outbox.id"))
    undo: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None when auto
    auto: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)  # done by auto mode
    created_at: Mapped[datetime] = created_at_column()
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnknownRequest(Base):
    """How an admin resolved a product a customer asked for that was not in the list.
    not_stocked rows are the "wanted but not stocked" list (Step 6)."""

    __tablename__ = "unknown_requests"
    __table_args__ = (
        UniqueConstraint("message_id", "normalized_text"),
        CheckConstraint(f"resolution IN {UNKNOWN_RESOLUTIONS}", name="resolution"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    text: Mapped[str] = mapped_column(String(255))
    normalized_text: Mapped[str] = mapped_column(String(255))
    size_ml: Mapped[int | None] = mapped_column(Integer)
    is_full_bottle: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    resolution: Mapped[str] = mapped_column(String(16))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime] = created_at_column()


class AutoRun(Base):
    """Auto mode's final decision for an incoming message (at most one auto reply each)."""

    __tablename__ = "auto_runs"
    __table_args__ = (CheckConstraint(f"status IN {AUTO_STATUSES}", name="status"),)

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(120))
    quick_action_id: Mapped[int | None] = mapped_column(ForeignKey("quick_actions.id"))
    created_at: Mapped[datetime] = created_at_column()
