from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, false
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
