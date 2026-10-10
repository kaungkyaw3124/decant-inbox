"""Services report they are alive by upserting a row in service_heartbeats."""
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.models import ServiceHeartbeat


def beat(name: str, details: str | None = None) -> None:
    now = datetime.now(UTC)
    stmt = insert(ServiceHeartbeat).values(name=name, last_seen=now, details=details)
    with SessionLocal.begin() as session:
        session.execute(stmt.on_conflict_do_update(
            index_elements=["name"], set_={"last_seen": now, "details": details}))
