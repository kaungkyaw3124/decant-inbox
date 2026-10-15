"""Import every model so Base.metadata is complete (Alembic autogenerate relies on it)."""
from app.models.audit import AuditLog
from app.models.catalog import Product, ProductAlias
from app.models.customers import Customer
from app.models.faq import FaqEntry
from app.models.health import ServiceHeartbeat
from app.models.messages import Message, MessageReview
from app.models.orders import (
    AutoRun, CustomerPhone, Order, OrderEvent, OrderItem, PaymentCheck, QuickAction, UnknownRequest,
)
from app.models.outbox import MediaDownload, Outbox
from app.models.parsing import ParseItem, ParseResult
from app.models.pricing import ProductCost, ProductPrice
from app.models.settings import AppSetting, PaymentMethod, ReplyTemplate
from app.models.users import User

__all__ = ["AppSetting", "AuditLog", "AutoRun", "Customer", "CustomerPhone", "FaqEntry", "MediaDownload", "Message", "MessageReview", "Order", "OrderEvent", "OrderItem", "Outbox", "ParseItem", "PaymentCheck", "ParseResult", "PaymentMethod", "Product",
           "ProductAlias", "ProductCost", "ProductPrice", "QuickAction", "ReplyTemplate", "ServiceHeartbeat", "UnknownRequest", "User"]
