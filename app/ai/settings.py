"""AI settings the owner changes on the AI page (app_settings "ai"); defaults from .env."""
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting, User

SETTING = "ai"
MODES = ("off", "shadow", "auto")
REASONING = ("low", "medium", "high")
LIMITS = {"daily_cap": (0, 5000), "monthly_budget_usd": (0.0, 500.0), "threshold": (0.5, 1.0),
          "min_days": (1, 60), "min_decisions": (1, 1000), "min_accuracy": (0.5, 1.0)}


def defaults() -> dict:
    s = get_settings()
    return {"mode": "shadow", "daily_cap": 300, "monthly_budget_usd": 5.0, "threshold": 0.85,
            "model": s.ai_model, "reasoning": s.ai_reasoning,
            # docs/SPEC-v4.7-graduation.md: SHADOW -> AUTO by itself when the numbers are good enough
            "auto_graduate": True, "min_days": 7, "min_decisions": 50, "min_accuracy": 0.95,
            "shadow_since": None,  # ISO time SHADOW (re)started: the graduation window
            # docs/SPEC-v4.12-address-payment-ai.md privacy switches (owner, /ai): addresses go to the AI
            # (phones stay masked, names never sent); payment screenshots go to the AI (off until the owner
            # turns it on)
            "ai_address": True, "ai_screenshot": False,
            "screenshot_check": None}  # scripts/ai_screens_check.py: {model, ok, at, detail}


def load(session: Session) -> dict:
    row = session.get(AppSetting, SETTING)
    return {**defaults(), **(row.value if row else {})}


def mode(session: Session) -> str:
    return load(session)["mode"]


def save(session: Session, values: dict, user: User | None) -> None:
    """ValueError with a sentence for the owner when a value is out of range."""
    value = {**load(session), **values}
    if value["mode"] not in MODES:
        raise ValueError("Mode: off, shadow or auto.")
    if value["reasoning"] not in REASONING:
        raise ValueError("Reasoning: low, medium or high.")
    if not str(value["model"]).strip() or len(str(value["model"])) > 64:
        raise ValueError("Model name missing.")
    for key, (low, high) in LIMITS.items():
        if not low <= float(value[key]) <= high:
            raise ValueError(f"{key.replace('_', ' ')} must be {low}-{high}.")
    value["daily_cap"] = int(value["daily_cap"])
    value["min_days"], value["min_decisions"] = int(value["min_days"]), int(value["min_decisions"])
    value["min_accuracy"] = round(float(value["min_accuracy"]), 3)
    value["auto_graduate"] = bool(value["auto_graduate"])
    value["ai_address"], value["ai_screenshot"] = bool(value["ai_address"]), bool(value["ai_screenshot"])
    value["monthly_budget_usd"] = round(float(value["monthly_budget_usd"]), 2)
    value["threshold"] = round(float(value["threshold"]), 2)
    stmt = insert(AppSetting).values(key=SETTING, value=value, updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))
