"""docs/SPEC-v5.0-go-live-pack.md G3: My account — 2-step login (authenticator app) and "log out everywhere".
Every user can use it for their own account (the owner should; staff may)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import AuditLog, TrustedDevice, User
from app.web import trust, twostep
from app.web.auth import current_user, login, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(dependencies=[Depends(current_user), Depends(verify_csrf)])


def _page(request: Request, user: User, status_code: int = 200, **extra):
    with SessionLocal() as db:
        devices = db.scalars(select(TrustedDevice).where(TrustedDevice.user_id == user.id)
                             .order_by(TrustedDevice.last_used_at.desc())).all()
        this = trust.device(db, request)
    return templates.TemplateResponse(request, "account.html", {
        "me": user, "new_secret": None, "codes": None, "error": None, "devices": devices,
        "this_device": this.id if this else None, **extra}, status_code=status_code)


@router.get("/account", response_class=HTMLResponse)
def account(request: Request, user: User = Depends(current_user)):
    return _page(request, user)


@router.post("/account/2fa/start", response_class=HTMLResponse)
def start(request: Request, user: User = Depends(current_user)):
    secret = twostep.new_secret()  # kept in the session until a correct code proves the app has it
    request.session["totp_new"] = secret
    return _page(request, user, new_secret=secret, qr=twostep.qr_svg(twostep.uri(secret, user.username)))


@router.post("/account/2fa/confirm", response_class=HTMLResponse)
def confirm(request: Request, code: str = Form(...), db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    secret = request.session.get("totp_new")
    if not secret:
        return RedirectResponse("/account", status_code=303)
    if not twostep.verify(secret, code):
        return _page(request, user, new_secret=secret, qr=twostep.qr_svg(twostep.uri(secret, user.username)),
                     error="Wrong code. Check the time on your phone and try the newest code.", status_code=400)
    shown, hashes = twostep.new_recovery_codes()
    user.totp_secret, user.totp_recovery = secret, hashes
    request.session.pop("totp_new", None)
    db.add(AuditLog(user_id=user.id, action="user.2fa_on", details={"user_id": user.id}))
    db.commit()
    return _page(request, user, codes=shown)  # shown once


@router.post("/account/2fa/recovery", response_class=HTMLResponse)
def recovery(request: Request, code: str = Form(...), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    if not twostep.verify(user.totp_secret, code):
        return _page(request, user, error="Wrong code.", status_code=400)
    shown, user.totp_recovery = twostep.new_recovery_codes()
    db.add(AuditLog(user_id=user.id, action="user.2fa_recovery_new", details={"user_id": user.id}))
    db.commit()
    return _page(request, user, codes=shown)


@router.post("/account/2fa/off")
def off(request: Request, code: str = Form(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not twostep.verify(user.totp_secret, code):
        return _page(request, user, error="Wrong code.", status_code=400)
    user.totp_secret, user.totp_recovery = None, []
    db.add(AuditLog(user_id=user.id, action="user.2fa_off", details={"user_id": user.id}))
    db.commit()
    flash(request, "2-step login is off.")
    return RedirectResponse("/account", status_code=303)


@router.post("/account/trusted/{device_id}/remove")
def remove_trusted(request: Request, device_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """docs/SPEC-v5.3 M5: that computer asks for the password (+ code) at its next login."""
    db.execute(delete(TrustedDevice).where(TrustedDevice.id == device_id, TrustedDevice.user_id == user.id))
    db.add(AuditLog(user_id=user.id, action="user.untrust_device", details={"device_id": device_id}))
    db.commit()
    flash(request, "Trusted computer removed.")
    return RedirectResponse("/account#trusted", status_code=303)


@router.post("/account/logout-everywhere")
def logout_everywhere(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.session_epoch += 1  # every other browser is logged out at its next click; this one logs in again
    trust.remove_all(db, user.id)  # docs/SPEC-v5.3 M5: trusted computers too
    db.add(AuditLog(user_id=user.id, action="user.logout_everywhere", details={"user_id": user.id}))
    db.commit()
    login(request, user)
    flash(request, "Logged out on every other device.")
    return RedirectResponse("/account", status_code=303)
