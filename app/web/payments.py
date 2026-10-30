"""Payments to check: the screenshot card with Approve / Reject / Not a payment."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import screens
from app.models import AuditLog, Customer, Order, PaymentCheck, PaymentMethod, User
from app.orders import address as address_rules
from app.orders import cart, payments, testpay
from app.replies import templates as replies
from app.web import staff
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(prefix="/payments", dependencies=[Depends(current_user), Depends(verify_csrf)])


def _check(db: Session, check_id: int) -> PaymentCheck:
    check = db.get(PaymentCheck, check_id)
    if check is None:
        raise HTTPException(404, "Payment check not found")
    return check


def _amount(value: str) -> int | None:
    digits = "".join(c for c in value.translate(str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")) if c.isdigit())
    return int(digits) if digits and int(digits) <= 100_000_000 else None


def _form(transaction_id: str, amount: str, method: str) -> payments.Form:
    return payments.Form(transaction_id.strip()[:64], _amount(amount), method.strip()[:64] or None)


def _card(request: Request, db: Session, check: PaymentCheck, form: payments.Form | None = None,
          found: list[str] | None = None, error: str | None = None, status_code: int = 200):
    order = db.get(Order, check.order_id)
    view = cart.view(db, order)
    methods = db.scalars(select(PaymentMethod).where(PaymentMethod.active).order_by(PaymentMethod.sort_order)).all()
    reading = screens.reading_of(check)  # docs/SPEC-v4.12 N3: pre-fill from the screenshot
    if form is None and reading is not None and reading.is_payment_receipt and check.transaction_id is None:
        form = payments.Form(reading.transaction_no or "", reading.amount or view.total,
                             screens.method_for(reading, methods))
    return templates.TemplateResponse(request, "payment.html", {
        "check": check, "order": order, "c": db.get(Customer, order.customer_id), "cart": view,
        "shot": payments.screenshot(db, check), "item_size": cart.item_size, "methods": methods,
        **reading_context(db, check, order, view.total),
        "form": form or payments.Form(check.transaction_id or "", check.amount_mmk or view.total, check.method),
        "warnings": found or [], "error": error, "reasons": payments.REASON_LABELS,
        "total_changes": payments.total_change_lines(db, order),  # docs/SPEC-v4.10-interruptions.md
        "address_problem": cart.address_problem(order),  # docs/SPEC-v4.12 N2
        "may_decide": staff.may_decide_payments(db, db.get(User, request.session["user_id"])),
    }, status_code=status_code)


def reading_context(db: Session, check: PaymentCheck, order: Order, total: int) -> dict:
    """The screenshot reader on the card: its reading, its warnings, and whether it is still working."""
    reading = screens.reading_of(check)
    waiting = check.ai_status is None and check.decision == "pending" and screens.enabled(db)
    return {"reading": reading, "ai_warnings": screens.warnings(db, check, order, total), "ai_waiting": waiting,
            "ai_failed": check.ai_status in ("error", "skipped")}


@router.get("", response_class=HTMLResponse)
def payment_list(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "payments.html", {"rows": payments.to_check(db)})


@router.get("/{check_id}", response_class=HTMLResponse)
def card(request: Request, check_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check = _check(db, check_id)
    payments.request_screenshot(db, check, user)  # downloaded only now, when the admin opens it
    db.commit()
    return _card(request, db, check)


@router.get("/{check_id}/shot", response_class=HTMLResponse)
def shot(request: Request, check_id: int, db: Session = Depends(get_db)):
    check = _check(db, check_id)
    order = db.get(Order, check.order_id)
    return templates.TemplateResponse(request, "_payment_shot.html", {
        "check": check, "shot": payments.screenshot(db, check),
        **reading_context(db, check, order, cart.view(db, order).total)})


@router.post("/{check_id}/approve", dependencies=[Depends(staff.payment_decider)])
def approve(request: Request, check_id: int, transaction_id: str = Form(""), amount: str = Form(""),
            method: str = Form(""), confirmed: str = Form(""), db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    check = _check(db, check_id)
    form = _form(transaction_id, amount, method)
    try:
        found = payments.approve(db, check, form, user, replies.load(db), confirmed == "1")
    except payments.PaymentError as exc:
        db.rollback()
        return _card(request, db, check, form, error=str(exc), status_code=400)
    if found:
        db.rollback()
        return _card(request, db, check, form, found)
    db.commit()
    order = db.get(Order, check.order_id)
    flash(request, f"Approved: Order #{testpay.order_label(order)}. The confirmation goes out in a few seconds (Cancel in the chat).")
    return RedirectResponse(f"/chats/{order.customer_id}#bottom", status_code=303)


@router.post("/{check_id}/address")
def fix_address(request: Request, check_id: int, address: str = Form(""), db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    """docs/SPEC-v4.12-address-payment-ai.md N2: fix a missing / invalid address before approving (same
    validator); saved on the order and the customer."""
    check = _check(db, check_id)
    order = db.get(Order, check.order_id)
    if order.order_no is not None:
        raise HTTPException(409, "A paid order is changed with “Edit locked order” (owner).")
    found = address_rules.admin_check(address)
    if not found.valid:
        return _card(request, db, check, error="Not saved: " + found.why, status_code=400)
    cart.set_address(db, order, db.get(Customer, order.customer_id), found)
    db.add(AuditLog(user_id=user.id, action="payment.address", details={"check_id": check.id, "order_id": order.id}))
    db.commit()
    flash(request, "Address saved (also for next time).")
    return RedirectResponse(f"/payments/{check.id}", status_code=303)


@router.post("/{check_id}/reject", dependencies=[Depends(staff.payment_decider)])
def reject(request: Request, check_id: int, reason: str = Form(""), transaction_id: str = Form(""),
           amount: str = Form(""), method: str = Form(""), db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    check = _check(db, check_id)
    form = _form(transaction_id, amount, method)
    try:
        payments.reject(db, check, reason, form, user, replies.load(db))
    except payments.PaymentError as exc:
        db.rollback()
        return _card(request, db, check, form, error=str(exc), status_code=400)
    db.commit()
    flash(request, "Rejected: the customer is told why; the order waits for payment again.")
    return RedirectResponse(f"/chats/{db.get(Order, check.order_id).customer_id}#bottom", status_code=303)


@router.post("/{check_id}/not-payment", dependencies=[Depends(staff.payment_decider)])
def not_payment(request: Request, check_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check = _check(db, check_id)
    try:
        payments.dismiss(db, check, user)
    except payments.PaymentError as exc:
        db.rollback()
        return _card(request, db, check, error=str(exc), status_code=400)
    db.commit()
    flash(request, "Dismissed: not a payment (nothing sent).")
    return RedirectResponse("/payments", status_code=303)


@router.post("/{check_id}/ask-one", dependencies=[Depends(staff.payment_decider)])
def ask_one(request: Request, check_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check = _check(db, check_id)
    try:
        payments.ask_one_screenshot(db, check, user, replies.load(db))
    except payments.PaymentError as exc:
        db.rollback()
        return _card(request, db, check, error=str(exc), status_code=400)
    db.commit()
    flash(request, "Asked for one screenshot.")
    return RedirectResponse(f"/chats/{db.get(Order, check.order_id).customer_id}#bottom", status_code=303)
