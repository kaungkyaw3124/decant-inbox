"""SHADOW -> AUTO graduation, the safety brake back to SHADOW, and the weekly AI summary
(docs/SPEC-v4.7-graduation.md).

Graduation (daily at 09:00 Asia/Yangon, parser worker): SHADOW + auto-graduate ON + at least
min_days since SHADOW (re)started + at least min_decisions accepted/corrected suggestions in the
window + accuracy >= min_accuracy + ZERO wrong products + error rate < 10% over 7 days.
The window = the last 14 days, but never before SHADOW (re)started.

Safety brake (after every decided AI call, after every AI step, and daily): AUTO goes back to
SHADOW when an admin changes the product of an AUTO-handled AI message, when the last 30
decided results are < 90% right (AUTO results count as right until someone corrects them), or
when >= 50% of the last 20 calls failed. The window restarts at the brake time.

"Wrong product" = the AI named a product and the admin chose a different one (or "we don't sell
it"). The AI saying "we don't sell it" and the admin choosing a product is a normal correction.

Weekly summary (Mondays from 09:00 Yangon): reports/ai-weekly.md with AGGREGATE NUMBERS ONLY (no
message text, no names, no phones), committed alone and pushed with the deploy key.
"""
import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai import settings as ai_settings
from app.ai.service import CALL_KINDS
from app.core.config import BASE_DIR, get_settings
from app.core.db import SessionLocal
from app.models import AICall, AppSetting, AuditLog, LearnedPattern, ParseResult, User

log = logging.getLogger("ai.graduation")
ACCURACY_WINDOW = timedelta(days=14)
ERROR_WINDOW = timedelta(days=7)
MAX_ERROR_RATE = 0.10
BRAKE_LAST_DECISIONS = 30
BRAKE_MIN_ACCURACY = 0.90
BRAKE_LAST_CALLS = 20
BRAKE_ERROR_RATE = 0.50
RUN_AT = time(9, 0)  # Asia/Yangon
NOTICE_FOR = timedelta(days=3)
STATE = "ai_graduation"  # app_settings: last daily check / last weekly summary
SUMMARY = Path("reports") / "ai-weekly.md"
DECIDED = ("accepted", "corrected")


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def _iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def shadow_since(session: Session, cfg: dict, now: datetime) -> datetime:
    """When SHADOW (re)started. Missing (older installs): starts now and is saved."""
    since = _iso(cfg.get("shadow_since"))
    if since is None:
        since = now
        ai_settings.save(session, {"shadow_since": now.isoformat()}, None)
    return since


# ---------- recording decisions ----------

def record_decision(session: Session, call: AICall, decision: str, user: User | None, wrong_product: bool,
                    now: datetime | None = None) -> str | None:
    """An admin accepted / corrected an AI result. Returns the brake reason if it fired."""
    now = now or datetime.now(UTC)
    was_auto = call.decision == "auto"
    call.decision, call.decided_by, call.decided_at = decision, user.id if user else None, now
    call.wrong_product = bool(wrong_product and decision == "corrected")
    session.flush()
    if was_auto and call.wrong_product and ai_settings.mode(session) == "auto":
        return brake(session, "an admin changed the product of an AUTO-handled message", now)
    return check_brake(session, now)


# ---------- graduation ----------

@dataclass
class Condition:
    key: str
    label: str  # English (translated in the page)
    value: str
    status: str  # ok | wait | fail
    missing: str = ""

    @property
    def icon(self) -> str:
        return {"ok": "✅", "wait": "⏳", "fail": "❌"}[self.status]


@dataclass
class Progress:
    mode: str
    auto_graduate: bool
    since: datetime
    days: int
    decisions: int
    accepted: int
    corrected: int
    wrong_products: int
    error_rate: float
    conditions: list[Condition]

    @property
    def ready(self) -> bool:
        return all(c.status == "ok" for c in self.conditions)

    @property
    def accuracy(self) -> float | None:
        return self.accepted / self.decisions if self.decisions else None


