from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column
from app.core.config import BASE_DIR

OUTBOX_STATUSES = ("queued", "sending", "sent", "failed", "cancelled")
REPLY_KINDS = ("custom", "price", "cart", "ask_address", "ask_phone", "contact", "payment_info", "payment",
               "delivery", "reminder", "cancel", "faq", "greeting", "choice", "hold")
DOWNLOAD_STATUSES = ("queued", "done", "failed")
UNDO_SECONDS = 10
MAX_TEXT = 4096  # Telegram's limit for one message
MEDIA_DIR = BASE_DIR / "secrets" / "media"  # downloaded photos (dir 700, git-ignored)


class Outbox(Base):
    """Messages an admin chose to send. Only the listener (the one process that uses the
    Telegram session) sends them: queued -> sending -> sent | failed. A row stuck in
    "sending" (crash during the send) is never retried automatically, to avoid doubles."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint(f"status IN {OUTBOX_STATUSES}", name="status"),
        CheckConstraint(f"reply_kind IN {REPLY_KINDS}", name="reply_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    reply_kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="queued", default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)  # one row per Send tap
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    # One-tap quick replies wait UNDO_SECONDS here so the admin can undo; editor replies go now.
    send_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=func.now())
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), index=True)  # quick reply to
    previous_review_status: Mapped[str | None] = mapped_column(String(16))  # restored by Undo


class MediaDownload(Base):
    """Admin asked to see a photo; the listener downloads it into secrets/media/."""

    __tablename__ = "media_downloads"
    __table_args__ = (CheckConstraint(f"status IN {DOWNLOAD_STATUSES}", name="status"),)

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), server_default="queued", default="queued")
    path: Mapped[str | None] = mapped_column(String(255))  # file name inside secrets/media/
    sha256: Mapped[str | None] = mapped_column(String(64))  # same screenshot sent twice?
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = created_at_column()
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
