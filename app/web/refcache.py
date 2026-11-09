"""docs/SPEC-v5.8 B: the shop's reference data (reply texts, products + prices, payment methods, staff names) is
read on every chat page but changes rarely. It is reused while one cheap fingerprint query says nothing
changed: max(xmin) + count per table catches inserts, updates and deletes from ANY process (listener, parser, a
test writing SQL). The fingerprint is taken once per request; any POST in this process clears the cache at once
(main.py), and an entry lives at most MAX_AGE seconds. Values are computed in their own session: cached ORM rows
are detached and shared read-only (these models have no lazy relationships).
"""
import threading
import time
from contextvars import ContextVar

from sqlalchemy import text

from app.core.db import SessionLocal

MAX_AGE = 60.0
# only what the cached values read (chat page: reply texts, products + sizes on sale, payment methods, staff names)
TABLES = ("products", "product_prices", "reply_templates", "payment_methods", "users")
_FINGERPRINT = text("SELECT " + ", ".join(
    f"(SELECT max(xmin::text::bigint) FROM {t}), (SELECT count(*) FROM {t})" for t in TABLES))
_request: ContextVar[dict | None] = ContextVar("refcache_request", default=None)
_cache: dict[str, tuple[float, tuple, object]] = {}
_lock = threading.Lock()


def once(key: str, compute):
    """compute() at most once per request (outside a request: every time)."""
    memo = _request.get()
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return memo[key]


def _fingerprint() -> tuple:
    def take() -> tuple:
        with SessionLocal() as session:
            return tuple(session.execute(_FINGERPRINT).one())
    return once("refcache", take)


def get(name: str, compute):
    """compute(session) -> value, reused while the reference tables are unchanged."""
    mark = _fingerprint()
    hit = _cache.get(name)
    if hit is not None and hit[1] == mark and time.monotonic() - hit[0] < MAX_AGE:
        return hit[2]
    with _lock:
        started = time.monotonic()
        with SessionLocal() as session:
            value = compute(session)
        _cache[name] = (started, mark, value)
        return value


def forget() -> None:
    _cache.clear()


async def per_request(request, call_next):
    """Middleware: fresh fingerprints for each request (so a change is seen by the next page at the latest)."""
    token = _request.set({})
    try:
        return await call_next(request)
    finally:
        _request.reset(token)
