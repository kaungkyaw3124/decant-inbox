"""DB tests run against a separate database (<db_name>_test), never the real one."""
import os

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings

TEST_DB = get_settings().db_name + "_test"
os.environ["DB_NAME"] = TEST_DB  # must be set before app.core.db is imported
os.environ["WEB_SECRET_KEY"] = "test-only-secret-key"
get_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated_db():
    from alembic import command
    from alembic.config import Config

    admin_url = get_settings().database_url.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
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
        c.execute(text("TRUNCATE products, product_aliases, customers, messages, users, service_heartbeats RESTART IDENTITY CASCADE"))
