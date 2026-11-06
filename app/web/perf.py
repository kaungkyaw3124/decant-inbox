"""docs/SPEC-v5.3-performance-pc.md M0/M1: page timing and static-file caching.

- Server-Timing header on every response: db (SQL time), app (the rest: Python + templates), total, in ms.
- A request slower than SLOW_MS is logged with its ROUTE only (the path template, never ids or search text).
- The last times per route are kept in memory for /health -> Speed.
- static_url(): /static/<file>?v=<content hash>, so a changed file gets a new URL and every URL can be cached
  by the browser for a year.
"""
import hashlib
import logging
import time
from collections import defaultdict, deque
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from sqlalchemy import event

from app.core.db import engine

log = logging.getLogger("perf")
SLOW_MS = 300
STATIC = Path(__file__).parent / "static"
_db_ms: ContextVar[list[float] | None] = ContextVar("db_ms", default=None)
# shortcut: per process and lost on restart; move to a table if the numbers must survive restarts
_times: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=200))


@event.listens_for(engine, "before_cursor_execute")
def _start(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("t0", []).append(time.perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def _stop(conn, cursor, statement, parameters, context, executemany):
    started = conn.info["t0"].pop()
    total = _db_ms.get()
    if total is not None:  # sync routes run in a thread that got a copy of the request's context
        total[0] += (time.perf_counter() - started) * 1000


async def timing(request, call_next):
    total_db = [0.0]
    token = _db_ms.set(total_db)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        _db_ms.reset(token)
    ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = (f"db;dur={total_db[0]:.1f}, app;dur={ms - total_db[0]:.1f}, "
                                         f"total;dur={ms:.1f}")
    route = getattr(request.scope.get("route"), "path", None)
    if route and not route.startswith("/static"):
        _times[f"{request.method} {route}"].append(ms)
        if ms > SLOW_MS:
            log.warning("slow request: %s %s %.0f ms (db %.0f ms)", request.method, route, ms, total_db[0])
    return response


def summary() -> list[dict]:
    """Per route: n, p50, p90, max in ms, slowest p90 first (for /health)."""
    rows = []
    for route, times in list(_times.items()):
        ordered = sorted(times)
        rows.append({"route": route, "n": len(ordered), "p50": ordered[len(ordered) // 2],
                     "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], "max": ordered[-1]})
    return sorted(rows, key=lambda r: -r["p90"])


@lru_cache(maxsize=None)
def static_url(name: str) -> str:
    """Files only change with a deploy (= restart), so the hash is computed once per process."""
    digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={digest}"


def cache_control(request) -> str:
    """Versioned static files (?v= or a versioned vendor folder) never change: keep for a year.
    Other static files: keep but check first (ETag). Everything else may hold customer data: never store."""
    path = request.url.path
    if path.startswith("/static/"):
        if "v" in request.query_params or path.startswith("/static/vendor/"):
            return "public, max-age=31536000, immutable"
        return "no-cache"
    return "no-store"
