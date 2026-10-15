from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, String, false
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

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"
