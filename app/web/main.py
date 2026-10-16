"""Dashboard app. Listens on 127.0.0.1:8080 only; the Cloudflare quick tunnel
(scripts/tunnel.py) adds public HTTPS, an SSH tunnel is the fallback.

Usage: .venv/bin/uvicorn app.web.main:app --host 127.0.0.1 --port 8080 --no-access-log --no-proxy-headers
(client IP comes from CF-Connecting-IP via auth.client_ip, not from uvicorn's proxy headers)
(no access log: inbox search terms are customer text and must not be logged)
"""
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.models import AuditLog, User
from app.web import (
    ai as ai_pages, auto as auto_pages, catalog, chats, health, help as help_pages, i18n, inbox, learning, orders, payments, practice,
    prices, sales, settings as settings_pages, users,
)
from app.web.auth import LoginRequired, authenticate, client_ip, current_user, locked_out, login, verify_csrf
from app.web.deps import get_db, templates

settings = get_settings()
if settings.web_secret_key is None:
    sys.exit("WEB_SECRET_KEY is missing in .env (see .env.example)")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.web_secret_key.get_secret_value(),
    session_cookie="decant_session",
    max_age=30 * 24 * 3600,
    same_site="lax",
    https_only=settings.web_cookie_secure,
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(inbox.router)
app.include_router(catalog.router)
app.include_router(chats.router)
app.include_router(auto_pages.router)
app.include_router(payments.router)
app.include_router(orders.router)
app.include_router(sales.router)
app.include_router(prices.router)
app.include_router(settings_pages.router)
app.include_router(learning.router)
app.include_router(ai_pages.router)
app.include_router(users.router)
app.include_router(health.router)
app.include_router(help_pages.router)
app.include_router(practice.router)

ERROR_TITLES = {400: "Can't do that", 403: "Not allowed", 404: "Not found", 409: "Already changed"}


@app.exception_handler(LoginRequired)
def redirect_to_login(request: Request, exc: LoginRequired):
    if request.headers.get("hx-request"):  # make htmx do a full-page redirect
        return HTMLResponse("", headers={"HX-Redirect": "/login"})
    return RedirectResponse(f"/login?next={exc.next_url}", status_code=303)


@app.exception_handler(StarletteHTTPException)
def error_page(request: Request, exc: StarletteHTTPException):
    """Errors as a page in the user's language (the detail is translated in error.html)."""
    if exc.status_code < 400 or request.headers.get("hx-request"):
        return HTMLResponse(str(exc.detail), status_code=exc.status_code, headers=exc.headers)
    return templates.TemplateResponse(request, "error.html", {
        "title": ERROR_TITLES.get(exc.status_code, "Something went wrong"), "detail": str(exc.detail)},
        status_code=exc.status_code, headers=exc.headers)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"next": inbox.safe_back(next, "/"), "error": None})


@app.post("/login", dependencies=[Depends(verify_csrf)])
def login_submit(
    request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"),
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    user = authenticate(db, username, password, ip)
    if user is None:
        error = ("Too many failed attempts. Wait 15 minutes." if locked_out(username.strip().lower(), ip)
                 else "Wrong username or password.")
        return templates.TemplateResponse(request, "login.html",
                                          {"next": inbox.safe_back(next, "/"), "error": error}, status_code=401)
    login(request, user)
    return RedirectResponse(inbox.safe_back(next, "/"), status_code=303)


@app.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request, db: Session = Depends(get_db)):
    user = db.get(User, request.session.get("user_id") or 0)
    request.session.clear()
    if user is not None:
        request.session["lang"] = user.language  # the login page stays in their language
    return RedirectResponse("/login", status_code=303)


@app.post("/language", dependencies=[Depends(verify_csrf)])
def set_language(request: Request, language: str = Form(...), back: str = Form("/"), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    """The header switch: every user picks their own dashboard language (saved on the user)."""
    if language not in i18n.LANGUAGES:
        raise HTTPException(400, "Unknown language")
    user.language = language
    db.add(AuditLog(user_id=user.id, action="user.language", details={"user_id": user.id, "language": language}))
    db.commit()
    return RedirectResponse(inbox.safe_back(back, "/"), status_code=303)
