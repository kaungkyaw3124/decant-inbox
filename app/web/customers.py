"""docs/SPEC-v5.2-customer-care.md: Customers (profiles, notes, tags), the reorder list, feedback settings."""
import csv
import io

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import care
from app.models import AuditLog, Customer, Order, User
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import get_db, templates
from app.web import paging
from app.web.inbox import flash, safe_back

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])


def _customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return customer


@router.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request, q: str = "", tag: str = "", city: str = "", sort: str = "spent",
                   db: Session = Depends(get_db)):
    page = paging.paginate(db, care.customer_query(q, tag, city, sort), request)  # docs/SPEC-v5.4 X2
    return templates.TemplateResponse(request, "customers.html", {
        "page": page, "rows": care.as_rows(db, page.items), "q": q, "tag": tag, "city": city, "sort": sort,
        "colours": care.TAG_COLOURS, "cfg": care.settings(db)})


@router.get("/customers/export.csv", dependencies=[Depends(owner_only)])
def export(db: Session = Depends(get_db)):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["name", "username", "city", "orders", "spent_mmk", "last_order", "tags"])
    for r in care.customer_rows(db):
        w.writerow([r["c"].display_name or "", r["c"].username or "", r["city"], r["orders"], r["spent"],
                    r["last"].date().isoformat() if r["last"] else "", " ".join(r["tags"])])
    return Response("﻿" + out.getvalue(), media_type="text/csv",  # BOM: Excel opens Burmese correctly
                    headers={"Content-Disposition": 'attachment; filename="customers.csv"'})


@router.get("/customers/reorder", response_class=HTMLResponse)
def reorder_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "reorder.html", {"rows": care.reorder_list(db), "cfg": care.settings(db)})


@router.post("/customers/care-settings", dependencies=[Depends(owner_only)])
def save_settings(request: Request, reorder_min_days: int = Form(25), reorder_max_days: int = Form(45),
                  feedback_on: str = Form(""), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not 1 <= reorder_min_days <= reorder_max_days <= 365:
        flash(request, "Days: from 1 to 365, the first not more than the second.")
        return RedirectResponse("/customers/reorder", status_code=303)
    care.save_settings(db, {"reorder_min_days": reorder_min_days, "reorder_max_days": reorder_max_days,
                            "feedback_on": feedback_on == "1"}, user)
    db.add(AuditLog(user_id=user.id, action="care.settings", details={"feedback_on": feedback_on == "1"}))
    db.commit()
    flash(request, "Saved.")
    return RedirectResponse("/customers/reorder", status_code=303)


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
def profile_page(request: Request, customer_id: int, db: Session = Depends(get_db)):
    customer = _customer(db, customer_id)
    page = paging.paginate(db, select(Order).where(Order.customer_id == customer_id, Order.order_no.is_not(None))
                           .order_by(Order.id.desc()), request, scalars=True)  # docs/SPEC-v5.4 X2
    return templates.TemplateResponse(request, "customer.html", {
        "c": customer, "profile": care.profile(db, customer), "page": page, "orders": page.items,
        "colours": care.TAG_COLOURS})


@router.post("/customers/{customer_id}/notes")
def add_note(request: Request, customer_id: int, text: str = Form(""), back: str = Form(""),
             db: Session = Depends(get_db), user: User = Depends(current_user)):
    _customer(db, customer_id)
    care.add_note(db, customer_id, text, user)
    db.commit()
    return RedirectResponse(safe_back(back, f"/customers/{customer_id}"), status_code=303)


@router.post("/customers/{customer_id}/tags")
def tag(request: Request, customer_id: int, tag: str = Form(...), on: str = Form("1"), back: str = Form(""),
        db: Session = Depends(get_db), user: User = Depends(current_user)):
    _customer(db, customer_id)
    care.set_tag(db, customer_id, tag, on == "1", user)
    db.add(AuditLog(user_id=user.id, action="care.tag", details={"customer_id": customer_id, "tag": tag[:24],
                                                                  "on": on == "1"}))
    db.commit()
    return RedirectResponse(safe_back(back, f"/customers/{customer_id}"), status_code=303)


@router.post("/customers/{customer_id}/optout")
def optout(request: Request, customer_id: int, on: str = Form("1"), db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    _customer(db, customer_id)
    care.set_opt_out(db, customer_id, on == "1")
    db.add(AuditLog(user_id=user.id, action="care.optout", details={"customer_id": customer_id, "on": on == "1"}))
    db.commit()
    return RedirectResponse(f"/customers/{customer_id}", status_code=303)


@router.post("/customers/{customer_id}/reorder")
def send_reorder(request: Request, customer_id: int, text: str = Form(""), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    try:
        care.send_reorder(db, _customer(db, customer_id), text, user)
    except care.CareError as exc:
        db.rollback()
        flash(request, str(exc))
        return RedirectResponse("/customers/reorder", status_code=303)
    db.commit()
    flash(request, "Queued: it goes out in a few seconds (Cancel in the chat).")
    return RedirectResponse("/customers/reorder", status_code=303)


@router.post("/orders/{order_id}/feedback-now", dependencies=[Depends(owner_only)])
def feedback_now(request: Request, order_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The owner's test button: ask this delivered order's feedback question now (once per order)."""
    n = care.ask_feedback(db, force_order=order_id)
    db.add(AuditLog(user_id=user.id, action="care.feedback_now", details={"order_id": order_id, "asked": n}))
    db.commit()
    flash(request, "Feedback question queued." if n else "Not asked: not delivered, asked before, or the customer "
                                                         "can't be messaged.")
    return RedirectResponse(f"/orders?tab=delivered#order-{order_id}", status_code=303)
