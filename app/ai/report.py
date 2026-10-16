"""Numbers for the AI page and the "Needs you" notices (docs/SPEC-v4.6-ai.md S5)."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import providers
from app.ai import settings as ai_settings
from app.ai.service import CALL_KINDS, _day_start, calls_today, cost_this_month
from app.core.config import BASE_DIR, get_settings
from app.models import AICall, QuickAction

EXPORTS = BASE_DIR / "data" / "exports"
LATEST_EVAL = EXPORTS / "ai_eval_latest.json"
EVAL_LOG = EXPORTS / "ai_eval_run.log"
EVAL_RUNNING = EXPORTS / "ai_eval.running"
ERROR_WINDOW = 20  # last calls looked at for "many errors"
ERROR_RATE = 0.5
FATAL = {"auth": "the API key was refused (check OPENAI_API_KEY in .env)",
         "quota": "no credit left: add credit in OpenAI Billing",
         "country": "OpenAI refuses this country / region"}


@dataclass
class Period:
    calls: int
    cost: float
    latency_ms: int
    accepted: int
    corrected: int
    auto: int
    errors: int
    rejected: int
    skipped: int  # cap / budget: not called
    saved: int  # messages answered with learned patterns (no AI call needed)

    @property
    def accuracy(self) -> int | None:
        done = self.accepted + self.corrected
        return round(100 * self.accepted / done) if done else None


def period(session: Session, since: datetime) -> Period:
    rows = dict(session.execute(select(AICall.decision, func.count()).where(AICall.created_at >= since)
                                .group_by(AICall.decision)).all())
    cost, latency = session.execute(select(
        func.coalesce(func.sum(AICall.cost_usd), 0),
        func.coalesce(func.avg(AICall.latency_ms).filter(AICall.ok), 0)).where(AICall.created_at >= since)).one()
    saved = session.scalar(select(func.count()).select_from(QuickAction).where(
        QuickAction.undone_at.is_(None), QuickAction.created_at >= since, QuickAction.undo.has_key("learned")))
    return Period(sum(rows.get(k, 0) for k in CALL_KINDS), float(cost), int(latency), rows.get("accepted", 0),
                  rows.get("corrected", 0), rows.get("auto", 0), rows.get("error", 0), rows.get("rejected", 0),
                  rows.get("cap", 0) + rows.get("budget", 0), saved or 0)


def notices(session: Session, now: datetime) -> list[str]:
    """Problems the owner should know about (shown on Needs you and the AI page)."""
    cfg = ai_settings.load(session)
    if cfg["mode"] == "off":
        return []
    out = []
    s = get_settings()
    if s.ai_provider == "openai" and providers.get() is None:
        out.append("🧠 AI is on, but OPENAI_API_KEY is missing in .env. Messages go to Needs you as before.")
        return out
    last = session.execute(select(AICall.decision, AICall.error).where(
        AICall.decision.in_(("shadow", "accepted", "corrected", "auto", "rejected", "error")))
        .order_by(AICall.id.desc()).limit(ERROR_WINDOW)).all()
    if last and last[0][0] == "error" and (last[0][1] or "") in FATAL:
        out.append(f"🧠 AI stopped working: {FATAL[last[0][1]]}. Messages go to Needs you as before.")
    elif len(last) >= 5 and sum(d == "error" for d, _ in last) / len(last) >= ERROR_RATE:
        errors = sum(d == "error" for d, _ in last)
        out.append(f"🧠 AI: {errors} of the last {len(last)} calls failed (network / API). See the AI page.")
    if calls_today(session, now) >= cfg["daily_cap"]:
        out.append(f"🧠 AI: daily limit of {cfg['daily_cap']} calls reached. Until tomorrow, unsure messages go to "
                   "Needs you without AI help.")
    if cost_this_month(session, now) >= cfg["monthly_budget_usd"]:
        out.append(f"🧠 AI: monthly budget of ${cfg['monthly_budget_usd']:.2f} used up. Raise it on the AI page, or "
                   "wait for next month.")
    return out


def recent(session: Session, limit: int = 50) -> list[AICall]:
    return list(session.scalars(select(AICall).order_by(AICall.id.desc()).limit(limit)))


def latest_eval() -> dict | None:
    try:
        return json.loads(LATEST_EVAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def eval_running(now: datetime) -> bool:
    try:
        started = datetime.fromisoformat(EVAL_RUNNING.read_text().strip())
    except (OSError, ValueError):
        return False
    return now - started < timedelta(minutes=10)


def today_start(now: datetime) -> datetime:
    return _day_start(now)


def month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)
