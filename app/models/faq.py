from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column


class FaqEntry(Base):
    """A common question and its answer (docs/SPEC-v3.md Step 7). keywords: comma separated,
    Burmese or English, as the admin typed them (matched on normalized text)."""

    __tablename__ = "faq_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    keywords: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    edited: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)  # False = seed text: "edit me"
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 default=func.now())
