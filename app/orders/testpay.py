"""Test payment code (docs/SPEC-v4.14-test-payment-code.md).

The owner's test account (customers.is_tester) types the secret .env TEST_PAY_CODE instead of sending a
payment screenshot: the order gets a TEST payment check (no money) and everything after it runs like a real
order, with its own Order IDs T1, T2, ... From any other chat the code is an ordinary message; we only
write "test_code.non_tester" so the owner can change the code. The code itself is never stored outside the
message, logged, sent to the AI or shown (app/web/deps.py hides it in every page).
"""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting, AuditLog, Customer, Message, MessageReview, Order, Outbox, PaymentCheck, User

AUTO_SETTING = "test_pay_auto_approve"
AUTO_AFTER = timedelta(seconds=5)
CLEARED = "test order cleared"
LOOKBACK = timedelta(hours=1)  # older messages (history imports) are never treated as the code
SEEN = ("test_code.used", "test_code.no_order", "test_code.non_tester", "test_code.too_early")  # one of these per code message
LABEL = "🧪 test payment code"
VALID = re.compile(r"[A-Za-z0-9]{8,}")
_DIGITS = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")


def code() -> str | None:
    """None = the feature is off (empty, missing, or not 8+ letters/digits)."""
    secret = get_settings().test_pay_code
    value = secret.get_secret_value().strip() if secret else ""
    return value if VALID.fullmatch(value) else None


def is_code(text: str | None) -> bool:
    """Exact match after trim, case-sensitive, Burmese digits as 0-9."""
    secret = code()
    return secret is not None and (text or "").strip().translate(_DIGITS) == secret


def hide(text: str) -> str:
    """For pages and AI prompts: the code (in any case) becomes a label."""
    secret, plain = code(), (text or "").translate(_DIGITS)
    if secret is None or secret.lower() not in plain.lower():
        return text
    return re.sub(re.escape(secret), LABEL, plain, flags=re.IGNORECASE)


def order_label(order: Order) -> str:
    """The Order ID as shown and sent, after "#": "1001" or "T1"."""
    return f"T{order.order_no}" if order.is_test else str(order.order_no)


# ---------- the worker ----------

def _waiting_order(session: Session, customer_id: int) -> Order | None:
    return session.scalar(select(Order).where(
        Order.customer_id == customer_id, Order.status == "waiting_payment", Order.payment_info_sent_at.is_not(None),
        ~exists().where(PaymentCheck.order_id == Order.id, PaymentCheck.decision.in_(("pending", "several")))))


def scan(session: Session, now: datetime | None = None) -> int:
    """New code messages -> a test check (tester), a Needs you note (tester, no order waiting) or the
    non-tester warning. Returns how many code messages were handled."""
    if code() is None:
        return 0
    now = now or datetime.now(UTC)
    seen = exists().where(AuditLog.action.in_(SEEN), AuditLog.details["message_id"].as_integer() == Message.id)
    rows = session.execute(select(Message, Customer).join(Customer, Customer.id == Message.customer_id).where(
        Message.direction == "in", Message.kind == "text", Message.received_at >= now - LOOKBACK, ~seen,
        ~exists().where(PaymentCheck.message_id == Message.id)).order_by(Message.received_at, Message.id)).all()
    done = 0
    # shortcut: compares the last hour's texts in Python every second, move the match into SQL if volume grows
    for message, customer in rows:
        if not is_code(message.raw_text):
            continue
        details = {"message_id": message.id, "customer_id": customer.id}
        if not customer.is_tester:
            session.add(AuditLog(user_id=None, action="test_code.non_tester", details=details))
            done += 1
            continue
        order = _waiting_order(session, customer.id)
        early = None if order is not None else _too_early(session, message, customer)
        if early is not None:
            order, action = early
        else:
            action = "test_code.used" if order is not None and message.received_at >= order.payment_info_sent_at \
                else "test_code.no_order"
        if action == "test_code.used":
            check = PaymentCheck(order_id=order.id, message_id=message.id, decision="pending", is_test=True)
            session.add(check)
            order.status, order.is_test = "photo_received", True
            session.flush()
            details |= {"check_id": check.id, "order_id": order.id}
        session.add(AuditLog(user_id=None, action=action, details=details))
        # handled like a screenshot: no card, no AI, no holding reply, nothing learned
        session.execute(insert(MessageReview).values(message_id=message.id, status="done", reviewed_at=now)
                        .on_conflict_do_update(index_elements=["message_id"], set_={"status": "done"}))
        done += 1
    session.flush()
    return done


