"""docs/SPEC-v5.0-go-live-pack.md G3: 2-step login with an authenticator app (TOTP, RFC 6238: 6 digits, 30 s,
SHA-1 — what Google Authenticator / Authy / 1Password expect), plus 10 one-time recovery codes.
Standard library only; the QR is drawn by segno. Secrets are never logged."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import segno

STEP = 30
DIGITS = 6
RECOVERY_CODES = 10


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code(secret: str, at: float | None = None) -> str:
    counter = int((time.time() if at is None else at) // STEP)
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def verify(secret: str | None, typed: str, at: float | None = None) -> bool:
    """The code now, or one step before / after (phone clocks drift)."""
    typed = "".join(ch for ch in typed if ch.isdigit())
    if not secret or len(typed) != DIGITS:
        return False
    now = time.time() if at is None else at
    return any(hmac.compare_digest(code(secret, now + d * STEP), typed) for d in (-1, 0, 1))


def uri(secret: str, username: str) -> str:
    return f"otpauth://totp/Decant%20Inbox:{quote(username)}?secret={secret}&issuer=Decant%20Inbox"


def qr_svg(text: str) -> str:
    """An inline SVG QR code (no external image, fits the page's CSP)."""
    return segno.make(text, error="m").svg_inline(scale=4, border=2)


def _hash(recovery: str) -> str:
    return hashlib.sha256(recovery.replace("-", "").strip().lower().encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """(codes to show ONCE, hashes to store)."""
    shown = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(RECOVERY_CODES)]
    return shown, [_hash(c) for c in shown]


def use_recovery(hashes: list[str], typed: str) -> list[str] | None:
    """The stored hashes without the used one, or None if the code is not valid."""
    h = _hash(typed)
    return [x for x in hashes if x != h] if h in hashes else None
