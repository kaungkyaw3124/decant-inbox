from datetime import datetime

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Integer, String, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

ROLES = ("owner", "staff")
LANGUAGES = ("my", "en")  # Burmese / English dashboard (docs/SPEC-v4.md 4.5)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="role"),
                      CheckConstraint(f"language IN {LANGUAGES}", name="language"))

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    disabled: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)  # can't log in
    language: Mapped[str] = mapped_column(String(2), server_default="en", default="en")
    created_at: Mapped[datetime] = created_at_column()
    # docs/SPEC-v5.0-go-live-pack.md G3: 2-step login (NULL = off), recovery code hashes, "log out everywhere"
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_recovery: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]", default=list)
    session_epoch: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    known_devices: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]", default=list)

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"
