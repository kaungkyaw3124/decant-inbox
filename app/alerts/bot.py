"""docs/SPEC-v5.0-go-live-pack.md G1: the owner's ALERT bot — the official Telegram Bot API over HTTPS
(api.telegram.org), NOT the shop's personal account: it never touches the Telethon session.
OFF while ALERT_BOT_TOKEN / ALERT_CHAT_ID are empty. The token is never logged (errors are logged by type only).
"""
import json
import logging
from pathlib import Path

import httpx

from app.core.config import get_settings

log = logging.getLogger("alerts")
API = "https://api.telegram.org"
MAX_FILE = 49 * 1024 * 1024  # bots may send files up to 50 MB
_transport: httpx.BaseTransport | None = None  # tests: httpx.MockTransport


class BotError(Exception):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.alert_bot_token and s.alert_bot_token.get_secret_value() and s.alert_chat_id)


def _call(method: str, data: dict, files: dict | None = None, timeout: float = 20) -> dict:
    s = get_settings()
    if not configured():
        raise BotError("alert bot is off (ALERT_BOT_TOKEN / ALERT_CHAT_ID empty)")
    url = f"{API}/bot{s.alert_bot_token.get_secret_value()}/{method}"
    try:
        with httpx.Client(timeout=timeout, transport=_transport) as client:
            r = client.post(url, data=data, files=files)
        body = r.json()
    except Exception as exc:
        raise BotError(f"{method}: {type(exc).__name__}") from None  # never the URL: it holds the token
    if not body.get("ok"):
        raise BotError(f"{method}: {body.get('error_code')} {str(body.get('description', ''))[:100]}")
    return body["result"]


def send(text: str, button: tuple[str, str] | None = None) -> None:
    """A message to the owner; button = (label, https url) opens the dashboard (no actions from the bot)."""
    data = {"chat_id": get_settings().alert_chat_id, "text": text[:4000], "disable_web_page_preview": "true"}
    if button and button[1].startswith("https://"):
        data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": button[0], "url": button[1]}]]})
    _call("sendMessage", data)


def parts(path: Path, size: int | None = None) -> list[bytes]:
    """The file in pieces of at most `size` bytes (a bot can't send more than 50 MB at once)."""
    size, data = size or MAX_FILE, path.read_bytes()
    return [data[i:i + size] for i in range(0, len(data), size)] or [b""]


def send_file(path: Path, caption: str) -> int:
    """Sends the file (split into .partN pieces when too big). Returns how many messages."""
    pieces = parts(path)
    for n, piece in enumerate(pieces, 1):
        name = path.name if len(pieces) == 1 else f"{path.name}.part{n}"
        note = caption if len(pieces) == 1 else f"{caption} (part {n}/{len(pieces)}: join with `cat {path.name}.part* > {path.name}`)"
        _call("sendDocument", {"chat_id": get_settings().alert_chat_id, "caption": note[:1000]},
              files={"document": (name, piece, "application/octet-stream")}, timeout=300)
    return len(pieces)


def chat_ids() -> list[tuple[str, str]]:
    """(chat id, name) of everyone who wrote to the bot lately (for scripts/alert_chat_id.py)."""
    s = get_settings()
    if not (s.alert_bot_token and s.alert_bot_token.get_secret_value()):
        raise BotError("ALERT_BOT_TOKEN is empty")
    with httpx.Client(timeout=20, transport=_transport) as client:
        body = client.get(f"{API}/bot{s.alert_bot_token.get_secret_value()}/getUpdates").json()
    seen = {}
    for update in body.get("result", []):
        chat = (update.get("message") or {}).get("chat") or {}
        if chat.get("id"):
            seen[str(chat["id"])] = chat.get("first_name") or chat.get("title") or ""
    return list(seen.items())
