"""docs/SPEC-v5.4-ui-ux-cleanup.md X2: one pager for every long list.

The server pages with LIMIT/OFFSET + a COUNT (never loads all rows); `?page=&per=` stays in the URL (Back and
links work). A `per` from the URL is remembered in a small cookie (only the number, nothing else), so the next
list opens with the same size. Templates show it with the `pager` macro in _ui.html.
"""
from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

PER_CHOICES = (10, 20, 50, 100)
COOKIE = "per"


@dataclass
class Page:
    items: list
    total: int
    page: int
    per: int
    request: Request
    key: str = "page"  # the URL parameter (two lists on one page use two keys)

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per))

    @property
    def first(self) -> int:
        return (self.page - 1) * self.per + 1 if self.total else 0

    @property
    def last(self) -> int:
        return min(self.page * self.per, self.total)

    def numbers(self) -> list[int | None]:
        """1 … 4 5 6 … 20 (None = ellipsis): first, last and the two next to the current page."""
        keep = {1, self.pages, *range(self.page - 1, self.page + 2)}
        out: list[int | None] = []
        for n in range(1, self.pages + 1):
            if n in keep:
                out.append(n)
            elif out and out[-1] is not None:
                out.append(None)
        return out

    def url(self, **changes) -> str:
        """This list's URL with page / per changed; search, tab and other filters stay."""
        if "page" in changes:
            changes[self.key] = changes.pop("page")
        params = dict(self.request.query_params) | {k: str(v) for k, v in changes.items()}
        if "per" in changes:
            params.pop(self.key, None)  # a new size starts at page 1
        return f"{self.request.url.path}?{urlencode(params)}"


def _number(value: str | None) -> int | None:
    """Digits only; a huge number becomes 10**9 (a page past the end = the last page)."""
    return min(int(value[:10]), 10**9) if value and value.isascii() and value.isdigit() else None


def per_of(request: Request, default: int = 20) -> int:
    for value in (request.query_params.get("per"), request.cookies.get(COOKIE)):
        if _number(value) in PER_CHOICES:
            return int(value)
    return default


def paginate(db: Session, query: Select, request: Request, default: int = 20, scalars: bool = False,
             key: str = "page") -> Page:
    """query: the full ordered SELECT. A page number past the end shows the last page."""
    per = per_of(request, default)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    page = min(max(_number(request.query_params.get(key)) or 1, 1), max(1, -(-total // per)))
    rows = db.execute(query.limit(per).offset((page - 1) * per))
    return Page(rows.scalars().all() if scalars else rows.all(), total, page, per, request, key)


async def remember_per(request: Request, call_next):
    """Middleware: a valid ?per= becomes the default for the next lists (cookie, 1 year, number only)."""
    response = await call_next(request)
    per = _number(request.query_params.get("per"))
    if per in PER_CHOICES and request.cookies.get(COOKIE) != str(per):
        response.set_cookie(COOKIE, str(per), max_age=31536000, path="/", httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
    return response
