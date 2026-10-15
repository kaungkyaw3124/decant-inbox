"""Login, sessions and CSRF for the dashboard.

Session = signed cookie (Starlette SessionMiddleware) holding user_id + csrf token.
Every POST must carry the csrf token (form field or X-CSRF-Token header).
"""
import secrets
import time
from collections import defaultdict
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.models import User
from app.web.deps import get_db

hasher = PasswordHasher()
_DUMMY_HASH = hasher.hash("timing-equalizer")

# Brute-force brake (in memory; resets on restart), per client IP and per username.
# The per-username limit is higher so one attacker can't lock the owner out alone.
MAX_FAILURES_PER_IP = 10
MAX_FAILURES_PER_USER = 30
FAILURE_WINDOW = 15 * 60
_failures: dict[str, list[float]] = defaultdict(list)
LOCAL_PEERS = {"127.0.0.1", "::1"}


class LoginRequired(Exception):
    def __init__(self, next_url: str):
        self.next_url = next_url


def hash_password(password: str) -> str:
    return hasher.hash(password)


def client_ip(request: Request) -> str:
    """Real client IP. Behind the Cloudflare tunnel every request comes from cloudflared on
    127.0.0.1 and Cloudflare sets CF-Connecting-IP (clients can't override it). The header
    is trusted only from a local peer; uvicorn runs with --no-proxy-headers."""
    peer = request.client.host if request.client else ""
    if peer in LOCAL_PEERS:
        cf_ip = request.headers.get("cf-connecting-ip", "").strip()
        if cf_ip:
            return cf_ip
    return peer


def _recent(key: str) -> int:
    now = time.monotonic()
    _failures[key] = [t for t in _failures[key] if now - t < FAILURE_WINDOW]
    if not _failures[key]:
        del _failures[key]
        return 0
    return len(_failures[key])


def locked_out(username: str, ip: str) -> bool:
    return (_recent(f"ip:{ip}") >= MAX_FAILURES_PER_IP
            or _recent(f"user:{username}") >= MAX_FAILURES_PER_USER)


def authenticate(db: Session, username: str, password: str, ip: str) -> User | None:
    username = username.strip().lower()
    if locked_out(username, ip):
        return None
    user = db.query(User).filter(User.username == username).one_or_none()
    try:
        hasher.verify(user.password_hash if user else _DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError):
        now = time.monotonic()
        _failures[f"ip:{ip}"].append(now)
        _failures[f"user:{username}"].append(now)
        return None
    if user is None or user.disabled:
        return None  # a disabled user can't log in (same message as a wrong password)
    _failures.pop(f"ip:{ip}", None)
    return user


def login(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf"] = secrets.token_urlsafe(32)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is not None and user.disabled:  # disabled while logged in: out at the next click
        request.session.clear()
        user = None
    if user is None:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise LoginRequired(quote(target, safe=""))
    return user


async def verify_csrf(request: Request) -> None:
    if request.method != "POST":
        return
    expected = request.session.get("csrf")
    sent = request.headers.get("x-csrf-token") or (await request.form()).get("csrf")
    if not expected or not sent or not secrets.compare_digest(str(sent), expected):
        raise HTTPException(403, "Form expired. Go back, reload the page and try again.")


def owner_only(user: User = Depends(current_user)) -> User:
    """Money settings, prices, users, learning approvals (docs/SPEC-v4.md 4.4): 403 for staff."""
    if not user.is_owner:
        raise HTTPException(403, "Only the owner can do this.")
    return user
