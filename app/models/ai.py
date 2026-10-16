from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

# What became of a call (docs/SPEC-v4.6-ai.md):
#   shadow     result shown on the teaching card, waiting for an admin
#   accepted   admin pressed ✅ on the card without changing the AI's answers
#   corrected  admin changed at least one AI answer
#   auto       used automatically (AUTO mode)
#   rejected   our checker refused the result (treated as "AI unsure")
#   error      no usable answer (timeout, network, 401, 429, no credit)
#   cap        not called: daily call cap reached
#   budget     not called: monthly budget used up
#   unused     the message was handled another way (or there was nothing to suggest)
AI_DECISIONS = ("shadow", "accepted", "corrected", "auto", "rejected", "error", "cap", "budget", "unused")


class AICall(Base):
    """One AI request for one customer message (at most one per message). Raw text is never
    stored here: only token counts, cost, the checked JSON result and what happened to it."""

    __tablename__ = "ai_calls"
    __table_args__ = (CheckConstraint(f"decision IN {AI_DECISIONS}", name="decision"),
                      Index("ix_ai_calls_created_at", "created_at"))

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)
    model: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(8))  # shadow | auto (the AI mode when it was called)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 8), server_default="0", default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(255))  # error kind / checker reasons (no secrets, no text)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decision: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # docs/SPEC-v4.7-graduation.md: when a person accepted / corrected it, and whether the correction
    # changed the AI's product to a different one ("wrong product": blocks graduation, brakes AUTO)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wrong_product: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    created_at: Mapped[datetime] = created_at_column()
