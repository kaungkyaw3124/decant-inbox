"""docs/SPEC-v5.1-inventory.md: Products & prices → Stock (everyone sees it; changing stock is the owner's)."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.inventory import excel, stock
from app.models import AuditLog, Bottle, User
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import _TZ, get_db, templates
from app.web.inbox import flash, safe_back

router = APIRouter(prefix="/stock", dependencies=[Depends(current_user), Depends(verify_csrf)])
MAX_UPLOAD = 2 * 1024 * 1024


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().web_secret_key.get_secret_value(), salt="stock-import")


def _number(value: str, whole: bool = True) -> float | int | None:
    value = (value or "").replace(",", "").strip()
    if not value:
        return None
    n = float(value)
    return int(n) if whole else n


def _back(request: Request) -> str:
    """docs/SPEC-v5.6: forms in the Products panel / dialogs come back to it (?back=...), the rest to /stock."""
    return safe_back(request.query_params.get("back", ""), "/stock")


def _done(request: Request, db: Session, user: User, action: str, text: str, **details):
    db.add(AuditLog(user_id=user.id, action=action, details=details))
    db.commit()
    flash(request, text)
    return RedirectResponse(_back(request), status_code=303)


def _failed(request: Request, db: Session, text: str):
    db.rollback()
    flash(request, text)
    return RedirectResponse(_back(request), status_code=303)


@router.get("")
def stock_page(user: User = Depends(current_user)):
    """docs/SPEC-v5.6: stock is on the Products page now; the owner's overview (reorder list, value, history,
    thresholds) is Settings -> Inventory."""
    return RedirectResponse("/settings?section=inventory" if user.is_owner else "/products", status_code=303)


@router.post("/bottles", dependencies=[Depends(owner_only)])
def add(request: Request, product_id: int = Form(...), size_ml: str = Form(...), count: str = Form("1"),
        cost_mmk: str = Form(""), remaining_ml: str = Form(""), db: Session = Depends(get_db),
        user: User = Depends(current_user)):
    try:
        added = stock.add_bottles(db, product_id, _number(size_ml), _number(count) or 1, _number(cost_mmk),
                                  _number(remaining_ml, whole=False), user)
    except (stock.StockError, ValueError, TypeError) as exc:
        return _failed(request, db, str(exc) if isinstance(exc, stock.StockError) else "Numbers only, please.")
    return _done(request, db, user, "stock.purchase", f"Added {len(added)} bottle(s).", product_id=product_id,
                 count=len(added))


@router.post("/bottles/{bottle_id}/open", dependencies=[Depends(owner_only)])
def open_(request: Request, bottle_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        stock.open_bottle(db, db.get(Bottle, bottle_id, with_for_update=True), user)
    except (stock.StockError, AttributeError) as exc:
        return _failed(request, db, str(exc) if isinstance(exc, stock.StockError) else "Bottle not found.")
    return _done(request, db, user, "stock.open", "Bottle opened.", bottle_id=bottle_id)


@router.post("/bottles/{bottle_id}/adjust", dependencies=[Depends(owner_only)])
def adjust(request: Request, bottle_id: int, remaining_ml: str = Form(...), reason: str = Form(""),
           db: Session = Depends(get_db), user: User = Depends(current_user)):
    bottle = db.get(Bottle, bottle_id, with_for_update=True)
    if bottle is None:
        return _failed(request, db, "Bottle not found.")
    try:
        stock.adjust_bottle(db, bottle, _number(remaining_ml, whole=False), reason, user)
    except (stock.StockError, ValueError, TypeError) as exc:
        return _failed(request, db, str(exc) if isinstance(exc, stock.StockError) else "Numbers only, please.")
    return _done(request, db, user, "stock.adjust", "Stock adjusted.", bottle_id=bottle_id)


@router.post("/adjust", dependencies=[Depends(owner_only)])
def fix_amount(request: Request, bottle_id: int = Form(...), remaining_ml: str = Form(...), reason: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The panel's "Fix the amount": the bottle is picked in the form (same rules as a bottle's Adjust)."""
    return adjust(request, bottle_id, remaining_ml, reason, db, user)


@router.post("/vials", dependencies=[Depends(owner_only)])
def vials(request: Request, size_ml: str = Form(...), change: str = Form(...), cost_each_mmk: str = Form(""),
          reason: str = Form(""), db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        stock.change_vials(db, _number(size_ml), _number(change), _number(cost_each_mmk), reason.strip(), user)
    except (stock.StockError, ValueError, TypeError) as exc:
        return _failed(request, db, str(exc) if isinstance(exc, stock.StockError) else "Numbers only, please.")
    return _done(request, db, user, "stock.vials", "Vials saved.", size_ml=size_ml)


@router.post("/settings", dependencies=[Depends(owner_only)])
async def save_settings(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    try:
        values = {"spill_ml": _number(str(form.get("spill_ml", "")), whole=False),
                  "low_ml": _number(str(form.get("low_ml", ""))), "low_vials": _number(str(form.get("low_vials", "")))}
        products = {k.removeprefix("low_"): _number(str(v)) for k, v in form.items()
                    if k.startswith("low_") and k.removeprefix("low_").isdigit() and str(v).strip()}
    except ValueError:
        return _failed(request, db, "Numbers only, please.")
    if any(v is None or v < 0 for v in values.values()) or values["spill_ml"] > 5:
        return _failed(request, db, "Spill 0-5 ml; thresholds 0 or more.")
    stock.save_settings(db, {**values, "low_ml_products": products}, user)
    return _done(request, db, user, "stock.settings", "Stock settings saved.")


@router.get("/export.xlsx", dependencies=[Depends(owner_only)])
def export(db: Session = Depends(get_db)):
    return Response(excel.export(db), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="stock-{datetime.now(_TZ):%Y-%m-%d}.xlsx"'})


@router.post("/import", response_class=HTMLResponse, dependencies=[Depends(owner_only)])
async def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return _failed(request, db, "File too big (max 2 MB).")
    try:
        bottles, vial_rows, errors = excel.read(db, data)
    except excel.SheetError as exc:
        return _failed(request, db, str(exc))
    return templates.TemplateResponse(request, "stock_preview.html", {
        "bottles": bottles, "vials": vial_rows, "errors": errors,
        "payload": None if errors else _signer().dumps(excel.to_payload(bottles, vial_rows))})


@router.post("/import/confirm", dependencies=[Depends(owner_only)])
def confirm(request: Request, payload: str = Form(...), db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    try:
        bottles, vial_rows = excel.from_payload(_signer().loads(payload, max_age=3600))
    except BadSignature:
        return _failed(request, db, "This preview has expired. Upload the file again.")
    try:
        stats = stock.apply_import(db, bottles, vial_rows, user)
    except stock.StockError as exc:
        return _failed(request, db, str(exc))
    return _done(request, db, user, "stock.import", f"Stock added: {stats['bottles']} bottles, {stats['vials']} vials.",
                 **stats)
