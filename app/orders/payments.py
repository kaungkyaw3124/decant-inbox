"""Payment check (docs/SPEC-orders.md "Payment check", Step 5).

- scan() (parser worker, DB only): a photo from a customer whose order is waiting for
  payment -> a pending payment check, order "photo_received". Several photos (same album,
  or more than one within 60 s) -> "several": nothing is downloaded or queued; the admin
  sends "one screenshot please" with one tap.
- The admin opens the card (the screenshot is downloaded then), types the transaction ID
  from their own KPay/AYA history and approves, rejects (3 reasons) or dismisses.
- Approve: reused transaction ID, reused image or amount != total -> warnings that need a
  second confirm. Then the order gets its Order ID (#1001, #1002, ...) and status paid,
  and the confirmation message is queued (10 s, Cancel in the chat).
Payment approval is never automatic, except a TEST check (docs/SPEC-v4.14-test-payment-code.md) with the
owner's "Auto-approve test payments" ON (app/orders/testpay.py).
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.ai import screens
from app.models import AuditLog, Customer, MediaDownload, Message, Order, Outbox, PaymentCheck, User
from app.models.outbox import UNDO_SECONDS
from app.orders import cart, testpay
from app.pricing import costs
from app.pricing.prices import format_mmk
from app.replies import compose
from app.replies import templates as replies
from app.replies.templates import render

SEVERAL_WITHIN = timedelta(seconds=60)
REASON_TEMPLATES = {"not_received": "reject_not_received", "wrong_screenshot": "reject_wrong_screenshot",
                    "wrong_amount": "reject_wrong_amount"}
REASON_LABELS = {"not_received": "Money not received", "wrong_screenshot": "Wrong screenshot",
                 "wrong_amount": "Amount too low (ask for the rest)"}


class PaymentError(Exception):
    """Shown to the admin; nothing was changed."""


# ---------- finding screenshots ----------

def scan(session: Session) -> int:
    """Turn new payment photos into checks. Returns how many checks were created/changed."""
    changed = 0
    orders = session.scalars(select(Order).where(Order.status.in_(("waiting_payment", "photo_received")),
                                                 Order.payment_info_sent_at.is_not(None))).all()
    for order in orders:
        checked = select(PaymentCheck.id).where(PaymentCheck.message_id == Message.id).exists()  # seen already
        photos = session.scalars(select(Message).where(
            Message.customer_id == order.customer_id, Message.direction == "in", Message.kind == "photo",
            Message.received_at >= order.payment_info_sent_at, ~checked).order_by(Message.received_at, Message.id)).all()
        for photo in photos:
            open_check = session.scalar(select(PaymentCheck).where(
                PaymentCheck.order_id == order.id, PaymentCheck.decision.in_(("pending", "several"))))
            first = session.get(Message, open_check.message_id) if open_check else None
            together = first is not None and (
                (photo.grouped_id and photo.grouped_id == first.grouped_id)
                or photo.received_at - first.received_at <= SEVERAL_WITHIN)
            if together:
                # a second photo with the first: ask for ONE screenshot instead
                open_check.decision, open_check.photo_count = "several", open_check.photo_count + 1
                session.add(PaymentCheck(order_id=order.id, message_id=photo.id, decision="not_payment",
                                         decided_at=datetime.now(UTC)))  # covered by the first one
                if order.status == "photo_received":
                    order.status = "waiting_payment"
            elif open_check is None:
                session.add(PaymentCheck(order_id=order.id, message_id=photo.id, decision="pending"))
                order.status = "photo_received"
            else:
                continue  # a later photo while one is still being checked: wait for that decision
            changed += 1
        session.flush()
    return changed


def to_check(session: Session) -> list[tuple[PaymentCheck, Order, Customer]]:
    return session.execute(
        select(PaymentCheck, Order, Customer).join(Order, Order.id == PaymentCheck.order_id)
        .join(Customer, Customer.id == Order.customer_id)
        .where(PaymentCheck.decision.in_(("pending", "several")), PaymentCheck.outbox_id.is_(None))
        .order_by(PaymentCheck.id)).all()


def request_screenshot(session: Session, check: PaymentCheck, user: User) -> None:
    """Opening the card downloads the screenshot (only then, and only one photo)."""
    if check.decision != "pending" or check.is_test:  # a test check has no screenshot
        return
    session.execute(text("INSERT INTO media_downloads (message_id, status, requested_by) VALUES (:m, 'queued', :u) "
                         "ON CONFLICT (message_id) DO UPDATE SET status = 'queued', error = NULL "
                         "WHERE media_downloads.status = 'failed'"), {"m": check.message_id, "u": user.id})


def screenshot(session: Session, check: PaymentCheck) -> MediaDownload | None:
    return session.get(MediaDownload, check.message_id)


# ---------- deciding ----------

@dataclass
class Form:
    transaction_id: str
    amount_mmk: int | None
    method: str | None


def warnings(session: Session, check: PaymentCheck, order: Order, form: Form) -> list[str]:
    """Reasons to look twice before approving (approving needs a second confirm)."""
    found = []
    reused = session.scalar(select(PaymentCheck).where(
        func.lower(PaymentCheck.transaction_id) == form.transaction_id.lower(), PaymentCheck.id != check.id,
        PaymentCheck.decision == "approved"))
    if reused:
        found.append(f"Transaction ID {form.transaction_id} was already used for order "
                     f"#{testpay.order_label(session.get(Order, reused.order_id))}.")
    shot = screenshot(session, check)
    if shot and shot.sha256:
        same = session.scalar(select(PaymentCheck.id).where(
            PaymentCheck.image_hash == shot.sha256, PaymentCheck.id != check.id,
            PaymentCheck.decision.in_(("approved", "rejected"))).limit(1))
        if same:
            found.append("This exact screenshot was sent before (another payment check).")
    total = cart.view(session, order).total
    if form.amount_mmk is not None and form.amount_mmk != total:
        found.append(f"Amount {format_mmk(form.amount_mmk)} ≠ order total {format_mmk(total)} ကျပ်.")
        found += total_change_lines(session, order)  # docs/SPEC-v4.10-interruptions.md
    # docs/SPEC-v4.12-address-payment-ai.md N3: what the screenshot reader found (only with ai_screenshot ON)
    found += [w.text for w in screens.warnings(session, check, order, total) if w.text not in found]
    return found


def total_change_lines(session: Session, order: Order) -> list[str]:
    """"Total changed at 02:41: 18,000 → 33,000 ကျပ်." for every change while waiting for payment."""
    from app.orders import delivery, steps  # late import: delivery imports this package's neighbours

    tz = delivery.local_zone()
    return [f"Total changed at {e.created_at.astimezone(tz).strftime('%H:%M')}: "
            f"{format_mmk(e.previous['total'])} → {format_mmk(e.previous['new_total'])} ကျပ်."
            for e in steps.total_changes(session, order.id)]


def _queue(session: Session, check: PaymentCheck, order: Order, body: str, user: User | None) -> None:
    now = datetime.now(UTC)
    greet = compose.needs_greeting(session, order.customer_id, now)
    body = compose.with_greeting(body, replies.load(session), greet)
    box = Outbox(customer_id=order.customer_id, text=body, reply_kind="payment", status="queued",
                 idempotency_key=f"payment-{check.id}-{now.timestamp()}", created_by=user.id if user else None,
                 send_after=now + timedelta(seconds=UNDO_SECONDS), source_message_id=check.message_id)
    session.add(box)
    session.flush()
    check.outbox_id = box.id


def confirmation_text(session: Session, order: Order, texts: dict[str, str]) -> str:
    """docs/SPEC-v4.12: always the validated address (full_text); approve() refuses without one."""
    if why := cart.address_problem(order):
        raise PaymentError(why)
    return render(texts["order_confirmed"], id=testpay.order_label(order),
                  items="\n".join(cart.item_lines(session, order, texts)),
                  total=format_mmk(cart.view(session, order).total),
                  phone=", ".join(order.phones or []), address=order.address or "")


def _decide(check: PaymentCheck, decision: str, user: User | None, form: Form | None = None,
            reason: str | None = None):
    check.decision, check.reason, check.decided_at = decision, reason, datetime.now(UTC)
    check.decided_by = user.id if user else None
    if form is not None:
        check.transaction_id, check.amount_mmk, check.method = form.transaction_id, form.amount_mmk, form.method


def approve(session: Session, check: PaymentCheck, form: Form, user: User | None, texts: dict[str, str],
            confirmed: bool = False) -> list[str]:
    """Returns warnings (nothing changed) unless confirmed or there are none. user None = the system
    (only for test checks, app/orders/testpay.py)."""
    order = session.scalar(select(Order).where(Order.id == check.order_id).with_for_update())
    if check.decision != "pending" or order.status != "photo_received":
        raise PaymentError("This payment check is already decided.")
    if why := cart.address_problem(order):  # docs/SPEC-v4.12 N2: never approve (= confirm) without a valid address
        raise PaymentError(why.replace("in the cart panel", "on this card"))
    if check.is_test:  # no money, no screenshot: nothing to compare
        form, found = Form(f"TEST-{check.id}", None, form.method), []
    else:
        if not form.transaction_id:
            raise PaymentError("The transaction ID is required (copy it from your KPay / AYA history).")
        shot = screenshot(session, check)
        if shot is None or shot.status != "done":
            raise PaymentError("Open the screenshot first (it is still loading).")
        found = warnings(session, check, order, form)
        if found and not confirmed:
            return found
        check.image_hash = shot.sha256
    _decide(check, "approved", user, form)
    order.order_no = session.scalar(text("SELECT nextval('test_order_no_seq')" if check.is_test
                                         else "SELECT nextval('order_no_seq')"))
    order.status, order.paid_at = "paid", datetime.now(UTC)
    costs.stamp(session, order)  # cost at the time of the sale (Step 8)
    _queue(session, check, order, confirmation_text(session, order, texts), user)
    session.add(AuditLog(user_id=user.id if user else None, action="payment.approve", details={
        "check_id": check.id, "order_id": order.id, "order_no": order.order_no, "warnings": found}))
    return []


def reject(session: Session, check: PaymentCheck, reason: str, form: Form, user: User, texts: dict[str, str]) -> None:
    order = session.scalar(select(Order).where(Order.id == check.order_id).with_for_update())
    if check.decision != "pending":
        raise PaymentError("This payment check is already decided.")
    if reason not in REASON_TEMPLATES:
        raise PaymentError("Choose a reason.")
    values = {}
    if reason == "wrong_amount":
        total = cart.view(session, order).total
        if form.amount_mmk is None or not 0 < form.amount_mmk < total:
            raise PaymentError("Type the amount received (less than the total) to ask for the rest.")
        values["remaining"] = format_mmk(total - form.amount_mmk)
    shot = screenshot(session, check)
    check.image_hash = shot.sha256 if shot else None
    _decide(check, "rejected", user, form, reason)
    order.status = "waiting_payment"
    _queue(session, check, order, render(texts[REASON_TEMPLATES[reason]], **values), user)
    session.add(AuditLog(user_id=user.id, action="payment.reject", details={"check_id": check.id, "reason": reason}))


def dismiss(session: Session, check: PaymentCheck, user: User) -> None:
    """Not a payment: nothing is sent."""
    order = session.scalar(select(Order).where(Order.id == check.order_id).with_for_update())
    if check.decision not in ("pending", "several"):
        raise PaymentError("This payment check is already decided.")
    _decide(check, "not_payment", user)
    if order.status == "photo_received":
        order.status = "waiting_payment"
    session.add(AuditLog(user_id=user.id, action="payment.not_payment", details={"check_id": check.id}))


def ask_one_screenshot(session: Session, check: PaymentCheck, user: User, texts: dict[str, str]) -> None:
    if check.decision != "several" or check.outbox_id:
        raise PaymentError("Nothing to ask.")
    order = session.get(Order, check.order_id)
    _queue(session, check, order, texts["several_photos"], user)
    _decide(check, "not_payment", user)  # the next single screenshot gets its own check
    session.add(AuditLog(user_id=user.id, action="payment.ask_one", details={"check_id": check.id}))


def count_open(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(PaymentCheck).where(
        PaymentCheck.decision.in_(("pending", "several")), PaymentCheck.outbox_id.is_(None)))
