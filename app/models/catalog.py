from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, created_at_column

ALIAS_SOURCES = ("seed", "learned")
PRODUCT_SOURCES = ("seed", "manual", "excel")  # manual = added in the dashboard, excel = added by a
# price-list import; the CSV seed leaves both alone


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("brand", "name"),
        CheckConstraint(f"source IN {PRODUCT_SOURCES}", name="source"),
        CheckConstraint("full_size_ml IS NULL OR full_size_ml > 0", name="full_size_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    source: Mapped[str] = mapped_column(String(16), server_default="seed", default="seed")
    full_size_ml: Mapped[int | None] = mapped_column(Integer)  # bottle size, from the price list
    created_at: Mapped[datetime] = created_at_column()


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        # Same alias may point at two products; the parser treats that as ambiguous.
        UniqueConstraint("product_id", "normalized_alias"),
        CheckConstraint(f"source IN {ALIAS_SOURCES}", name="source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    alias_text: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(16))