def _too_early(session: Session, message: Message, customer: Customer) -> tuple[Order, str] | None:
    """docs/SPEC-v4.16 Q4: the code before payment info. A cart that only waits for "yes" (items, phone,
    valid address): yes + payment info + the test check in one go; otherwise tell the tester why nothing
    happened. None = no cart / confirmed order (the 4.14 "no order" note)."""
    from app.orders import cart  # late import: cart -> address -> parser
    from app.replies import templates as replies

    order = cart.open_cart(session, customer.id)
    if order is None or order.status not in ("cart", "confirmed"):
        return None
    texts = replies.load(session)
    ready = session.begin_nested()
    if order.status == "cart":
        cart.confirm(session, order)
    cart.use_saved_contact(session, order, customer)
    if not cart.payment_problems(session, order, customer):
        body = cart.payment_text(session, order, texts)
        cart.payment_info_sent(session, order)
        ready.commit()
        _reply(session, message, body, "payment_info")
        return order, "test_code.used"
    ready.rollback()  # not ready: the order stays as it was
    _reply(session, message, texts["test_code_too_early"], "custom")
    return order, "test_code.too_early"


def _reply(session: Session, message: Message, body: str, kind: str) -> None:
    session.add(Outbox(customer_id=message.customer_id, text=body, reply_kind=kind, status="queued",
                       idempotency_key=f"test-code-{message.id}", created_by=None, send_after=datetime.now(UTC),
                       source_message_id=message.id))


def auto_approve(session: Session) -> bool:
    row = session.get(AppSetting, AUTO_SETTING)
    return bool(row and row.value.get("enabled"))


def set_auto_approve(session: Session, on: bool, user: User) -> None:
    stmt = insert(AppSetting).values(key=AUTO_SETTING, value={"enabled": on}, updated_by=user.id)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))
    session.add(AuditLog(user_id=user.id, action="test_code.auto_approve", details={"enabled": on}))


def run_auto_approve(session: Session, now: datetime | None = None) -> int:
    """Setting ON: test checks 5 s old are approved by the system. Real checks never."""
    from app.orders import payments  # late import: payments imports a lot
    from app.replies import templates as replies

    if not auto_approve(session):
        return 0
    now = now or datetime.now(UTC)
    approved = 0
    for check in session.scalars(select(PaymentCheck).where(
            PaymentCheck.is_test, PaymentCheck.decision == "pending", PaymentCheck.created_at <= now - AUTO_AFTER)):
        try:
            with session.begin_nested():
                payments.approve(session, check, payments.Form("", None, None), None, replies.load(session), True)
            approved += 1
        except payments.PaymentError:
            pass  # e.g. no valid address yet: stays on /payments for the owner
    return approved


def clear(session: Session, user: User) -> int:
    """Owner's "Clear test orders": cancels every test order not delivered (nothing is sent, nothing is
    deleted); cleared orders are hidden even with "Show test orders"."""
    from app.orders import delivery  # late import: delivery imports this module

    orders = session.scalars(select(Order).where(Order.is_test, Order.status.in_(delivery.CANCELLABLE))
                             .with_for_update()).all()
    for order in orders:
        delivery.cancel(session, order, user, {}, CLEARED, message=None)
    return len(orders)


def notes(session: Session, action: str, since: datetime) -> list[tuple[Customer, datetime]]:
    """Needs you: "test_code.non_tester" (⚠️ someone sent the test payment code) or "test_code.no_order"
    (🧪 test code but no order waiting for payment), newest first."""
    return [(session.get(Customer, row.details["customer_id"]), row.created_at) for row in session.scalars(
        select(AuditLog).where(AuditLog.action == action, AuditLog.created_at >= since).order_by(AuditLog.id.desc()))]
