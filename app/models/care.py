"""docs/SPEC-v5.2-customer-care.md: notes, tags, opt-outs, reorder messages, feedback after delivery
(own tables, CLAUDE.md principle 6; v1 tables unchanged)."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column


class CustomerNote(Base):
    __tablename__ = "customer_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()


class CustomerTag(Base):
    __tablename__ = "customer_tags"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    tag: Mapped[str] = mapped_column(String(24), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()


class CareOptOut(Base):
    """No reorder / feedback messages to this customer (they said stop, or an admin set it)."""

    __tablename__ = "care_optouts"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # customer | admin
    created_at: Mapped[datetime] = created_at_column()


class ReorderSent(Base):
    __tablename__ = "reorder_sent"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    outbox_id: Mapped[int] = mapped_column(ForeignKey("outbox.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()


class Feedback(Base):
    """One question per delivered order, and the customer's answer."""

    __tablename__ = "order_feedback"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    outbox_id: Mapped[int | None] = mapped_column(ForeignKey("outbox.id"))
    asked_at: Mapped[datetime] = created_at_column()
    answer: Mapped[str | None] = mapped_column(String(8))  # good | bad | other
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
