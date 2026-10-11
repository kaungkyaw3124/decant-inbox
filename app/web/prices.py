"""Price list: download as Excel, upload -> preview -> confirm.

Nothing is written before Confirm. The preview carries the parsed file in a signed
hidden field (no temp files); Confirm re-checks it against the database and refuses if
the preview the admin saw is no longer what would happen.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuditLog, User
from app.pricing import excel
from app.web.auth import current_user, verify_csrf
from app.web.deps import _TZ, get_db, templates
from app.web.inbox import flash

router = APIRouter(prefix="/prices", dependencies=[Depends(current_user), Depends(verify_csrf)])
MAX_UPLOAD = 2 * 1024 * 1024
PREVIEW_MAX_AGE = 3600


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().web_secret_key.get_secret_value(), salt="price-import")


def _last_import(db: Session) -> AuditLog | None:
    return db.scalar(select(AuditLog).where(AuditLog.action == "prices.import")
                     .order_by(AuditLog.id.desc()).limit(1))


def _page(request: Request, db: Session, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(request, "prices.html", {
        "error": error, "last_import": _last_import(db),
    }, status_code=status_code)


def _preview(request: Request, sheet: excel.Sheet, plan: excel.Plan, filename: str,
             choices: dict[int, str] | None = None, error: str | None = None, status_code: int = 200):
    payload = None if sheet.errors else _signer().dumps({
        "sheet": sheet.to_payload(), "filename": filename, "fingerprint": excel.fingerprint(plan)})
    return templates.TemplateResponse(request, "prices_preview.html", {
        "sheet": sheet, "plan": plan, "filename": filename, "payload": payload,
        "choices": choices or {}, "error": error,
    }, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def prices_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, db)


@router.get("/export.xlsx")
def export(db: Session = Depends(get_db)):
    rows, sizes = excel.export_rows(db)
    filename = f"prices-{datetime.now(_TZ):%Y-%m-%d}.xlsx"
    return Response(excel.write_workbook(rows, sizes),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/import", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read(MAX_UPLOAD + 1)
    filename = (file.filename or "upload.xlsx")[-100:]
    if len(data) > MAX_UPLOAD:
        return _page(request, db, "File too big (max 2 MB).", 400)
    try:
        sheet = excel.read_sheet(data)
    except excel.SheetError as exc:
        return _page(request, db, str(exc), 400)
    return _preview(request, sheet, excel.plan_import(db, sheet), filename)


@router.post("/import/confirm")
async def confirm(request: Request, payload: str = Form(...), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    try:
        data = _signer().loads(payload, max_age=PREVIEW_MAX_AGE)
    except BadSignature:
        return _page(request, db, "This preview has expired. Upload the file again.", 400)
    sheet = excel.Sheet.from_payload(data["sheet"])
    form = await request.form()
    choices = {int(k.removeprefix("choice_")): str(v) for k, v in form.items()
               if k.startswith("choice_") and k.removeprefix("choice_").isdigit()}
    plan = excel.plan_import(db, sheet)
    if json.loads(json.dumps(excel.fingerprint(plan))) != data["fingerprint"]:
        return _preview(request, sheet, plan, data["filename"], choices,
                        "Prices changed since this preview (another import or edit). Check the new preview.", 409)
    try:
        stats = excel.apply_import(db, plan, choices, user.id)
    except ValueError as exc:
        db.rollback()
        return _preview(request, sheet, plan, data["filename"], choices, str(exc), 400)
    db.add(AuditLog(user_id=user.id, action="prices.import",
                    details={"filename": data["filename"], "rows": len(sheet.rows), **stats}))
    db.commit()
    flash(request, f"Price list saved: {stats['products_added']} new products, "
                   f"{stats['products_updated']} updated, {stats['prices_written']} price changes.")
    return RedirectResponse("/prices", status_code=303)
