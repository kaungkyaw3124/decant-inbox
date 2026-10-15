"""Settings: payment methods and reply templates. Every change goes to audit_log."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AuditLog, PaymentMethod, ReplyTemplate, User
from app.orders import auto, delivery
from app.replies import templates as replies
from app.web.auth import current_user, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(prefix="/settings", dependencies=[Depends(current_user), Depends(verify_csrf)])


def _page(request: Request, db: Session, errors: dict[str, str] | None = None,
          drafts: dict[str, str] | None = None, status_code: int = 200):
    texts = replies.load(db)
    customized = set(db.scalars(select(ReplyTemplate.key)))
    rows = []
    for t in replies.TEMPLATES:
        try:
            example = replies.render(texts[t.key], **t.example)
        except (KeyError, ValueError, IndexError):
            example = ""
        rows.append({"def": t, "text": (drafts or {}).get(t.key, texts[t.key]), "example": example,
                     "customized": t.key in customized, "error": (errors or {}).get(t.key)})
    methods = db.scalars(select(PaymentMethod).order_by(PaymentMethod.sort_order, PaymentMethod.id)).all()
    return templates.TemplateResponse(request, "settings.html", {
        "methods": methods, "templates": rows, "speed": auto.speed(db), "speed_limits": auto.SPEED_LIMITS,
        "speed_error": (errors or {}).get("speed"), "order_rules": delivery.rules(db),
        "rule_limits": delivery.RULE_LIMITS, "rules_error": (errors or {}).get("rules")}, status_code=status_code)


def _method_fields(name: str, account_number: str, account_name: str) -> dict[str, str]:
    fields = {"name": name.strip(), "account_number": account_number.strip(), "account_name": account_name.strip()}
    if not all(fields.values()):
        raise HTTPException(400, "Name, account number and account name are all required.")
    if len(fields["name"]) > 64 or len(fields["account_number"]) > 64 or len(fields["account_name"]) > 128:
        raise HTTPException(400, "Too long.")
    return fields


def _log(db: Session, user: User, action: str, **details) -> None:
    db.add(AuditLog(user_id=user.id, action=action, details=details))


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, db)


@router.post("/payment-methods")
def add_method(request: Request, name: str = Form(...), account_number: str = Form(...),
               account_name: str = Form(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    fields = _method_fields(name, account_number, account_name)
    last = db.scalar(select(PaymentMethod.sort_order).order_by(PaymentMethod.sort_order.desc()).limit(1))
    method = PaymentMethod(**fields, active=True, sort_order=(last or 0) + 1)
    db.add(method)
    db.flush()
    _log(db, user, "payment_method.add", id=method.id, **fields)
    db.commit()
    flash(request, f"{method.name} added.")
    return RedirectResponse("/settings#payment-methods", status_code=303)


@router.post("/payment-methods/{method_id}")
def update_method(request: Request, method_id: int, name: str = Form(...), account_number: str = Form(...),
                  account_name: str = Form(...), active: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    method = db.get(PaymentMethod, method_id)
    if method is None:
        raise HTTPException(404, "Payment method not found")
    fields = {**_method_fields(name, account_number, account_name), "active": active == "1"}
    for key, value in fields.items():
        setattr(method, key, value)
    _log(db, user, "payment_method.update", id=method_id, **fields)
    db.commit()
    flash(request, f"{method.name} saved.")
    return RedirectResponse("/settings#payment-methods", status_code=303)


@router.post("/payment-methods/{method_id}/delete")
def delete_method(request: Request, method_id: int, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    method = db.get(PaymentMethod, method_id)
    if method is None:
        raise HTTPException(404, "Payment method not found")
    _log(db, user, "payment_method.delete", id=method_id, name=method.name,
         account_number=method.account_number, account_name=method.account_name)
    db.delete(method)
    db.commit()
    flash(request, "Payment method deleted.")
    return RedirectResponse("/settings#payment-methods", status_code=303)


@router.post("/templates/{key}")
def save_template(request: Request, key: str, text: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    if key not in replies.BY_KEY:
        raise HTTPException(404, "Unknown template")
    try:
        text = replies.validate(key, text)
    except ValueError as exc:
        return _page(request, db, errors={key: str(exc)}, drafts={key: text}, status_code=400)
    if text == replies.BY_KEY[key].default:
        db.execute(delete(ReplyTemplate).where(ReplyTemplate.key == key))
    else:
        stmt = insert(ReplyTemplate).values(key=key, text=text, updated_by=user.id)
        db.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
            "text": stmt.excluded.text, "updated_by": user.id, "updated_at": stmt.excluded.updated_at}))
    _log(db, user, "reply_template.update", key=key, text=text)
    db.commit()
    flash(request, "Reply saved.")
    return RedirectResponse(f"/settings#t-{key}", status_code=303)


@router.post("/templates/{key}/reset")
def reset_template(request: Request, key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if key not in replies.BY_KEY:
        raise HTTPException(404, "Unknown template")
    db.execute(delete(ReplyTemplate).where(ReplyTemplate.key == key))
    _log(db, user, "reply_template.reset", key=key)
    db.commit()
    flash(request, "Reply reset to the default text.")
    return RedirectResponse(f"/settings#t-{key}", status_code=303)


@router.post("/auto-speed")
def save_speed(request: Request, quiet_s: str = Form(""), delay_min_s: str = Form(""), delay_max_s: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        values = {"quiet_s": int(quiet_s), "delay_min_s": int(delay_min_s), "delay_max_s": int(delay_max_s)}
        auto.set_speed(db, values, user)
    except ValueError as exc:
        db.rollback()
        return _page(request, db, errors={"speed": str(exc) if "must" in str(exc) or "longer" in str(exc)
                                          else "Whole seconds only."}, status_code=400)
    _log(db, user, "auto.speed", **values)
    db.commit()
    flash(request, "Auto-reply speed saved.")
    return RedirectResponse("/settings#auto-speed", status_code=303)


@router.post("/order-rules")
def save_order_rules(request: Request, reminder_hours: str = Form(""), cancel_hours: str = Form(""),
                     auto_delivered_days: str = Form(""), thank_you: str = Form(""),
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        values = {"reminder_hours": int(reminder_hours), "cancel_hours": int(cancel_hours),
                  "auto_delivered_days": int(auto_delivered_days), "thank_you": thank_you == "1"}
    except ValueError:
        return _page(request, db, errors={"rules": "Whole numbers only."}, status_code=400)
    try:
        delivery.set_rules(db, values, user)
    except ValueError as exc:
        db.rollback()
        return _page(request, db, errors={"rules": str(exc)}, status_code=400)
    _log(db, user, "order_rules.update", **values)
    db.commit()
    flash(request, "Orders & payments settings saved.")
    return RedirectResponse("/settings#order-rules", status_code=303)
