"""v4.18 speed: NOTIFY on new messages and outbox rows

docs/SPEC-v4.18-speed.md S1: the parser worker LISTENs on new_message and the listener's sender on outbox, so
they wake at once instead of at the next poll (the polls stay as the fallback). Triggers, so every writer
(listener, dashboard, worker) notifies without code changes. Payload = the row id only (no text).

Revision ID: d7e4a1b9c3f2
Revises: c5d8e1f2a904
Create Date: 2026-11-02 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd7e4a1b9c3f2'
down_revision: Union[str, None] = 'c5d8e1f2a904'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
CREATE FUNCTION notify_new_message() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_notify('new_message', NEW.id::text); RETURN NULL; END $$;
CREATE TRIGGER messages_notify AFTER INSERT ON messages FOR EACH ROW WHEN (NEW.direction = 'in')
EXECUTE FUNCTION notify_new_message();
CREATE FUNCTION notify_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM pg_notify('outbox', NEW.id::text); RETURN NULL; END $$;
CREATE TRIGGER outbox_notify AFTER INSERT OR UPDATE OF status, send_after ON outbox FOR EACH ROW
WHEN (NEW.status = 'queued') EXECUTE FUNCTION notify_outbox();
""")


def downgrade() -> None:
    op.execute("""
DROP TRIGGER outbox_notify ON outbox; DROP FUNCTION notify_outbox();
DROP TRIGGER messages_notify ON messages; DROP FUNCTION notify_new_message();
""")
