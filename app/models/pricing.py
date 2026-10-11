from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column


class ProductPrice(Base):
    """Price history, append-only. The current price of a (product, size) is its newest row;
    a newer row with price_mmk NULL means "no longer sold". size_ml NULL = full bottle
    (its size is products.full_size_ml). Rows are never edited, so we always know what a
    customer was quoted at a given time."""

    __tablename__ = "product_prices"
    __table_args__ = (
        CheckConstraint("is_full_bottle = (size_ml IS NULL)", name="full_bottle_size"),
        CheckConstraint("size_ml IS NULL OR size_ml > 0", name="size_positive"),
        CheckConstraint("price_mmk IS NULL OR price_mmk > 0", name="price_positive"),
        Index("ix_product_prices_lookup", "product_id", "size_ml", "effective_from"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    size_ml: Mapped[int | None] = mapped_column(Integer)
    is_full_bottle: Mapped[bool] = mapped_column(Boolean)
    price_mmk: Mapped[int | None] = mapped_column(Integer)
    in_stock: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