def progress(session: Session, now: datetime | None = None) -> Progress:
    now = now or datetime.now(UTC)
    cfg = ai_settings.load(session)
    since = shadow_since(session, cfg, now)
    start = max(since, now - ACCURACY_WINDOW)
    # after the start: the correction that fired a brake belongs to the old window
    rows = dict(session.execute(select(AICall.decision, func.count()).where(
        AICall.decision.in_(DECIDED), AICall.decided_at > start).group_by(AICall.decision)).all())
    accepted, corrected = rows.get("accepted", 0), rows.get("corrected", 0)
    decisions = accepted + corrected
    wrong = session.scalar(select(func.count()).select_from(AICall).where(
        AICall.wrong_product, AICall.decided_at > start)) or 0
    calls, failed = session.execute(select(
        func.count().filter(AICall.decision.in_(CALL_KINDS)),
        func.count().filter(AICall.decision.in_(("error", "rejected")))).where(
        AICall.created_at >= now - ERROR_WINDOW)).one()
    error_rate = failed / calls if calls else 0.0
    days = (now - since).days
    min_days, min_decisions, min_accuracy = cfg["min_days"], cfg["min_decisions"], cfg["min_accuracy"]
    accuracy = accepted / decisions if decisions else None
    conditions = [
        Condition("days", "Days in SHADOW", f"{days} / {min_days}", "ok" if days >= min_days else "wait",
                  "" if days >= min_days else f"{min_days - days} more days"),
        Condition("decisions", "Checked AI suggestions (14 days)", f"{decisions} / {min_decisions}",
                  "ok" if decisions >= min_decisions else "wait",
                  "" if decisions >= min_decisions else f"{min_decisions - decisions} more checked suggestions"),
        Condition("accuracy", "Accuracy (14 days)", "–" if accuracy is None else f"{accuracy:.0%} / {min_accuracy:.0%}",
                  "wait" if accuracy is None else "ok" if accuracy >= min_accuracy else "fail",
                  "" if accuracy is not None and accuracy >= min_accuracy else f"accuracy must reach {min_accuracy:.0%}"),
        Condition("wrong", "Wrong products (14 days)", str(wrong), "ok" if wrong == 0 else "fail",
                  "" if wrong == 0 else "no wrong product allowed in 14 days"),
        Condition("errors", "Errors (7 days)", f"{error_rate:.0%} / under {MAX_ERROR_RATE:.0%}",
                  "ok" if error_rate < MAX_ERROR_RATE else "fail",
                  "" if error_rate < MAX_ERROR_RATE else f"errors must be under {MAX_ERROR_RATE:.0%}"),
    ]
    return Progress(cfg["mode"], cfg["auto_graduate"], since, days, decisions, accepted, corrected, wrong,
                    error_rate, conditions)


def graduate_if_ready(session: Session, now: datetime | None = None) -> str | None:
    """SHADOW -> AUTO when every condition is met. Returns the notice, or None."""
    now = now or datetime.now(UTC)
    cfg = ai_settings.load(session)
    if cfg["mode"] != "shadow" or not cfg["auto_graduate"]:
        return None
    p = progress(session, now)
    if not p.ready:
        return None
    notice = (f"🧠 AI switched to AUTO: accuracy {p.accuracy:.0%} on {p.decisions} decisions, "
              f"{p.wrong_products} wrong products")
    ai_settings.save(session, {"mode": "auto", "auto_since": now.isoformat()}, None)
    session.add(AuditLog(user_id=None, action="ai.graduated", details={
        "actor": "auto-graduation", "notice": notice, "accuracy": round(p.accuracy, 4), "decisions": p.decisions,
        "wrong_products": p.wrong_products, "error_rate": round(p.error_rate, 4), "days": p.days}))
    log.info("AI graduated to AUTO (%d decisions, %.1f%%)", p.decisions, 100 * p.accuracy)
    return notice


# ---------- safety brake ----------

def brake(session: Session, reason: str, now: datetime) -> str:
    notice = f"🧠 AI switched back to SHADOW: {reason}"
    ai_settings.save(session, {"mode": "shadow", "shadow_since": now.isoformat(), "auto_since": None}, None)
    session.add(AuditLog(user_id=None, action="ai.brake", details={
        "actor": "auto-graduation", "notice": notice, "reason": reason}))
    log.warning("AI brake: back to SHADOW (%s)", reason)
    return reason


