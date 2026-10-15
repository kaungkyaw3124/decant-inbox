"""After payment (docs/SPEC-v3.md 6.1, 6.4): paid -> packed -> sent_out -> delivered, and
cancelling a whole order.

Every change is one admin tap, logged in order_events + audit_log, and can be undone for
60 s. A message it sends (Sent out, thank-you on Delivered, cancel) waits those 60 s in
the outbox, so Undo also takes the message back. Sent-out orders older than N days
(Settings) become delivered by themselves, without a message.
"""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting, AuditLog, Order, OrderEvent, Outbox, PaymentCheck, User
from app.models.orders import OPEN_STATUSES, SHIPPING_STATUSES
from app.orders import cart
from app.replies import compose
from app.replies import templates as replies
from app.replies.templates import render

UNDO_WINDOW = timedelta(seconds=60)
RULES_SETTING = "order_rules"
DEFAULT_RULES = {"reminder_hours": 12, "cancel_hours": 48, "auto_delivered_days": 5, "thank_you": False}
RULE_LIMITS = {"reminder_hours": (1, 168), "cancel_hours": (2, 336), "auto_delivered_days": (1, 60)}
# to-status -> statuses it can come from (packing can be skipped; delivered can be set early)
MOVES = {"packed": ("paid",), "sent_out": ("paid", "packed"), "delivered": ("paid", "packed", "sent_out")}
CANCELLABLE = OPEN_STATUSES + SHIPPING_STATUSES
_FIELDS = ("status", "packed_at", "sent_out_at", "delivered_at", "deli_name", "deli_phone", "deli_note",
           "closed_at", "cancel_note")


class OrderError(Exception):
    """Shown to the admin; nothing was changed."""


# ---------- settings ----------

def rules(session: Session) -> dict:
    row = session.get(AppSetting, RULES_SETTING)
    return {**DEFAULT_RULES, **(row.value if row else {})}


