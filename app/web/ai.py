"""AI page (docs/SPEC-v4.6-ai.md S5, owner only): mode switch, today / this month numbers,
settings, the last 50 calls, and "Run evaluation" (scripts/ai_eval.py against the real API)."""
import subprocess
import sys
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import graduation, report, screens  # noqa: F401  (screens: the reader's settings)
from app.ai import settings as ai_settings
from app.ai.types import AIResult
from app.core.config import BASE_DIR
from app.models import AuditLog, Product, User
from app.web.auth import current_user, owner_only, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(prefix="/ai", dependencies=[Depends(owner_only), Depends(verify_csrf)])
MODE_LABELS = {"off": "OFF", "shadow": "SHADOW: suggests on teaching cards", "auto": "AUTO: acts when sure"}


def _call_rows(db: Session) -> list[dict]:
    names = dict(db.execute(select(Product.id, Product.name)).all())
    rows = []
    for call in report.recent(db):
        summary = ""
        if call.result_json:
            try:
                r = AIResult.from_json(call.result_json)
                parts = [(names.get(i.product_id, "?") if i.product_id else f"🚫 {i.not_in_list}" if i.not_in_list
                          else f"? {i.unclear_text or ''}") + (f" {i.size}" if i.size else "")
                         + (f" ×{i.qty}" if i.qty != 1 else "") for i in r.items]
                summary = f"{r.intent} {r.confidence:.2f}" + (": " + ", ".join(parts) if parts else "")
                reason = r.reason
            except (KeyError, TypeError, ValueError):
                reason = ""
        else:
            reason = ""
        rows.append({"call": call, "summary": summary, "reason": reason})
    return rows


@router.get("", response_class=HTMLResponse)
def ai_page(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    return templates.TemplateResponse(request, "ai.html", {
        "cfg": ai_settings.load(db), "modes": MODE_LABELS, "reasonings": ai_settings.REASONING,
        "today": report.period(db, report.today_start(now)), "month": report.period(db, report.month_start(now)),
        "notices": report.notices(db, now), "calls": _call_rows(db), "evaluation": report.latest_eval(),
        "eval_running": report.eval_running(now), "progress": graduation.progress(db, now),
        "auto_since": _since(ai_settings.load(db).get("auto_since")),
        # docs/SPEC-v4.12-address-payment-ai.md N4: privacy switches + what they did this month
        "privacy": report.privacy_stats(db, report.month_start(now)), "screens_ok": screens_available(db)})


def screens_available(db: Session) -> bool:
    """S0: the capability check passed with the model that is configured now."""
    cfg = ai_settings.load(db)
    found = cfg.get("screenshot_check") or {}
    return bool(found.get("ok")) and found.get("model") == cfg["model"]


@router.post("/privacy")
def set_privacy(request: Request, ai_address: str = Form(""), ai_screenshot: str = Form(""),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    """docs/SPEC-v4.12-address-payment-ai.md: what may be sent to the AI (owner only)."""
    values = {"ai_address": ai_address == "1", "ai_screenshot": ai_screenshot == "1"}
    if values["ai_screenshot"] and not screens_available(db):
        model = ai_settings.load(db)["model"]
        flash(request, f"Screenshot reading is not available with model {model}.")
        values["ai_screenshot"] = False
        before = ai_settings.load(db)
        ai_settings.save(db, values, user)
        db.add(AuditLog(user_id=user.id, action="ai.privacy", details={
            "before": {k: before[k] for k in values}, "after": values}))
        db.commit()
        return RedirectResponse("/ai#privacy", status_code=303)
    return _save(request, db, user, values, "privacy")


def _since(value: str | None) -> datetime | None:
    """docs/SPEC-v4.11-ai-first.md L1: the banner "AUTO since <date>"."""
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _save(request: Request, db: Session, user: User, values: dict, what: str) -> RedirectResponse:
    try:
        before = ai_settings.load(db)
        ai_settings.save(db, values, user)
    except (ValueError, TypeError) as exc:
        db.rollback()
        flash(request, f"Not saved: {exc}")
        return RedirectResponse("/ai", status_code=303)
    db.add(AuditLog(user_id=user.id, action=f"ai.{what}", details={
        "before": {k: before[k] for k in values}, "after": values}))
    db.commit()
    flash(request, "Saved.")
    return RedirectResponse("/ai", status_code=303)


@router.post("/mode")
def set_mode(request: Request, mode: str = Form(...), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    """A manual switch also turns auto-graduate OFF (docs/SPEC-v4.7-graduation.md)."""
    if mode not in ai_settings.MODES:
        flash(request, "Not saved: Mode: off, shadow or auto.")
        return RedirectResponse("/ai", status_code=303)
    before = ai_settings.load(db)
    graduation.manual_switch(db, mode, user)
    db.add(AuditLog(user_id=user.id, action="ai.mode", details={
        "before": {"mode": before["mode"], "auto_graduate": before["auto_graduate"]},
        "after": {"mode": mode, "auto_graduate": False}}))
    db.commit()
    flash(request, "Saved. Auto-graduation is OFF now (you chose the mode yourself); turn it on again below.")
    return RedirectResponse("/ai", status_code=303)


@router.post("/settings")
def set_settings(request: Request, daily_cap: str = Form(...), monthly_budget_usd: str = Form(...),
                 threshold: str = Form(...), model: str = Form(...), reasoning: str = Form(...),
                 auto_graduate: str = Form(""), min_days: str = Form("7"), min_decisions: str = Form("50"),
                 min_accuracy: str = Form("95"),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        values = {"daily_cap": int(daily_cap), "monthly_budget_usd": float(monthly_budget_usd),
                  "threshold": float(threshold), "model": model.strip(), "reasoning": reasoning,
                  "auto_graduate": auto_graduate == "1", "min_days": int(min_days),
                  "min_decisions": int(min_decisions), "min_accuracy": float(min_accuracy) / 100}
    except ValueError:
        flash(request, "Not saved: type numbers for the limits, budget, threshold and graduation rules.")
        return RedirectResponse("/ai", status_code=303)
    return _save(request, db, user, values, "settings")


@router.post("/evaluate")
def run_evaluation(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Starts scripts/ai_eval.py in the background (real API, a few cents); the page shows the
    latest report when it is done."""
    now = datetime.now(UTC)
    if report.eval_running(now):
        flash(request, "The evaluation is already running.")
        return RedirectResponse("/ai", status_code=303)
    report.EXPORTS.mkdir(parents=True, exist_ok=True)
    report.EVAL_RUNNING.write_text(now.isoformat())
    log = report.EVAL_LOG.open("w")
    subprocess.Popen(  # noqa: S603 - fixed command, no user input
        ["/bin/sh", "-c", f'"{sys.executable}" -m scripts.ai_eval; rm -f "{report.EVAL_RUNNING}"'],
        cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    db.add(AuditLog(user_id=user.id, action="ai.evaluate", details={}))
    db.commit()
    flash(request, "Evaluation started. It takes about 2 minutes; reload this page.")
    return RedirectResponse("/ai", status_code=303)
