from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

INTENTS = ("buy", "ask_stock", "ask_price", "other", "unknown")
PARSE_METHODS = ("rules", "ai", "human")


class ParseResult(Base):
    """Re-parsing adds a new row and flips is_current; history is kept."""

    __tablename__ = "parse_results"
    __table_args__ = (
        CheckConstraint(f"intent IN {INTENTS}", name="intent"),
        CheckConstraint(f"method IN {PARSE_METHODS}", name="method"),
        # At most one current result per message.
        Index(
            "uq_parse_results_current_per_message", "message_id",
            unique=True, postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    intent: Mapped[str] = mapped_column(String(16))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    size_ml: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(16))
    parser_version: Mapped[str] = mapped_column(String(32))
    is_current: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = created_at_column()
