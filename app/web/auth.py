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

# Brute-force brake per username (in memory; resets on restart).
MAX_FAILURES = 10
FAILURE_WINDOW = 15 * 60
_failures: dict[str, list[float]] = defaultdict(list)


class LoginRequired(Exception):
    def __init__(self, next_url: str):
        self.next_url = next_url


def hash_password(password: str) -> str:
    return hasher.hash(password)


def locked_out(username: str) -> bool:
    now = time.monotonic()
    _failures[username] = [t for t in _failures[username] if now - t < FAILURE_WINDOW]
    return len(_failures[username]) >= MAX_FAILURES


def authenticate(db: Session, username: str, password: str) -> User | None:
    username = username.strip().lower()
    if locked_out(username):
        return None
    user = db.query(User).filter(User.username == username).one_or_none()
    try:
        hasher.verify(user.password_hash if user else _DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError):
        _failures[username].append(time.monotonic())
        return None
    if user is None:
        return None
    _failures.pop(username, None)
    return user


def login(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf"] = secrets.token_urlsafe(32)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
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
