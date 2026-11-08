import base64
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


def mask_csrf(token: str) -> str:
    """docs/SPEC-v5.3 M1: pages are gzip-compressed, so the token in a page is different every time
    (random pad + token XOR pad) and can't be guessed byte by byte from compressed sizes (BREACH)."""
    raw = token.encode()
    pad = secrets.token_bytes(len(raw))
    return base64.urlsafe_b64encode(pad + bytes(a ^ b for a, b in zip(raw, pad))).decode()


def unmask_csrf(sent: str) -> str:
    """The session token from a masked one; an unmasked (old) token comes back unchanged."""
    try:
        data = base64.urlsafe_b64decode(sent.encode())
    except (ValueError, UnicodeEncodeError):
        return sent
    half = len(data) // 2
    if len(data) % 2 or not half:
        return sent
    return bytes(a ^ b for a, b in zip(data[half:], data[:half])).decode("latin-1")


def needs_count(session: Session, role: str) -> int:
    """The Chats counter in the menu: may be up to 60 s old (docs/SPEC-v5.3 M4: shared with the pages' cache)."""
    from app.web.auto import needs_you_cached  # late import: auto imports this module

    return needs_you_cached(owner=role == "owner", max_age=60)["count"]


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
    return {"csrf": mask_csrf(csrf_token(request)), "flash": request.session.pop("flash", None),
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


def _my(context) -> bool:
    return context.get("lang") == "my"


@pass_context
def day(context, value) -> str:
    """docs/SPEC-v5.7: "8 Nov" (Burmese: the month name translated). A datetime is turned into the shop's day."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.astimezone(_TZ)
    month = f"{value:%b}"
    return f"{value.day} {i18n.translate(month, 'my') if _my(context) else month}"


@pass_context
def when(context, value: datetime | None) -> str:
    """docs/SPEC-v5.7: the real date and time on a row, "8 Nov, 3:12 pm" (Burmese: 24-hour clock)."""
    if value is None:
        return ""
    local = value.astimezone(_TZ)
    clock = f"{local:%H:%M}" if _my(context) else f"{local.hour % 12 or 12}:{local:%M} {'am' if local.hour < 12 else 'pm'}"
    return f"{day(context, local)}, {clock}"


templates.env.filters["local_time"] = local_time
templates.env.filters["day"] = day
templates.env.filters["when"] = when
templates.env.filters["age"] = age
from app.web.perf import static_url  # noqa: E402 (docs/SPEC-v5.3 M1)

templates.env.globals.update(static_url=static_url, format_mmk=format_mmk, size_label=size_label, now=lambda: datetime.now(UTC),
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
