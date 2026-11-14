from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

# docs/SPEC-v5.9 B7: the pool per process (the web unit sets DB_POOL_SIZE=20 / DB_MAX_OVERFLOW=20); a full pool
# waits at most db_pool_timeout s, then raises sqlalchemy.exc.TimeoutError (counted on /health)
_s = get_settings()
engine = create_engine(_s.database_url, pool_pre_ping=True, pool_size=_s.db_pool_size,
                       max_overflow=_s.db_max_overflow, pool_timeout=_s.db_pool_timeout)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
