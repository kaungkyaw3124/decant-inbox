"""DB tests run against a separate database (<db_name>_test), never the real one."""
import os

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings

# one database per pytest-xdist worker (gw0, gw1, ...) so workers never see each other's rows
TEST_DB = get_settings().db_name + "_test" + os.environ.get("PYTEST_XDIST_WORKER", "").replace("gw", "_")
os.environ["DB_NAME"] = TEST_DB  # must be set before app.core.db is imported
os.environ["WEB_SECRET_KEY"] = "test-only-secret-key"
os.environ["AI_PROVIDER"] = "off"  # never the real AI in tests: AI tests install providers.FakeProvider
get_settings.cache_clear()

from argon2 import PasswordHasher  # noqa: E402

import app.web.auth as _auth  # noqa: E402

_auth.hasher = PasswordHasher(time_cost=1, memory_cost=64, parallelism=1)  # tests only: same API, ~1 ms not 300


@pytest.fixture(scope="session")
def migrated_db():
    from alembic import command
    from alembic.config import Config

    admin_url = get_settings().database_url.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
        # throwaway test data: do not wait for the disk on every commit (the real database is unchanged)
        c.execute(text(f'ALTER DATABASE "{TEST_DB}" SET synchronous_commit = off'))
    command.upgrade(Config("alembic.ini"), "head")
    yield
    from app.core.db import engine

    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db(migrated_db):
    from app.core.db import engine

    yield engine
    with engine.begin() as c:
        # every table empty + every id back to its start (as TRUNCATE ... RESTART IDENTITY CASCADE did:
        # no migration seeds rows except faq_entries, re-seeded below), ~3x faster than TRUNCATE
        tables = [r[0] for r in c.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"))]
        sequences = [r[0] for r in c.execute(text("SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'"))]
        c.execute(text("SET LOCAL session_replication_role = replica"))  # no FK checks while emptying
        c.execute(text("; ".join(f'DELETE FROM "{t}"' for t in tables)))
        c.execute(text("; ".join(f'ALTER SEQUENCE "{q}" RESTART' for q in sequences)))
        c.execute(text("SET LOCAL session_replication_role = DEFAULT"))
        c.execute(text("ALTER SEQUENCE order_no_seq RESTART WITH 1001"))
        c.execute(text("ALTER SEQUENCE test_order_no_seq RESTART WITH 1"))
        # faq_entries: back to the migration's seed
        from app.replies.faq import SEED

        for n, (title, keywords, answer) in enumerate(SEED, start=1):
            c.execute(text("INSERT INTO faq_entries (title, keywords, answer, sort_order) VALUES (:t, :k, :a, :n)"),
                      {"t": title, "k": keywords, "a": answer, "n": n})
