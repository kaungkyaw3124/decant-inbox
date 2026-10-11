"""Dashboard app. Listens on 127.0.0.1:8080 only; the Cloudflare quick tunnel
(scripts/tunnel.py) adds public HTTPS, an SSH tunnel is the fallback.

Usage: .venv/bin/uvicorn app.web.main:app --host 127.0.0.1 --port 8080 --no-access-log --no-proxy-headers
(client IP comes from CF-Connecting-IP via auth.client_ip, not from uvicorn's proxy headers)
(no access log: inbox search terms are customer text and must not be logged)
"""
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.web import catalog, health, inbox, prices, settings as settings_pages
from app.web.auth import LoginRequired, authenticate, client_ip, locked_out, login, verify_csrf
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
app.include_router(prices.router)
app.include_router(settings_pages.router)
app.include_router(health.router)


@app.exception_handler(LoginRequired)
def redirect_to_login(request: Request, exc: LoginRequired):
    if request.headers.get("hx-request"):  # make htmx do a full-page redirect
        return HTMLResponse("", headers={"HX-Redirect": "/login"})
    return RedirectResponse(f"/login?next={exc.next_url}", status_code=303)


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
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
