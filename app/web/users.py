"""Users (owner only, docs/SPEC-v4.md 4.4): add staff, reset a password, disable, language,
what staff may do; and the Activity page (audit_log with who did it)."""
import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.models.users import LANGUAGES, ROLES
from app.web import staff
from app.web.auth import hash_password, owner_only, verify_csrf
from app.web.deps import get_db, templates
from app.web.inbox import flash

router = APIRouter(dependencies=[Depends(owner_only), Depends(verify_csrf)])
MIN_PASSWORD = 10
ACTIVITY_PAGE = 100


def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


def _back(request: Request, note: str) -> RedirectResponse:
    flash(request, note)
    return RedirectResponse("/users", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "users.html", {
        "users": db.scalars(select(User).order_by(User.role, User.username)).all(),
        "staff_settings": staff.settings(db), "roles": ROLES, "languages": LANGUAGES, "min_password": MIN_PASSWORD})


@router.post("/users")
def add_user(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form("staff"),
             language: str = Form("my"), db: Session = Depends(get_db), me: User = Depends(owner_only)):
    username = username.strip().lower()
    if not username or len(username) > 64 or not username.replace("_", "").replace(".", "").isalnum():
        return _back(request, "Username: letters and numbers only.")
    if role not in ROLES or language not in LANGUAGES:
        raise HTTPException(400, "Unknown role or language")
    if len(password) < MIN_PASSWORD:
        return _back(request, f"Password: at least {MIN_PASSWORD} characters.")
    if db.scalar(select(User.id).where(User.username == username)):
        return _back(request, f"“{username}” already exists.")
    user = User(username=username, password_hash=hash_password(password), role=role, language=language)
    db.add(user)
    db.flush()
    db.add(AuditLog(user_id=me.id, action="user.add", details={"user_id": user.id, "username": username,
                                                                "role": role}))
    db.commit()
    return _back(request, f"{role.title()} “{username}” added. Give them the password in person.")


@router.post("/users/{user_id}/password")
def reset_password(request: Request, user_id: int, password: str = Form(...), db: Session = Depends(get_db),
                   me: User = Depends(owner_only)):
    user = _user(db, user_id)
    if len(password) < MIN_PASSWORD:
        return _back(request, f"Password: at least {MIN_PASSWORD} characters.")
    user.password_hash = hash_password(password)
    db.add(AuditLog(user_id=me.id, action="user.password", details={"user_id": user.id}))
    db.commit()
    return _back(request, f"New password set for “{user.username}”.")


@router.post("/users/{user_id}/disabled")
def set_disabled(request: Request, user_id: int, disabled: str = Form(...), db: Session = Depends(get_db),
                 me: User = Depends(owner_only)):
    user = _user(db, user_id)
    if user.id == me.id:
        return _back(request, "You can't disable yourself.")
    user.disabled = disabled == "1"
    db.add(AuditLog(user_id=me.id, action="user.disable" if user.disabled else "user.enable",
                    details={"user_id": user.id}))
    db.commit()
    return _back(request, f"“{user.username}” {'can no longer log in' if user.disabled else 'can log in again'}.")


@router.post("/users/{user_id}/language")
def set_language(request: Request, user_id: int, language: str = Form(...), db: Session = Depends(get_db),
                 me: User = Depends(owner_only)):
    user = _user(db, user_id)
    if language not in LANGUAGES:
        raise HTTPException(400, "Unknown language")
    user.language = language
    db.add(AuditLog(user_id=me.id, action="user.language", details={"user_id": user.id, "language": language}))
    db.commit()
    return _back(request, "Saved.")


@router.post("/users/staff-settings")
def staff_settings(request: Request, can_approve_payments: str = Form(""), db: Session = Depends(get_db),
                   me: User = Depends(owner_only)):
    staff.set_settings(db, {"can_approve_payments": can_approve_payments == "1"}, me)
    db.add(AuditLog(user_id=me.id, action="staff.settings",
                    details={"can_approve_payments": can_approve_payments == "1"}))
    db.commit()
    return _back(request, "Staff settings saved.")


# ---------- activity (audit log) ----------

def summary(details: dict) -> str:
    return json.dumps(details or {}, ensure_ascii=False)[:160]


@router.get("/activity", response_class=HTMLResponse)
def activity(request: Request, who: str = "", page: int = 1, db: Session = Depends(get_db)):
    page = max(page, 1)
    query = select(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)
    if who == "auto":
        query = query.where(AuditLog.user_id.is_(None))
    elif who.isdigit():
        query = query.where(AuditLog.user_id == int(who))
    rows = db.execute(query.order_by(AuditLog.id.desc()).limit(ACTIVITY_PAGE + 1)
                      .offset((page - 1) * ACTIVITY_PAGE)).all()
    return templates.TemplateResponse(request, "activity.html", {
        "rows": [(a, u, summary(a.details)) for a, u in rows[:ACTIVITY_PAGE]], "who": who, "page": page,
        "more": len(rows) > ACTIVITY_PAGE, "users": db.scalars(select(User).order_by(User.username)).all(),
        "today": db.scalar(select(func.count()).select_from(AuditLog)
                           .where(AuditLog.created_at >= func.date_trunc("day", func.now())))})
