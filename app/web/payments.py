"""Payments to check: the screenshot card with Approve / Reject / Not a payment."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Order, PaymentCheck, PaymentMethod, User
from app.orders import cart, payments
from app.replies import templates as replies
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
    return templates.TemplateResponse(request, "payment.html", {
        "check": check, "order": order, "c": db.get(Customer, order.customer_id), "cart": view,
        "shot": payments.screenshot(db, check), "item_size": cart.item_size,
        "methods": db.scalars(select(PaymentMethod).where(PaymentMethod.active).order_by(PaymentMethod.sort_order)).all(),
        "form": form or payments.Form(check.transaction_id or "", check.amount_mmk or view.total, check.method),
        "warnings": found or [], "error": error, "reasons": payments.REASON_LABELS,
    }, status_code=status_code)


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
    return templates.TemplateResponse(request, "_payment_shot.html", {"check": check,
                                                                      "shot": payments.screenshot(db, check)})


@router.post("/{check_id}/approve")
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
    flash(request, f"Approved: Order #{order.order_no}. The confirmation goes out in a few seconds (Cancel in the chat).")
    return RedirectResponse(f"/chats/{order.customer_id}#bottom", status_code=303)


@router.post("/{check_id}/reject")
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


@router.post("/{check_id}/not-payment")
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


@router.post("/{check_id}/ask-one")
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
