"""Import every model so Base.metadata is complete (Alembic autogenerate relies on it)."""
from app.models.catalog import Product, ProductAlias
from app.models.customers import Customer
from app.models.health import ServiceHeartbeat
from app.models.messages import Message, MessageReview
from app.models.parsing import ParseResult
from app.models.users import User

__all__ = ["Customer", "Message", "MessageReview", "ParseResult", "Product", "ProductAlias", "ServiceHeartbeat", "User"]
