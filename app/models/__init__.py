"""Import every model so Base.metadata is complete (Alembic autogenerate relies on it)."""
from app.models.audit import AuditLog
from app.models.catalog import Product, ProductAlias
from app.models.customers import Customer
from app.models.health import ServiceHeartbeat
from app.models.messages import Message, MessageReview
from app.models.orders import CustomerPhone, Order, OrderItem, QuickAction
from app.models.outbox import MediaDownload, Outbox
from app.models.parsing import ParseItem, ParseResult
from app.models.pricing import ProductPrice
from app.models.settings import PaymentMethod, ReplyTemplate
from app.models.users import User

__all__ = ["AuditLog", "Customer", "CustomerPhone", "MediaDownload", "Message", "MessageReview", "Order", "OrderItem", "Outbox", "ParseItem", "ParseResult", "PaymentMethod", "Product",
           "ProductAlias", "ProductPrice", "QuickAction", "ReplyTemplate", "ServiceHeartbeat", "User"]
