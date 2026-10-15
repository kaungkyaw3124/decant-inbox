"""Staff settings (docs/SPEC-v4.md 4.4): what staff may do beyond daily orders."""
from fastapi import Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AppSetting, User
from app.web.auth import current_user
from app.web.deps import get_db

SETTING = "staff"
DEFAULTS = {"can_approve_payments": True}


def settings(session: Session) -> dict:
    row = session.get(AppSetting, SETTING)
    return {**DEFAULTS, **(row.value if row else {})}


def set_settings(session: Session, values: dict, user: User) -> None:
    value = {"can_approve_payments": bool(values["can_approve_payments"])}
    stmt = insert(AppSetting).values(key=SETTING, value=value, updated_by=user.id)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


def may_decide_payments(session: Session, user: User) -> bool:
    return user.is_owner or settings(session)["can_approve_payments"]


def payment_decider(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    """Approve / reject / not a payment: the owner, and staff while the owner allows it."""
    if not may_decide_payments(db, user):
        raise HTTPException(403, "Only the owner checks payments now (Users > staff settings).")
    return user