def check_brake(session: Session, now: datetime | None = None) -> str | None:
    """AUTO -> SHADOW if a brake condition holds. Returns the reason, or None."""
    now = now or datetime.now(UTC)
    cfg = ai_settings.load(session)
    if cfg["mode"] != "auto":
        return None
    since = _iso(cfg.get("auto_since")) or shadow_since(session, cfg, now)
    auto_handled = exists().where(ParseResult.message_id == AICall.message_id, ParseResult.method == "ai")
    if session.scalar(select(exists().where(AICall.wrong_product, AICall.decided_at >= since, auto_handled))):
        return brake(session, "an admin changed the product of an AUTO-handled message", now)
    start = shadow_since(session, cfg, now)
    last = session.scalars(select(AICall.decision).where(
        AICall.decision.in_((*DECIDED, "auto")), AICall.decided_at > start)
        .order_by(AICall.decided_at.desc(), AICall.id.desc()).limit(BRAKE_LAST_DECISIONS)).all()
    if len(last) >= BRAKE_LAST_DECISIONS:
        right = sum(d != "corrected" for d in last) / len(last)
        if right < BRAKE_MIN_ACCURACY:
            return brake(session, f"accuracy {right:.0%} on the last {len(last)} decided AI results", now)
    calls = session.scalars(select(AICall.decision).where(AICall.decision.in_(CALL_KINDS))
                            .order_by(AICall.id.desc()).limit(BRAKE_LAST_CALLS)).all()
    if len(calls) >= BRAKE_LAST_CALLS:
        rate = sum(d in ("error", "rejected") for d in calls) / len(calls)
        if rate >= BRAKE_ERROR_RATE:
            return brake(session, f"{rate:.0%} of the last {len(calls)} AI calls failed", now)
    return None


def manual_switch(session: Session, mode: str, user: User, now: datetime | None = None) -> None:
    """The owner chose a mode by hand: auto-graduate goes OFF until the owner turns it on again."""
    now = now or datetime.now(UTC)
    values = {"mode": mode, "auto_graduate": False}
    if mode == "shadow":
        values["shadow_since"] = now.isoformat()
    if mode == "auto":
        values["auto_since"] = now.isoformat()
    ai_settings.save(session, values, user)


def notices(session: Session, now: datetime) -> list[str]:
    """Graduation / brake notices of the last 3 days (newest first)."""
    rows = session.scalars(select(AuditLog).where(AuditLog.action.in_(("ai.graduated", "ai.brake")),
                                                  AuditLog.created_at >= now - NOTICE_FOR)
                           .order_by(AuditLog.id.desc()).limit(1))
    return [r.details["notice"] for r in rows if r.details.get("notice")]


# ---------- the worker's daily / weekly tick ----------

def report_week(now: datetime) -> tuple[date, date]:
    """The last full Monday-Sunday week (Yangon) before the most recent Monday 09:00."""
    local = now.astimezone(_tz())
    monday = local.date() - timedelta(days=local.weekday())
    if local.time() < RUN_AT and local.weekday() == 0:
        monday -= timedelta(days=7)
    return monday - timedelta(days=7), monday - timedelta(days=1)


def _state(session: Session) -> dict:
    row = session.get(AppSetting, STATE)
    return dict(row.value) if row else {}


def _save_state(session: Session, value: dict) -> None:
    stmt = insert(AppSetting).values(key=STATE, value=value)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_at": func.now()}))


_seen: dict[str, str] = {}  # in-process: what this worker already did (saves a query every second)


def tick(now: datetime | None = None, publish_fn=None) -> list[str]:
    """Called by the parser worker every loop. Returns what it did (for the log)."""
    now = now or datetime.now(UTC)
    local = now.astimezone(_tz())
    today = local.date().isoformat()
    week_start, _ = report_week(now)
    week = week_start.isoformat()
    if _seen.get("weekly") == week and (_seen.get("daily") == today or local.time() < RUN_AT):
        return []  # nothing due (no database work every second)
    done = []
    with SessionLocal.begin() as session:
        state = _state(session)
        before = dict(state)
        if state.get("last_daily") != today and local.time() >= RUN_AT:
            if notice := graduate_if_ready(session, now):
                done.append(notice)
            if reason := check_brake(session, now):
                done.append(f"brake: {reason}")
            state["last_daily"] = today
        if "last_weekly" not in state:
            state["last_weekly"] = week  # first run: start with the next week, no summary for the past
        write_week = state["last_weekly"] != week
        if write_week:
            state["last_weekly"] = week
        if state != before:
            _save_state(session, state)
        if state.get("last_daily") == today:
            _seen["daily"] = today
        _seen["weekly"] = week
        text = summary(session, now) if write_week else None
    if text is not None:
        path = BASE_DIR / SUMMARY
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        outcome = (publish_fn or publish)(BASE_DIR, SUMMARY)
        done.append(f"weekly summary {week}: {outcome}")
        log.info("AI weekly summary for the week of %s written; git: %s", week, outcome)
    return done


# ---------- weekly summary (aggregates only) ----------

