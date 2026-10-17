"""docs/SPEC-v4.11-ai-first.md L1 (data step, run once at deploy): AI mode = AUTO now, auto-graduate
OFF (the owner skipped the SHADOW period). The safety brake (docs/SPEC-v4.7-graduation.md) stays on:
a wrong product on an AUTO message, accuracy < 90% on the last 30, or errors >= 50% of the last 20
puts it back to SHADOW with a notice. Safe to run again (nothing changes when already done).

Usage: .venv/bin/python -m scripts.ai_auto_now
"""
from datetime import UTC, datetime

from app.ai import settings as ai_settings
from app.core.db import SessionLocal
from app.models import AuditLog


def switch(session, now: datetime | None = None) -> bool:
    """True when it changed something."""
    now = now or datetime.now(UTC)
    cfg = ai_settings.load(session)
    if cfg["mode"] == "auto" and cfg.get("skipped_shadow") and not cfg["auto_graduate"]:
        return False
    ai_settings.save(session, {"mode": "auto", "auto_graduate": False, "auto_since": now.isoformat(),
                               "skipped_shadow": True}, None)
    session.add(AuditLog(user_id=None, action="ai.mode", details={
        "actor": "deploy (owner decision 2026-10-17: AI-first, skip SHADOW)",
        "before": {"mode": cfg["mode"], "auto_graduate": cfg["auto_graduate"]},
        "after": {"mode": "auto", "auto_graduate": False}}))
    return True


def main() -> None:
    with SessionLocal.begin() as session:
        changed = switch(session)
        cfg = ai_settings.load(session)
    print(f"AI mode: {cfg['mode']}, auto-graduate: {'ON' if cfg['auto_graduate'] else 'OFF'}, since "
          f"{cfg.get('auto_since')}" + ("" if changed else " (already set, nothing changed)"))


if __name__ == "__main__":
    main()
