from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

PATTERN_KINDS = ("nickname", "intent_phrase", "not_stocked")
PATTERN_STATUSES = ("pending", "approved", "rejected")


class LearnedPattern(Base):
    """Something an admin taught with a teaching card (docs/SPEC-v4.md 4.2):
    nickname: text -> product · intent_phrase: text -> intent · not_stocked: text -> "we don't sell it".
    pending = used to understand, one-tap only; approved = like a seed alias / keyword (auto
    allowed); rejected = ignored by the parser. One live row per (kind, text)."""

    __tablename__ = "learned_patterns"
    __table_args__ = (
        CheckConstraint(f"kind IN {PATTERN_KINDS}", name="kind"),
        CheckConstraint(f"status IN {PATTERN_STATUSES}", name="status"),
        CheckConstraint("(kind = 'nickname') = (product_id IS NOT NULL)", name="nickname_product"),
        CheckConstraint("(kind = 'intent_phrase') = (intent IS NOT NULL)", name="phrase_intent"),
        Index("uq_learned_patterns_live_text", "kind", "normalized_text", unique=True,
              postgresql_where=text("status != 'rejected'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String(255))
    normalized_text: Mapped[str] = mapped_column(String(255))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    intent: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="pending", default="pending")
    taught_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    taught_at: Mapped[datetime] = created_at_column()
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None + approved_at = auto (N uses)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_uses: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    corrections: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    # docs/SPEC-v4.6-ai.md: the AI proposed it (shown as "AI + <user>", or "AI" in AUTO mode)
    via_ai: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
