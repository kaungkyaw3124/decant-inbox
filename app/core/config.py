"""Settings from environment / .env. Secrets live only in .env (never committed)."""
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    db_host: str = "127.0.0.1"  # inside compose, services set DB_HOST=postgres
    db_port: int = 5432
    db_name: str = "product_requests"
    db_user: str = "appuser"
    db_password: SecretStr

    # Telegram (Phase 2). Optional here so DB-only scripts run without them.
    tg_api_id: int | None = None
    tg_api_hash: SecretStr | None = None
    tg_session_path: Path = BASE_DIR / "secrets" / "telegram"  # Telethon adds ".session"

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
