"""docs/SPEC-v5.1-inventory.md: stock in ml (own tables, CLAUDE.md principle 6; v1 tables unchanged)."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

BOTTLE_STATUSES = ("sealed", "open", "empty")
MOVE_KINDS = ("purchase", "decant", "adjust", "return", "waste")


class Bottle(Base):
    """A full perfume bottle we bought; decants are poured from the open one."""

    __tablename__ = "bottles"
    __table_args__ = (CheckConstraint(f"status IN {BOTTLE_STATUSES}", name="status"),
                      CheckConstraint("remaining_ml >= 0", name="remaining_not_negative"))

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    size_ml: Mapped[int] = mapped_column(Integer)
    remaining_ml: Mapped[float] = mapped_column(Numeric(7, 2))
    cost_mmk: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()


class Vial(Base):
    """Empty decant vials / atomizers of one size."""

    __tablename__ = "vials"
    __table_args__ = (CheckConstraint("count >= 0", name="count_not_negative"),)

    size_ml: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    cost_each_mmk: Mapped[int | None] = mapped_column(Integer)


class StockMove(Base):
    """Every change of stock, with who and why (the history)."""

    __tablename__ = "stock_moves"
    __table_args__ = (CheckConstraint(f"kind IN {MOVE_KINDS}", name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)
    bottle_id: Mapped[int | None] = mapped_column(ForeignKey("bottles.id"))
    vial_size: Mapped[int | None] = mapped_column(Integer)
    ml_change: Mapped[float] = mapped_column(Numeric(7, 2), default=0)
    count_change: Mapped[int] = mapped_column(Integer, default=0)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()
