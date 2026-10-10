from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

REVIEW_STATUSES = ("new", "done", "ignored")


class Message(Base):
    """Raw messages are kept forever; parsing results live in parse_results."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("channel", "external_chat_id", "external_message_id"),  # idempotent imports
        Index("ix_messages_received_at", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    external_chat_id: Mapped[str] = mapped_column(String(64))
    external_message_id: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class MessageReview(Base):
    """Current review state of a message: one row per message, updated in place."""

    __tablename__ = "message_reviews"
    __table_args__ = (
        CheckConstraint(f"status IN {REVIEW_STATUSES}", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), server_default="new", default="new")
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
