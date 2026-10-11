"""Import every model so Base.metadata is complete (Alembic autogenerate relies on it)."""
from app.models.audit import AuditLog
from app.models.catalog import Product, ProductAlias
from app.models.customers import Customer
from app.models.health import ServiceHeartbeat
from app.models.messages import Message, MessageReview
from app.models.outbox import MediaDownload, Outbox
from app.models.parsing import ParseResult
from app.models.pricing import ProductPrice
from app.models.settings import PaymentMethod, ReplyTemplate
from app.models.users import User

__all__ = ["AuditLog", "Customer", "MediaDownload", "Message", "MessageReview", "Outbox", "ParseResult", "PaymentMethod", "Product",
           "ProductAlias", "ProductPrice", "ReplyTemplate", "ServiceHeartbeat", "User"]