def set_rules(session: Session, values: dict, user: User | None) -> None:
    """ValueError if outside the allowed ranges."""
    for key, (low, high) in RULE_LIMITS.items():
        if not low <= values[key] <= high:
            raise ValueError(f"{key.replace('_', ' ')} must be {low}-{high}")
    if values["cancel_hours"] <= values["reminder_hours"]:
        raise ValueError("Cancel must come after the reminder")
    stmt = insert(AppSetting).values(key=RULES_SETTING, value=values, updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


# ---------- texts ----------

def deli_line(order: Order, texts: dict[str, str]) -> str:
    """"\\nDeli: name phone", only when a deli name or phone was given."""
    if not (order.deli_name or order.deli_phone):
        return ""
    line = render(texts["deli_line"], deli_name=order.deli_name or "", deli_phone=order.deli_phone or "")
    return "\n" + re.sub(r"[ \t]{2,}", " ", line).strip()


def local_date(value: datetime) -> str:
    from zoneinfo import ZoneInfo

    return value.astimezone(ZoneInfo(get_settings().timezone)).strftime("%d/%m/%Y")


def sent_out_text(order: Order, texts: dict[str, str]) -> str:
    return render(texts["order_sent_out"], order_no=str(order.order_no), deli_line=deli_line(order, texts))


def status_answer(order: Order, texts: dict[str, str]) -> str:
    """Reply to "when will it arrive?" for a paid / packed / sent-out order."""
    if order.status == "sent_out":
        return render(texts["delivery_sent"], order_no=str(order.order_no), sent_date=local_date(order.sent_out_at),
                      deli_line=deli_line(order, texts))
    return render(texts["delivery_preparing"], order_no=str(order.order_no))


def shipping_order(session: Session, customer_id: int) -> Order | None:
    """The customer's newest paid order that has not arrived yet."""
    return session.scalar(select(Order).where(Order.customer_id == customer_id, Order.status.in_(SHIPPING_STATUSES))
                          .order_by(Order.paid_at.desc().nulls_last(), Order.id.desc()).limit(1))


def has_payment_photo(session: Session, order: Order) -> bool:
    """A screenshot came for this order (money may be involved): never cancel it automatically."""
    return bool(session.scalar(select(PaymentCheck.id).where(
        PaymentCheck.order_id == order.id, PaymentCheck.decision != "not_payment").limit(1)))


# ---------- changes ----------

def _snapshot(order: Order) -> dict:
    return {f: (v.isoformat() if isinstance(v, datetime) else v) for f in _FIELDS for v in [getattr(order, f)]}


def queue(session: Session, order: Order, body: str, user: User | None, reply_kind: str, key: str,
          delay: timedelta = UNDO_WINDOW) -> Outbox:
    now = datetime.now(UTC)
    greet = compose.needs_greeting(session, order.customer_id, now)
    box = Outbox(customer_id=order.customer_id, text=compose.with_greeting(body, replies.load(session), greet),
                 reply_kind=reply_kind, status="queued", idempotency_key=f"{key}-{order.id}-{now.timestamp()}",
                 created_by=user.id if user else None, send_after=now + delay)
    session.add(box)
    session.flush()
    return box


def _event(session: Session, order: Order, before: dict, user: User | None, box: Outbox | None,
           action: str, **details) -> OrderEvent:
    event = OrderEvent(order_id=order.id, from_status=before["status"], to_status=order.status, previous=before,
                       outbox_id=box.id if box else None, created_by=user.id if user else None)
    session.add(event)
    session.flush()
    session.add(AuditLog(user_id=user.id if user else None, action=action, details={
        "actor": "admin" if user else "auto", "order_id": order.id, "order_no": order.order_no,
        "event_id": event.id, "from": before["status"], "to": order.status,
        "outbox_id": box.id if box else None, **details}))
    return event


def move(session: Session, order: Order, to: str, user: User | None, texts: dict[str, str],
         deli_name: str = "", deli_phone: str = "", deli_note: str = "", now: datetime | None = None) -> OrderEvent:
    """Packed / Sent out / Delivered. user None = the system (auto-delivered, no message)."""
    now = now or datetime.now(UTC)
    if to not in MOVES:
        raise OrderError("Unknown status.")
    if order.status not in MOVES[to]:
        raise OrderError(f"Order #{order.order_no} is {order.status.replace('_', ' ')}; it can't become "
                         f"{to.replace('_', ' ')}.")
    before = _snapshot(order)
    order.status, order.updated_at = to, now
    box = None
    if to == "packed":
        order.packed_at = now
    elif to == "sent_out":
        order.sent_out_at = now
        order.deli_name = deli_name.strip()[:64] or None
        order.deli_phone = deli_phone.strip()[:32] or None
        order.deli_note = deli_note.strip()[:500] or None
        box = queue(session, order, sent_out_text(order, texts), user, "delivery", "sent-out")
    else:
        order.delivered_at = now
        if user is not None and rules(session)["thank_you"]:
            box = queue(session, order, texts["order_delivered"], user, "delivery", "delivered")
    return _event(session, order, before, user, box, f"order.{to}")


def cancel(session: Session, order: Order, user: User | None, texts: dict[str, str], note: str = "",
           message: str | None = "order_cancelled", delay: timedelta = UNDO_WINDOW) -> OrderEvent:
    """Cancel the whole order (any time before delivered). message: template key to send, or None.
    A paid order's refund happens outside the system (note)."""
    if order.status not in CANCELLABLE:
        raise OrderError("This order can't be cancelled any more.")
    before = _snapshot(order)
    cart.cancel(session, order)
    order.cancel_note = note.strip()[:500] or None
    box = queue(session, order, texts[message], user, "cancel", "cancel", delay) if message else None
    return _event(session, order, before, user, box, "order.cancel", note=order.cancel_note)


def undo(session: Session, event: OrderEvent, user: User, now: datetime | None = None) -> Order:
    now = now or datetime.now(UTC)
    if event.undone_at is not None:
        raise OrderError("Already undone.")
    if now - event.created_at > UNDO_WINDOW:
        raise OrderError("Too late to undo (60 s).")
    order = session.scalar(select(Order).where(Order.id == event.order_id).with_for_update())
    if order.status != event.to_status:
        raise OrderError("The order changed again meanwhile.")
    if event.previous["status"] in OPEN_STATUSES and cart.open_cart(session, order.customer_id):
        raise OrderError("The customer has a new cart meanwhile; can't reopen this one.")
    if event.outbox_id:
        box = session.scalar(select(Outbox).where(Outbox.id == event.outbox_id).with_for_update())
        if box.status != "queued":
            raise OrderError("Too late to undo: the message has already been sent.")
        box.status = "cancelled"
    for field, value in event.previous.items():
        is_time = field.endswith("_at") and value
        setattr(order, field, datetime.fromisoformat(value) if is_time else value)
    order.updated_at = now
    event.undone_at = now
    session.add(AuditLog(user_id=user.id, action="order.undo", details={"event_id": event.id, "order_id": order.id}))
    return order


def undoable(session: Session, order_ids: list[int], now: datetime | None = None) -> dict[int, OrderEvent]:
    """The newest event per order that can still be undone (shown as an Undo button)."""
    now = now or datetime.now(UTC)
    if not order_ids:
        return {}
    rows = session.scalars(select(OrderEvent).where(
        OrderEvent.order_id.in_(order_ids), OrderEvent.undone_at.is_(None), OrderEvent.created_by.is_not(None),
        OrderEvent.created_at >= now - UNDO_WINDOW).order_by(OrderEvent.id))
    return {e.order_id: e for e in rows}


def auto_deliver(session: Session, now: datetime | None = None) -> int:
    """Sent out more than N days ago -> delivered (no message)."""
    now = now or datetime.now(UTC)
    days = rules(session)["auto_delivered_days"]
    orders = session.scalars(select(Order).where(
        Order.status == "sent_out", Order.sent_out_at <= now - timedelta(days=days)).with_for_update()).all()
    for order in orders:
        move(session, order, "delivered", None, {}, now=now)
    return len(orders)
