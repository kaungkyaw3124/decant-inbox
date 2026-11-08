"""docs/SPEC-v5.7-date-filter-and-light-chat.md A: one date filter for the list pages (like the 5.4 pager).

`?range=today|yesterday|7d|30d|all` or `?from=YYYY-MM-DD&to=YYYY-MM-DD`, in the SHOP's days (Asia/Yangon, from
settings.timezone): "Today" starts at 00:00 Yangon time. Broken dates never give an error page: reversed dates are
swapped, unreadable ones are ignored (with a note). Templates show it with the `date_chips` macro in _ui.html.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import true
from starlette.requests import Request

from app.orders import sales

CHIPS = (("today", "Today"), ("yesterday", "Yesterday"), ("7d", "7 days"), ("30d", "30 days"), ("all", "All time"))
MAX_DAYS = 3660  # a picked range longer than 10 years is cut (keeps the query sane)


@dataclass
class DateRange:
    key: str  # today | yesterday | 7d | 30d | all | custom
    first: date | None  # None = all time
    last: date | None
    request: Request
    default: str = "all"
    note: str = ""  # shown when the dates in the URL could not be used

    @property
    def active(self) -> bool:
        return self.key != self.default

    @property
    def bounds(self) -> tuple[datetime, datetime] | None:
        """UTC [start, end) of the chosen Yangon days, None = all time."""
        return None if self.first is None else sales.bounds(self.first, self.last)

    def where(self, column):
        """SQL condition: column inside the chosen days (always true for All time)."""
        if self.bounds is None:
            return true()
        start, end = self.bounds
        return (column >= start) & (column < end)

    def url(self, key: str | None = None, **changes) -> str:
        """This page's URL with another range (filters and tab stay; the page goes back to 1)."""
        params = {k: v for k, v in self.request.query_params.items() if k not in ("range", "from", "to", "page")}
        if key and key != self.default:
            params["range"] = key
        params |= {k: str(v) for k, v in changes.items()}
        return f"{self.request.url.path}" + (f"?{urlencode(params)}" if params else "")

    def keep(self) -> list[tuple[str, str]]:
        """Hidden fields for the Pick dates form: every filter except the range and the page."""
        return [(k, v) for k, v in self.request.query_params.multi_items() if k not in ("range", "from", "to", "page")]

    @property
    def query(self) -> str:
        """The range as URL parameters, for links that change something else (tabs, toggles); "" = the default."""
        if self.key == "custom":
            return urlencode({"from": self.first.isoformat(), "to": self.last.isoformat()})
        return f"range={self.key}" if self.active else ""


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def date_range(request: Request, default: str = "all", today: date | None = None) -> DateRange:
    q = request.query_params
    d = today or sales.today()
    if q.get("from") or q.get("to"):
        first, last = _day(q.get("from", "")), _day(q.get("to", ""))
        if first or last:
            first, last = first or last, last or first
            first, last = min(first, last), max(first, last)
            return DateRange("custom", max(first, last - timedelta(days=MAX_DAYS)), last, request, default)
        note = "Those dates could not be read, so all dates are shown."
        return DateRange(default, *_resolve(default, d), request, default, note)
    key = q.get("range", default)
    key = key if key in dict(CHIPS) else default
    return DateRange(key, *_resolve(key, d), request, default)


def _resolve(key: str, d: date) -> tuple[date | None, date | None]:
    return {"today": (d, d), "yesterday": (d - timedelta(days=1), d - timedelta(days=1)),
            "7d": (d - timedelta(days=6), d), "30d": (d - timedelta(days=29), d)}.get(key, (None, None))
