"""Settings: payment methods and reply templates. Every change goes to audit_log."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.inventory import stock
from app.models import AuditLog, Customer, FaqEntry, PaymentMethod, Product, ReplyTemplate, User
from app.orders import auto, delivery, testpay
from app.pricing import costs
from app.pricing.prices import DEFAULT_SIZES, current_prices
from app.replies import faq
from app.replies import templates as replies
from app.alerts import bot, service as alerts
from app.core.config import get_settings
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import get_db, templates
from app.web import paging
from app.web.inbox import flash

router = APIRouter(prefix="/settings", dependencies=[Depends(owner_only), Depends(verify_csrf)])  # owner only (4.4)

# docs/SPEC-v5.4 X3: Settings shows one section at a time; a save comes back to its section with "Saved ✓"
SECTIONS = ("orders", "auto-reply", "alerts", "inventory", "test", "shop")
_SECTION_OF = {"order-rules": "orders", "payment-methods": "orders", "auto-speed": "auto-reply", "faq": "auto-reply",
               "t-": "auto-reply", "alerts": "alerts", "vial-costs": "inventory", "test-payments": "test"}
_ERROR_SECTION = {"speed": "auto-reply", "rules": "orders", "faq": "auto-reply", "faq_id": "auto-reply",
                  "vial": "inventory"}


def section_of(anchor: str) -> str:
    return next((sec for prefix, sec in _SECTION_OF.items() if anchor.startswith(prefix)), "orders")


def _to(anchor: str) -> RedirectResponse:
    return RedirectResponse(f"/settings?section={section_of(anchor)}&saved={anchor}#{anchor}", status_code=303)



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
    section = request.query_params.get("section")
    if errors:
        section = next((_ERROR_SECTION.get(k, "auto-reply") for k in errors), section)
    return templates.TemplateResponse(request, "settings.html", {
        "section": section if section in SECTIONS else "orders", "saved": request.query_params.get("saved", ""),
        "methods": methods, "templates": rows, "speed": auto.speed(db), "speed_limits": auto.SPEED_LIMITS,
        "speed_error": (errors or {}).get("speed"), "order_rules": delivery.rules(db),
        "rule_limits": delivery.RULE_LIMITS, "rules_error": (errors or {}).get("rules"),
        "faqs": db.scalars(select(FaqEntry).order_by(FaqEntry.sort_order, FaqEntry.id)).all(),
        "faq_error": (errors or {}).get("faq"), "faq_error_id": (errors or {}).get("faq_id"),
        "test_code_set": testpay.code() is not None, "test_auto_approve": testpay.auto_approve(db),
        "testers": db.scalars(select(Customer).where(Customer.is_tester).order_by(Customer.id)).all(),
        "vials": costs.vial_costs(db), "vial_sizes": _decant_sizes(db), "vial_error": (errors or {}).get("vial"),
        "alerts": alerts.settings(db), "alert_types": alerts.TYPES, "alerts_on": bot.configured(),
        # docs/SPEC-v5.6: the stock overview (reorder list, value, thresholds, history) lives in Inventory
        "stock": stock.overview(db), "stock_history": paging.paginate(db, stock.history_query(), request),
        "stock_products": db.scalars(select(Product).where(Product.active).order_by(Product.brand, Product.name)).all(),
        "backup_offsite": bool(get_settings().backup_passphrase and get_settings().backup_passphrase.get_secret_value())},
        status_code=status_code)


def _method_fields(name: str, account_number: str, account_name: str) -> dict[str, str]:
    fields = {"name": name.strip(), "account_number": account_number.strip(), "account_name": account_name.strip()}
    if not all(fields.values()):
        raise HTTPException(400, "Name, account number and account name are all required.")
    if len(fields["name"]) > 64 or len(fields["account_number"]) > 64 or len(fields["account_name"]) > 128:
        raise HTTPException(400, "Too long.")
    return fields


def _log(db: Session, user: User, action: str, **details) -> None:
    db.add(AuditLog(user_id=user.id, action=action, details=details))


# ---------- docs/SPEC-v5.0-go-live-pack.md G1: alerts ----------

@router.post("/alerts")
async def save_alerts(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    alerts.save_settings(db, {k: form.get(f"type_{k}") == "1" for k in alerts.TYPES}, form.get("preview") == "1",
                         user.id)
    _log(db, user, "alerts.settings")
    db.commit()
    flash(request, "Alert settings saved.")
    return _to("alerts")


@router.post("/alerts/test")
def test_alert(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        bot.send("🔔 Test alert from Decant Inbox: alerts reach your phone.", ("Open dashboard", alerts.dashboard_url() or ""))
        flash(request, "Test alert sent: check Telegram.")
    except bot.BotError as exc:
        flash(request, f"Test alert NOT sent: {exc}")
    _log(db, user, "alerts.test")
    db.commit()
    return _to("alerts")


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, db)


@router.post("/test-payments")
def test_payments(request: Request, auto_approve: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    testpay.set_auto_approve(db, auto_approve == "1", user)
    db.commit()
    flash(request, "Saved.")
    return _to("test-payments")


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
    return _to("payment-methods")


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
    return _to("payment-methods")


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
    return _to("payment-methods")


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
    return _to(f"t-{key}")


@router.post("/templates/{key}/reset")
def reset_template(request: Request, key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if key not in replies.BY_KEY:
        raise HTTPException(404, "Unknown template")
    db.execute(delete(ReplyTemplate).where(ReplyTemplate.key == key))
    _log(db, user, "reply_template.reset", key=key)
    db.commit()
    flash(request, "Reply reset to the default text.")
    return _to(f"t-{key}")


@router.post("/auto-speed")
def save_speed(request: Request, quiet_s: str = Form(""), delay_min_s: str = Form(""), delay_max_s: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        values = {"quiet_s": float(quiet_s), "delay_min_s": float(delay_min_s), "delay_max_s": float(delay_max_s)}
        if any(v != v or round(v, 1) != v for v in values.values()):  # NaN / more than 0.1 s precision
            raise ValueError("Seconds, like 0.5 or 2.")
        auto.set_speed(db, values, user)
    except ValueError as exc:
        db.rollback()
        return _page(request, db, errors={"speed": str(exc) if "must" in str(exc) or "longer" in str(exc)
                                          else "Seconds, like 0.5 or 2."}, status_code=400)
    _log(db, user, "auto.speed", **values)
    db.commit()
    flash(request, "Auto-reply speed saved.")
    return _to("auto-speed")


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
    return _to("order-rules")


# ---------- FAQ (Step 7) ----------

def _faq_entry(db: Session, entry_id: int) -> FaqEntry:
    entry = db.get(FaqEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "FAQ entry not found")
    return entry


@router.post("/faq")
def add_faq(request: Request, title: str = Form(""), keywords: str = Form(""), answer: str = Form(""),
            db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        fields = faq.validate(title, keywords, answer)
    except ValueError as exc:
        return _page(request, db, errors={"faq": str(exc), "faq_id": "new"}, status_code=400)
    last = db.scalar(select(FaqEntry.sort_order).order_by(FaqEntry.sort_order.desc()).limit(1))
    entry = FaqEntry(**fields, active=True, edited=True, sort_order=(last or 0) + 1, updated_by=user.id)
    db.add(entry)
    db.flush()
    _log(db, user, "faq.add", id=entry.id, **fields)
    db.commit()
    flash(request, f"FAQ “{entry.title}” added.")
    return _to(f"faq-{entry.id}")


@router.post("/faq/{entry_id}")
def update_faq(request: Request, entry_id: int, title: str = Form(""), keywords: str = Form(""),
               answer: str = Form(""), active: str = Form(""), db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    entry = _faq_entry(db, entry_id)
    try:
        fields = faq.validate(title, keywords, answer)
    except ValueError as exc:
        return _page(request, db, errors={"faq": str(exc), "faq_id": entry_id}, status_code=400)
    for key, value in {**fields, "active": active == "1", "edited": True, "updated_by": user.id}.items():
        setattr(entry, key, value)
    entry.updated_at = func.now()
    _log(db, user, "faq.update", id=entry_id, active=active == "1", **fields)
    db.commit()
    flash(request, f"FAQ “{entry.title}” saved.")
    return _to(f"faq-{entry_id}")


@router.post("/faq/{entry_id}/delete")
def delete_faq(request: Request, entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    entry = _faq_entry(db, entry_id)
    _log(db, user, "faq.delete", id=entry_id, title=entry.title, keywords=entry.keywords, answer=entry.answer)
    db.delete(entry)
    db.commit()
    flash(request, "FAQ entry deleted.")
    return _to("faq")


# ---------- vial cost per decant size (Step 8) ----------

def _decant_sizes(db: Session) -> list[int]:
    sizes = set(DEFAULT_SIZES) | set(costs.vial_costs(db))
    for prices in current_prices(db).values():
        sizes.update(p.size_ml for p in prices if p.size_ml)
    return sorted(sizes)


@router.post("/vial-costs")
async def save_vial_costs(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    values = {}
    for size in _decant_sizes(db):
        raw = "".join(c for c in str(form.get(f"vial_{size}", "")) if c.isdigit())
        values[size] = int(raw) if raw else 0
    try:
        costs.set_vial_costs(db, values, user)
    except ValueError as exc:
        db.rollback()
        return _page(request, db, errors={"vial": str(exc)}, status_code=400)
    _log(db, user, "vial_costs.update", **{str(k): v for k, v in values.items()})
    db.commit()
    flash(request, "Vial costs saved (used for orders paid from now on).")
    return _to("vial-costs")
