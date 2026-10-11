import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.pricing.prices import format_mmk, size_label


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def _template_context(request: Request) -> dict:
    auto_on = False
    if request.session.get("user_id"):  # the switch is shown on every page
        from app.orders import auto  # late import: avoids an import cycle at startup

        with SessionLocal() as session:
            auto_on = auto.enabled(session)
    return {"csrf": csrf_token(request), "flash": request.session.pop("flash", None),
            "path": request.url.path, "auto_on": auto_on}


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates", context_processors=[_template_context]
)
_TZ = ZoneInfo(get_settings().timezone)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def local_time(value: datetime | None, fmt: str = "%d %b %H:%M") -> str:
    return value.astimezone(_TZ).strftime(fmt) if value else ""


templates.env.filters["local_time"] = local_time
templates.env.globals.update(format_mmk=format_mmk, size_label=size_label, now=lambda: datetime.now(UTC))
