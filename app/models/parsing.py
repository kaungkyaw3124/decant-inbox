from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, false, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

INTENTS = ("buy", "ask_stock", "ask_price", "other", "unknown", "remove", "confirm", "done", "address",
           "ask_delivery", "cancel_order", "greeting", "previous_item")
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
    phone: Mapped[str | None] = mapped_column(String(20))  # Myanmar mobile found in the text
    # docs/SPEC-v4.md 4.2: learned_patterns this parse used (nicknames, intent phrases)
    learned_ids: Mapped[list[int]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), default=list)


class ParseItem(Base):
    """One product line of a parse result (rules-2: "good girl 5ml, swy 10ml"). The first
    item is also copied to parse_results.product_id/size_ml/quantity for v1 readers."""

    __tablename__ = "parse_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    parse_result_id: Mapped[int] = mapped_column(ForeignKey("parse_results.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    size_ml: Mapped[int | None] = mapped_column(Integer)  # None with is_full_bottle = full bottle
    is_full_bottle: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    quantity: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    unknown_text: Mapped[str | None] = mapped_column(String(255))  # named, but not in our catalog
    from_context: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    match: Mapped[str | None] = mapped_column(String(16))  # exact | fuzzy | inherited | ... (auto: exact only)
    # 4.1 partial match ("hawas for him" with alias "hawas"): the alias' product, a suggestion only
    candidate_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    name_text: Mapped[str | None] = mapped_column(String(255))  # the customer's words for the product (4.2)
