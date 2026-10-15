"""audit_log helper: who did what (docs/SPEC-v4.md 4.4: every dashboard action names its user)."""
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(session: Session, user: User | None, action: str, **details) -> None:
    """user None = done by the system (auto mode, the worker)."""
    session.add(AuditLog(user_id=user.id if user else None, action=action, details=details))
