import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.orders import testpay
from app.web import i18n
from app.pricing.prices import format_mmk, size_label


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


_needs: dict[str, tuple[float, int]] = {}  # role -> (monotonic time, Needs you count)


def needs_count(session: Session, role: str) -> int:
    """The Inbox counter in the menu. shortcut: cached 60 s per process (needs_you takes ~0.7 s), make
    needs_you cheaper if the counter must be live."""
    import time

    from app.web.auto import needs_you  # late import: auto imports this module

    at, count = _needs.get(role, (0.0, 0))
    if time.monotonic() - at > 60:
        count = needs_you(session, owner=role == "owner")["count"]
        _needs[role] = (time.monotonic(), count)
    return count


def remember_needs(role: str, count: int) -> None:
    import time

    _needs[role] = (time.monotonic(), count)


def _template_context(request: Request) -> dict:
    auto_on, payments_open, to_pack, role, to_learn, needs = False, 0, 0, None, 0, 0
    lang = request.session.get("lang", i18n.DEFAULT)  # before login: the last user's language
    if request.session.get("user_id"):  # the switch and the badges are on every page
        from sqlalchemy import func, select

        from app.learning import patterns
        from app.models import Order, User
        from app.orders import auto, payments  # late import: avoids an import cycle at startup

        with SessionLocal() as session:
            auto_on, payments_open = auto.enabled(session), payments.count_open(session)
            to_pack = session.scalar(select(func.count()).select_from(Order).where(Order.status == "paid"))
            row = session.execute(select(User.role, User.language).where(User.id == request.session["user_id"])).first()
            if row:
                role, lang = row
            to_learn = patterns.pending_count(session)
            needs = needs_count(session, role) if role else 0
    t, tr, code = i18n.for_lang(lang)
    return {"csrf": csrf_token(request), "flash": request.session.pop("flash", None),
            "path": request.url.path, "auto_on": auto_on, "payments_open": payments_open, "to_pack": to_pack,
            "user_role": role, "to_learn": to_learn, "needs_count": needs, "lang": lang, "t": t, "tr": tr, "code": code}


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates", context_processors=[_template_context]
)
_TZ = ZoneInfo(get_settings().timezone)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def local_time(value: datetime | None, fmt: str = "%d %b %H:%M") -> str:
    return value.astimezone(_TZ).strftime(fmt) if value else ""


AGE_UNITS = {"en": ("min", "h", "d"), "my": ("မိနစ်", "နာရီ", "ရက်")}


@pass_context
def age(context, value: datetime | None) -> str:
    """How long ago, short: "5 min", "3 h", "2 d" (Burmese units for lang=my)."""
    if value is None:
        return ""
    minute, hour, day = AGE_UNITS["my" if context.get("lang") == "my" else "en"]
    minutes = int((datetime.now(UTC) - value).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)} {minute}"
    return f"{minutes // 60} {hour}" if minutes < 48 * 60 else f"{minutes // 1440} {day}"


templates.env.filters["local_time"] = local_time
templates.env.filters["age"] = age
templates.env.globals.update(format_mmk=format_mmk, size_label=size_label, now=lambda: datetime.now(UTC),
                             order_label=testpay.order_label)


def _hide_code(value):
    """docs/SPEC-v4.14: the test payment code never appears in a page (message text, search box, ...)."""
    if isinstance(value, Markup):
        return Markup(testpay.hide(str(value)))
    return testpay.hide(value) if isinstance(value, str) else value


templates.env.finalize = _hide_code


def address_reason(text: str | None) -> str:
    """docs/SPEC-v4.12: why a saved address is not valid (shown next to the ⚠️ badge)."""
    from app.orders import address  # late import: orders -> web would be a cycle at start-up

    return address.validate(text).why or address.REASONS["keywords"]


templates.env.globals["address_reason"] = address_reason
