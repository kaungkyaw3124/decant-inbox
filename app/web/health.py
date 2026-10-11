"""Health checks, shared by /healthz (no login, status only) and /health (details)."""
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import and_, exists, func, select, text
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.models import Message, ParseResult, ServiceHeartbeat
from app.web.auth import current_user
from app.web.deps import get_db, local_time, templates
from scripts.backup_db import list_backups

router = APIRouter()

# A service is "down" if its heartbeat is older than this (they beat every 60s / 30s).
MAX_HEARTBEAT_AGE = {"listener": timedelta(minutes=3), "parser": timedelta(minutes=2)}
MAX_UNPARSED_AGE = timedelta(minutes=5)
MAX_BACKUP_AGE = timedelta(hours=26)
MIN_FREE_DISK = 0.10


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def ago(delta: timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 120:
        return f"{s}s ago"
    if s < 7200:
        return f"{s // 60} min ago"
    if s < 172800:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def run_checks(db: Session) -> list[Check]:
    now = datetime.now(UTC)
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return [Check("database", False, "cannot connect")]
    checks = [Check("database", True, "connected")]

    beats = {h.name: h for h in db.scalars(select(ServiceHeartbeat))}
    for name, max_age in MAX_HEARTBEAT_AGE.items():
        h = beats.get(name)
        if h is None:
            checks.append(Check(name, False, "never reported"))
        else:
            age = now - h.last_seen
            checks.append(Check(name, age <= max_age, f"last heartbeat {ago(age)} ({h.details or ''})"))

    has_result = exists().where(and_(ParseResult.message_id == Message.id, ParseResult.is_current))
    count, oldest = db.execute(select(func.count(), func.min(Message.created_at))
                               .where(~has_result, Message.direction == "in")).one()  # ours are never parsed
    checks.append(Check(
        "parse queue", count == 0 or now - oldest <= MAX_UNPARSED_AGE,
        "empty" if count == 0 else f"{count} waiting, oldest {ago(now - oldest)}",
    ))

    backups = list_backups()
    if not backups:
        checks.append(Check("backup", False, "no backup yet"))
    else:
        newest = backups[0]
        age = now - datetime.fromtimestamp(newest.stat().st_mtime, UTC)
        checks.append(Check("backup", age <= MAX_BACKUP_AGE,
                            f"{newest.name}, {ago(age)}, {newest.stat().st_size // 1024} KiB, {len(backups)} kept"))

    disk = shutil.disk_usage(BASE_DIR)
    free = disk.free / disk.total
    checks.append(Check("disk", free >= MIN_FREE_DISK, f"{disk.free // 2**30} GiB free ({free:.0%})"))
    return checks


@router.get("/healthz", response_class=PlainTextResponse)
def healthz(db: Session = Depends(get_db)):
    """For scripts/monitors: 200 if everything is fine, else 503. Names and status only."""
    checks = run_checks(db)
    body = "\n".join(f"{c.name}: {'ok' if c.ok else 'FAIL'}" for c in checks)
    return PlainTextResponse(body + "\n", status_code=200 if all(c.ok for c in checks) else 503)


@router.get("/health", response_class=HTMLResponse, dependencies=[Depends(current_user)])
def health(request: Request, db: Session = Depends(get_db)):
    last = db.scalar(select(func.max(Message.received_at)))
    return templates.TemplateResponse(request, "health.html", {
        "checks": run_checks(db), "last_message": local_time(last, "%d %b %Y %H:%M") if last else "none yet",
        "total": db.scalar(select(func.count()).select_from(Message)),
    })
