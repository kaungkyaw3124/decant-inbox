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

    # Dashboard (Phase 4). Secret signs the session cookie; generate with
    # python -c "import secrets; print(secrets.token_urlsafe(48))"
    web_secret_key: SecretStr | None = None
    web_cookie_secure: bool = True  # HTTPS via the Cloudflare tunnel (localhost over SSH also counts)
    timezone: str = "Asia/Yangon"

    # AI helper (docs/SPEC-v4.6-ai.md). The key lives only in .env; never print or log it.
    openai_api_key: SecretStr | None = None
    ai_provider: str = "openai"  # openai | off
    ai_model: str = "gpt-6-luna"
    ai_reasoning: str = "low"  # low | medium | high
    ai_timeout_s: float = 8.0
    # USD per 1M tokens (gpt-6-luna); cost per call = tokens x these prices
    ai_price_in: float = 0.10
    ai_price_cached_in: float = 0.01
    ai_price_out: float = 0.50

    # docs/SPEC-v4.14-test-payment-code.md: secret code the owner's test account sends instead of a payment
    # screenshot. Empty = feature off. Never print or log it.
    test_pay_code: SecretStr | None = None

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