def summary(session: Session, now: datetime) -> str:
    """Markdown with numbers only. Never message text, names, phones or ids of customers."""
    tz = _tz()
    first, last = report_week(now)
    start = datetime.combine(first, time(0), tz)
    end = datetime.combine(last + timedelta(days=1), time(0), tz)
    in_week = (AICall.created_at >= start) & (AICall.created_at < end)
    decided_in_week = (AICall.decided_at >= start) & (AICall.decided_at < end)
    counts = dict(session.execute(select(AICall.decision, func.count()).where(in_week)
                                  .group_by(AICall.decision)).all())
    calls = sum(counts.get(k, 0) for k in CALL_KINDS)
    cost, latency = session.execute(select(func.coalesce(func.sum(AICall.cost_usd), 0),
                                           func.coalesce(func.avg(AICall.latency_ms).filter(AICall.ok), 0))
                                    .where(in_week)).one()
    decided = dict(session.execute(select(AICall.decision, func.count()).where(
        decided_in_week, AICall.decision.in_(DECIDED)).group_by(AICall.decision)).all())
    accepted, corrected = decided.get("accepted", 0), decided.get("corrected", 0)
    wrong = session.scalar(select(func.count()).select_from(AICall).where(decided_in_week, AICall.wrong_product))
    auto_handled = session.scalar(select(func.count()).select_from(AICall).where(
        AICall.decided_at >= start, AICall.decided_at < end,
        exists().where(ParseResult.message_id == AICall.message_id, ParseResult.method == "ai")))
    pats = dict(session.execute(select(LearnedPattern.status, func.count()).where(LearnedPattern.via_ai)
                                .group_by(LearnedPattern.status)).all())
    accuracy = f"{accepted / (accepted + corrected):.0%}" if accepted + corrected else "–"
    p = progress(session, now)
    cfg = ai_settings.load(session)
    iso = first.isocalendar()
    lines = [
        "# AI weekly summary",
        "",
        "Aggregate numbers only (docs/SPEC-v4.7-graduation.md). Written by the parser worker.",
        "",
        f"- Week: {iso.year}-W{iso.week:02d} ({first.isoformat()} to {last.isoformat()}, Asia/Yangon)",
        f"- Written: {now.astimezone(tz).strftime('%Y-%m-%d %H:%M')} Asia/Yangon",
        f"- Mode now: {cfg['mode'].upper()} (auto-graduate {'ON' if cfg['auto_graduate'] else 'OFF'})",
        "",
        "| Number | This week |",
        "|---|---|",
        f"| AI calls | {calls} |",
        f"| Cost (USD) | {float(cost):.4f} |",
        f"| Average answer time (s) | {float(latency) / 1000:.1f} |",
        f"| Accepted unchanged | {accepted} |",
        f"| Corrected | {corrected} |",
        f"| Wrong products | {wrong} |",
        f"| Accuracy | {accuracy} |",
        f"| Errors / refused by the checker | {counts.get('error', 0)} / {counts.get('rejected', 0)} |",
        f"| Not called (limit / budget) | {counts.get('cap', 0) + counts.get('budget', 0)} |",
        f"| Handled automatically (AUTO) | {auto_handled} |",
        f"| Learned patterns from the AI: approved / pending (total) | {pats.get('approved', 0)} / "
        f"{pats.get('pending', 0)} |",
        "",
        "## Graduation progress (SHADOW -> AUTO)",
        "",
        *(f"- {c.icon} {c.label}: {c.value}" + (f" ({c.missing})" if c.missing else "") for c in p.conditions),
        "",
    ]
    return "\n".join(lines)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)


def publish(repo: Path, rel: Path) -> str:
    """Commit ONLY the summary file and push it (deploy key via ~/.ssh/config). Never pushes other
    work: if the branch already has local commits that are not pushed, it does nothing (a push
    would send them too). Returns what happened; never raises."""
    try:
        ahead = _git(repo, "rev-list", "--count", "@{u}..HEAD")
        if ahead.returncode != 0 or ahead.stdout.strip() != "0":
            return "skipped: the branch has local commits that are not pushed yet"
        _git(repo, "add", "--", str(rel))
        if _git(repo, "diff", "--cached", "--quiet", "--", str(rel)).returncode == 0:
            return "unchanged"
        commit = _git(repo, "commit", "--only", "-m", "AI weekly summary", "--", str(rel))
        if commit.returncode != 0:
            return "commit failed: " + (commit.stderr.strip().splitlines() or ["?"])[-1][:200]
        push = _git(repo, "push", "origin", "HEAD")
        if push.returncode != 0:
            return "push failed: " + (push.stderr.strip().splitlines() or ["?"])[-1][:200]
        return "pushed"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git failed: {type(exc).__name__}"
