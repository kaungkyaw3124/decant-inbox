"""docs/SPEC-v5.3-performance-pc.md M5: "Trust this computer for 30 days" (owner only; staff unchanged).

Cookie decant_trust = a random token (HttpOnly, Secure, SameSite=Lax, Path=/, until the fixed 30-day end); the
database keeps only its sha256 (trusted_devices). With a valid token:
- an expired 12 h session is renewed silently (renew(), a middleware inside the session middleware);
- the 2-step code is skipped at login on that computer (the password is still asked).
The token changes every time it is used. Removed by: Log out on that computer, "Log out everywhere",
My account -> Trusted computers -> Remove, the 30 days ending, a disabled user.
No customer data in the cookie.
"""
import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AuditLog, TrustedDevice, User

COOKIE = "decant_trust"
DAYS = 30


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _set(response, token: str, expires_at: datetime) -> None:
    response.set_cookie(COOKIE, token, max_age=max(int((expires_at - datetime.now(UTC)).total_seconds()), 0),
                        httponly=True, secure=get_settings().web_cookie_secure, samesite="lax", path="/")


def forget(response) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=get_settings().web_cookie_secure, samesite="lax")


def device(db: Session, request: Request) -> TrustedDevice | None:
    """The valid trusted computer of this browser, else None."""
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 100:
        return None
    row = db.scalar(select(TrustedDevice).where(TrustedDevice.token_hash == _hash(token)))
    if row is None or row.expires_at <= datetime.now(UTC):
        return None
    user = db.get(User, row.user_id)
    return row if user is not None and user.is_owner and not user.disabled else None


def trust(db: Session, user: User, request: Request, response) -> None:
    token = secrets.token_urlsafe(32)
    row = TrustedDevice(user_id=user.id, token_hash=_hash(token), expires_at=datetime.now(UTC) + timedelta(days=DAYS),
                        user_agent=request.headers.get("user-agent", "")[:255])
    db.add(row)
    db.add(AuditLog(user_id=user.id, action="user.trust_device", details={"user_id": user.id}))
    db.commit()
    _set(response, token, row.expires_at)


def rotate(db: Session, row: TrustedDevice, response) -> None:
    """A new token for the same computer; the 30-day end stays."""
    token = secrets.token_urlsafe(32)
    row.token_hash, row.last_used_at = _hash(token), datetime.now(UTC)
    db.commit()
    _set(response, token, row.expires_at)


def remove(db: Session, request: Request, response) -> None:
    """Log out on this computer: its trust ends too (else the next click would log it in again)."""
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(TrustedDevice).where(TrustedDevice.token_hash == _hash(token)))
        db.commit()
        forget(response)


def remove_all(db: Session, user_id: int) -> None:
    db.execute(delete(TrustedDevice).where(TrustedDevice.user_id == user_id))


def _session_expired(session: dict) -> bool:
    from app.web.auth import SESSION_HOURS

    return not session.get("user_id") or time.time() - session.get("since", 0) > SESSION_HOURS * 3600


async def renew(request: Request, call_next):
    """Middleware: an expired (or missing) session + a valid trusted-computer cookie -> logged in again."""
    if COOKIE not in request.cookies or request.url.path.startswith(("/static/", "/healthz", "/login", "/logout")) \
            or not _session_expired(request.session):
        return await call_next(request)

    def check():
        from app.web.auth import login

        with SessionLocal() as db:
            row = device(db, request)
            if row is None:
                token = request.cookies[COOKIE]
                over = db.execute(delete(TrustedDevice).where(  # 30 days over: this row can never be valid again
                    TrustedDevice.token_hash == _hash(token[:100]), TrustedDevice.expires_at <= datetime.now(UTC)))
                db.commit()
                return False if over.rowcount else None
            login(request, db.get(User, row.user_id))
            token = secrets.token_urlsafe(32)
            row.token_hash, row.last_used_at = _hash(token), datetime.now(UTC)
            db.add(AuditLog(user_id=row.user_id, action="user.trusted_renew", details={"device_id": row.id}))
            db.commit()
            return token, row.expires_at

    renewed = await run_in_threadpool(check)
    response = await call_next(request)
    # an unknown token is left alone: a parallel request may still carry the token another request just rotated,
    # and deleting the cookie then would drop the new one too
    if renewed is False:
        forget(response)
    elif renewed is not None:
        _set(response, *renewed)
    return response
