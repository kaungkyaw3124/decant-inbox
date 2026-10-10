"""Telethon client factory. The Telegram account is READ-ONLY for this project:
never send, edit, delete, forward or mark messages as read (see CLAUDE.md).
tests/test_listener_readonly.py fails if listener code calls such methods."""
import os
import sys

from telethon import TelegramClient

from app.core.config import get_settings


def make_client() -> TelegramClient:
    settings = get_settings()
    if not settings.tg_api_id or not settings.tg_api_hash:
        sys.exit("Set TG_API_ID and TG_API_HASH in .env (from https://my.telegram.org).")
    session_dir = settings.tg_session_path.parent
    session_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(session_dir, 0o700)
    return TelegramClient(
        str(settings.tg_session_path),
        settings.tg_api_id,
        settings.tg_api_hash.get_secret_value(),
        catch_up=True,  # fetch updates missed while the listener was down
        device_model="Decant Inbox server",
    )


def secure_session_file() -> None:
    path = get_settings().tg_session_path.with_suffix(".session")
    if path.exists():
        os.chmod(path, 0o600)
