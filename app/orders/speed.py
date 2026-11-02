"""docs/SPEC-v4.18-speed.md S0: how fast the bot's first reply reaches a customer, per stage.

No new table: every stage already has a timestamp — messages.received_at (Telegram date) and created_at (saved),
parse_results.created_at (parsed), ai_calls.created_at - latency_ms (AI started / finished), auto_runs.created_at
(decided), outbox.created_at (queued) and sent_at (sent). So the numbers exist for the past too ("before").
First reply = the first outbox row the BOT made for the customer after the message (a person's reply is not
counted). Paths: "holding" (the please-wait reply), "ai" (an AI call was made), else "rules". Numbers only.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_TOTAL = timedelta(minutes=10)  # slower = an outage / history import, not a speed sample
STAGES = ("saved", "parsed", "ai", "decided", "queued", "sent")


@dataclass
class Timing:
    message_id: int
    path: str
    total: float  # seconds, Telegram date -> sent
    stages: dict[str, float]  # stage -> seconds since the previous stage

    @property
    def slowest(self) -> str:
        return max(self.stages, key=self.stages.get) if self.stages else "-"


SQL = text("""
SELECT m.id, m.received_at AS tg, m.created_at AS saved,
       (SELECT min(p.created_at) FROM parse_results p WHERE p.message_id = m.id) AS parsed,
       a.created_at - make_interval(secs => coalesce(a.latency_ms, 0) / 1000.0) AS ai_start, a.created_at AS ai_done,
       r.created_at AS decided, o.created_at AS queued, o.sent_at AS sent, o.reply_kind
FROM messages m
JOIN LATERAL (SELECT * FROM outbox o WHERE o.customer_id = m.customer_id AND o.created_by IS NULL
              AND o.created_at >= m.created_at AND o.status = 'sent' ORDER BY o.created_at, o.id LIMIT 1) o ON true
LEFT JOIN ai_calls a ON a.message_id = m.id
LEFT JOIN auto_runs r ON r.message_id = m.id
WHERE m.direction = 'in' AND m.received_at >= :since AND m.received_at < :until
  AND o.sent_at - m.received_at < :most
  AND NOT EXISTS (SELECT 1 FROM messages n WHERE n.customer_id = m.customer_id AND n.direction = 'in'
                  AND n.received_at > m.received_at AND n.received_at <= o.created_at)
ORDER BY m.id""")


def timings(session: Session, since: datetime, until: datetime) -> list[Timing]:
    """One Timing per customer message the bot answered first (the last message of a burst only)."""
    found = []
    for row in session.execute(SQL, {"since": since, "until": until, "most": MAX_TOTAL}).mappings():
        path = "holding" if row["reply_kind"] in ("holding", "hold") else "ai" if row["ai_done"] else "rules"
        points = [("saved", row["saved"]), ("parsed", row["parsed"]), ("ai", row["ai_done"]),
                  ("decided", row["decided"]), ("queued", row["queued"]), ("sent", row["sent"])]
        stages, before = {}, row["tg"]
        for name, at in points:
            if at is None or at > row["sent"]:  # e.g. the decision logged after a holding reply went out
                continue
            stages[name] = max((at - before).total_seconds(), 0.0)
            before = max(before, at)
        found.append(Timing(row["id"], path, (row["sent"] - row["tg"]).total_seconds(), stages))
    return found


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0-100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(p / 100 * len(ordered)) - 1))]


def summary(session: Session, since: datetime, until: datetime) -> dict:
    """{"paths": {path: {"n", "p50", "p90", "max"}}, "slowest": [Timing x5]}"""
    rows = timings(session, since, until)
    paths = {}
    for path in ("rules", "ai", "holding"):
        totals = [r.total for r in rows if r.path == path]
        paths[path] = {"n": len(totals), "p50": percentile(totals, 50), "p90": percentile(totals, 90),
                       "max": max(totals) if totals else None}
    return {"paths": paths, "slowest": sorted(rows, key=lambda r: -r.total)[:5]}
