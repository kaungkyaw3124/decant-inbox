from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

# cart -> confirmed -> waiting_payment -> photo_received -> paid -> packed -> sent_out -> delivered
# (docs/SPEC-orders.md, docs/SPEC-v3.md 6.1)
ORDER_STATUSES = ("cart", "confirmed", "waiting_payment", "photo_received", "paid", "packed", "sent_out",
                  "delivered", "cancelled", "abandoned")
OPEN_STATUSES = ("cart", "confirmed", "waiting_payment", "photo_received")
PAID_STATUSES = ("paid", "packed", "sent_out", "delivered")  # counted as sales
SHIPPING_STATUSES = ("paid", "packed", "sent_out")  # paid, not delivered yet
QUICK_KINDS = ("price", "cart_add", "cart_remove", "cart_list", "confirm", "address", "contact", "not_stocked",
               "delivery", "cancel_order", "faq", "greeting", "teach", "choose_previous", "change_info")
CHANGE_WANTED = ("address", "phone", "both", "unclear")  # docs/SPEC-v4.8-change-info.md
EVENT_KINDS = ("status", "contact", "address_checked")
UNKNOWN_RESOLUTIONS = ("mapped", "new_product", "not_stocked")
AUTO_STATUSES = ("replied", "skipped")
# pending: one screenshot to check · several: more than one photo (ask for one) ·
# approved -> order paid · rejected -> back to waiting payment · not_payment: dismissed
CHECK_DECISIONS = ("pending", "several", "approved", "rejected", "not_payment")
REJECT_REASONS = ("not_received", "wrong_screenshot", "wrong_amount")
FIRST_ORDER_NO = 1001
MAX_PHONES = 3


class Order(Base):
    """A cart until paid; the Order ID (order_no) is given when a payment is approved (Step 5)."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status"),
        CheckConstraint(f"change_wanted IN {CHANGE_WANTED}", name="change_wanted"),
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
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deli_name: Mapped[str | None] = mapped_column(String(64))  # optional, given with "Sent out"
    deli_phone: Mapped[str | None] = mapped_column(String(32))
    deli_note: Mapped[str | None] = mapped_column(Text)  # for us only
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # one payment reminder
    cancel_note: Mapped[str | None] = mapped_column(Text)  # why it was cancelled (admin / auto)
    # docs/SPEC-v4.8-change-info.md: the customer wants to change the address / phone; we asked for the
    # new one. While set, payment info waits and the next address / phone REPLACES the old one.
    change_wanted: Mapped[str | None] = mapped_column(String(8))
    change_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    unit_cost_mmk: Mapped[int | None] = mapped_column(Integer)  # cost when paid (bottle share + vial); None = unknown
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


class PaymentCheck(Base):
    """A payment screenshot to check. The admin types the transaction ID from their own
    KPay/AYA history; approving gives the order its Order ID. A reused transaction ID or
    image is a warning (second confirm), not a database rule."""

    __tablename__ = "payment_checks"
    __table_args__ = (
        CheckConstraint(f"decision IN {CHECK_DECISIONS}", name="decision"),
        CheckConstraint(f"reason IS NULL OR reason IN {REJECT_REASONS}", name="reason"),
        Index("ix_payment_checks_transaction_id", "transaction_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)  # the (first) photo
    photo_count: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    image_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # sha256 of the downloaded file
    transaction_id: Mapped[str | None] = mapped_column(String(64))
    amount_mmk: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16), server_default="pending", default="pending")
    reason: Mapped[str | None] = mapped_column(String(32))
    outbox_id: Mapped[int | None] = mapped_column(ForeignKey("outbox.id"))  # confirmation / reject / "one photo" reply
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class AutoRun(Base):
    """Auto mode's final decision for an incoming message (at most one auto reply each)."""

    __tablename__ = "auto_runs"
    __table_args__ = (CheckConstraint(f"status IN {AUTO_STATUSES}", name="status"),)

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(120))
    quick_action_id: Mapped[int | None] = mapped_column(ForeignKey("quick_actions.id"))
    created_at: Mapped[datetime] = created_at_column()


class OrderEvent(Base):
    """A delivery-status change of a paid order (or a cancel), with what is needed to undo it
    within 60 s. created_by None = done by the system (auto-delivered, auto-cancel).
    kind "contact" (docs/SPEC-v4.8-change-info.md): the address / phones changed; previous = old
    values, the order holds the new ones. kind "address_checked": an admin checked a change made
    after payment."""

    __tablename__ = "order_events"
    __table_args__ = (CheckConstraint(f"kind IN {EVENT_KINDS}", name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    previous: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # fields to restore on undo
    kind: Mapped[str] = mapped_column(String(16), server_default="status", default="status")
    outbox_id: Mapped[int | None] = mapped_column(ForeignKey("outbox.id"))  # message it queued, if any
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChoicePrompt(Base):
    """"Which one?" (docs/SPEC-v4.md 4.3): we sent a numbered list of the customer's earlier
    items; their next message "1", "၁", "1 နဲ့ 2", "အကုန်" (within 24 h) picks from options."""

    __tablename__ = "choice_prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))  # the "ဟိုနေ့ကဟာ" message
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # [{product_id, size_ml, is_full_bottle}]
    quantity: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
