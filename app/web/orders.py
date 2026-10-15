"""Orders after payment (docs/SPEC-v3.md 6.1, 6.2, 6.4, 6.5): to pack / to send / sent /
delivered, one-tap status buttons with 60 s Undo, cancel, payment reminder; the "wanted
but not stocked" report; clearing "Needs you" rows."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Order, OrderEvent, User
from app.models.orders import PAID_STATUSES
from app.orders import cart, delivery, followups, reports
from app.replies import templates as replies
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash, safe_back

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])
TABS = {  # tab -> (label, statuses, oldest first?)
    "to_pack": ("📦 To pack", ("paid",), True),
    "to_send": ("🚚 To send", ("packed",), True),
    "sent": ("Sent", ("sent_out",), False),
    "delivered": ("✅ Delivered", ("delivered",), False),
    "all": ("All", PAID_STATUSES + ("cancelled",), False),
}
STATUS_LABELS = {"paid": "📦 to pack", "packed": "🚚 to send", "sent_out": "sent out", "delivered": "✅ delivered",
                 "cancelled": "cancelled", "photo_received": "📷 payment photo", "waiting_payment": "💳 waiting payment",
                 "cart": "🛒 cart", "confirmed": "✅ confirmed", "abandoned": "abandoned"}
LIST_SIZE = 100


def _order(db: Session, order_id: int, lock: bool = True) -> Order:
    query = select(Order).where(Order.id == order_id)
    order = db.scalar(query.with_for_update() if lock else query)
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


@router.get("/orders", response_class=HTMLResponse)
def orders_page(request: Request, tab: str = "to_pack", db: Session = Depends(get_db)):
    tab = tab if tab in TABS else "to_pack"
    label, statuses, oldest_first = TABS[tab]
    query = select(Order, Customer).join(Customer, Customer.id == Order.customer_id).where(
        Order.status.in_(statuses), Order.order_no.is_not(None))
    order_by = Order.paid_at.asc() if oldest_first else Order.paid_at.desc()
    rows = db.execute(query.order_by(order_by, Order.id).limit(LIST_SIZE)).all()
    counts = {key: len(db.scalars(select(Order.id).where(Order.status.in_(st), Order.order_no.is_not(None))).all())
              for key, (_, st, _) in TABS.items() if key in ("to_pack", "to_send", "sent")}
    return templates.TemplateResponse(request, "orders.html", {
        "tab": tab, "tabs": TABS, "counts": counts, "status_labels": STATUS_LABELS,
        "rows": [(o, c, cart.view(db, o)) for o, c in rows], "item_name": cart.item_name,
        "undo": delivery.undoable(db, [o.id for o, _ in rows]), "now": datetime.now(UTC)})


def _back(request: Request, back: str, order: Order) -> RedirectResponse:
    return RedirectResponse(safe_back(back, "/orders") + f"#order-{order.id}", status_code=303)


@router.post("/orders/{order_id}/status")
def set_status(request: Request, order_id: int, to: str = Form(...), deli_name: str = Form(""),
               deli_phone: str = Form(""), deli_note: str = Form(""), back: str = Form("/orders"),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = _order(db, order_id)
    try:
        event = delivery.move(db, order, to, user, replies.load(db), deli_name, deli_phone, deli_note)
        db.commit()
    except delivery.OrderError as exc:
        db.rollback()
        flash(request, str(exc))
        return _back(request, back, order)
    done = {"packed": "📦 Packed", "sent_out": "🚚 Sent out", "delivered": "✅ Delivered"}[to]
    flash(request, f"Order #{order.order_no}: {done}." + (" The customer gets the message in 60 s (Undo to stop it)."
                                                          if event.outbox_id else " Undo for 60 s."))
    return _back(request, back, order)


@router.post("/orders/{order_id}/cancel")
def cancel_order(request: Request, order_id: int, note: str = Form(""), message: str = Form("order_cancelled"),
                 back: str = Form("/orders"), db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = _order(db, order_id)
    template = message if message in ("order_cancelled", "order_auto_cancelled") else None
    try:
        delivery.cancel(db, order, user, replies.load(db), note, template)
        db.commit()
    except delivery.OrderError as exc:
        db.rollback()
        flash(request, str(exc))
        return _back(request, back, order)
    flash(request, f"Order{f' #{order.order_no}' if order.order_no else ''} cancelled"
                   + (" (message in 60 s; Undo to stop it)." if template else ". Nothing sent.")
                   + (" Refund outside the system." if order.paid_at else ""))
    return _back(request, back, order)


@router.post("/orders/{order_id}/remind")
def remind(request: Request, order_id: int, back: str = Form("/"), db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    order = _order(db, order_id)
    if order.status != "waiting_payment":
        raise HTTPException(409, "Not waiting for payment")
    try:
        followups.send_reminder(db, order, user, replies.load(db), datetime.now(UTC))
        db.commit()
    except delivery.OrderError as exc:
        db.rollback()
        flash(request, str(exc))
        return RedirectResponse(safe_back(back, "/"), status_code=303)
    flash(request, "Payment reminder queued (60 s; Cancel in the chat).")
    return RedirectResponse(safe_back(back, "/"), status_code=303)


@router.post("/orders/events/{event_id}/undo")
def undo(request: Request, event_id: int, back: str = Form("/orders"), db: Session = Depends(get_db),
         user: User = Depends(current_user)):
    event = db.get(OrderEvent, event_id)
    if event is None:
        raise HTTPException(404, "Not found")
    try:
        order = delivery.undo(db, event, user)
        db.commit()
        flash(request, f"Undone: order is {order.status.replace('_', ' ')} again.")
    except delivery.OrderError as exc:
        db.rollback()
        flash(request, str(exc))
    return RedirectResponse(safe_back(back, "/orders") + f"#order-{event.order_id}", status_code=303)


@router.post("/needs-you/clear")
async def clear(request: Request, status: str = Form("done"), back: str = Form("/"),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Mark the listed unanswered messages done / ignored (clears them from Needs you)."""
    form = await request.form()
    ids = [int(v) for v in form.getlist("message_id") if str(v).isdigit()]
    if status not in ("done", "ignored") or not ids:
        raise HTTPException(400, "Nothing to clear")
    followups.clear(db, ids, status, user)
    db.commit()
    flash(request, f"Marked {status}.")
    return RedirectResponse(safe_back(back, "/"), status_code=303)


@router.get("/reports/wanted", response_class=HTMLResponse)
def wanted(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "wanted.html", {"rows": reports.wanted(db)})
