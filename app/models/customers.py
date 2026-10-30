from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("channel", "external_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))  # "telegram" now, "viber" later
    external_user_id: Mapped[str] = mapped_column(String(64))  # string: works for any channel
    username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    ignored: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    created_at: Mapped[datetime] = created_at_column()
    # Contact details (v2). phone = first of customer_phones (kept in sync by app/orders/cart.py).
    phone: Mapped[str | None] = mapped_column(String(20))
    phone_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", use_alter=True))
    address: Mapped[str | None] = mapped_column(Text)  # set by an admin (Step 4)
    # docs/SPEC-v4.12-address-payment-ai.md: the split of the saved address; True = it failed the validator
    address_parts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    address_invalid: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    # Auto mode (Step 4c): never auto-reply to this customer (friends, family) / resumed
    # by the admin after an owner pause (replying by hand pauses auto for 2 h).
    auto_reply_off: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    auto_resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # docs/SPEC-v4.10-interruptions.md: when we last added a "resume line" (at most every 10 min)
    resume_line_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # docs/SPEC-v4.14-test-payment-code.md: the owner's own test account (the test payment code works here only)
    is_tester: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
