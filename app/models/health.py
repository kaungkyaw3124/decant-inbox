from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class ServiceHeartbeat(Base):
    """Each long-running service writes its last-alive time here; the health page reads it."""

    __tablename__ = "service_heartbeats"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)  # listener | parser
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[str | None] = mapped_column(String(255))  # counts/ids only, never text
