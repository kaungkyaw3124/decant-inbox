"""Daily database backup: pg_dump (custom format) into backups/, keeps the newest 14.

Each dump is written to a .partial file, checked with `pg_restore --list`, then
renamed, so a half-written or broken file never counts as a backup.
Run by the decant-backup.timer systemd unit; safe to run by hand.

docs/SPEC-v5.0-go-live-pack.md G2: when BACKUP_PASSPHRASE and the alert bot are set, the new dump is also
encrypted (gpg, AES-256, symmetric) and sent to the owner's alert bot chat: a copy that leaves the server.
A failure is reported to the alert bot and the run exits 1 (the health page shows it too).

Usage: .venv/bin/python -m scripts.backup_db [--keep 14]
Restore: .venv/bin/python -m scripts.restore_backup FILE  (a .dump, or the .dump.gpg from the bot chat)
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import BASE_DIR, get_settings

BACKUP_DIR = BASE_DIR / "backups"
PATTERN = "product_requests_*.dump"


def list_backups(backup_dir: Path = BACKUP_DIR) -> list[Path]:
    """Finished backups, newest first."""
    return sorted(backup_dir.glob(PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)


def prune(keep: int, backup_dir: Path = BACKUP_DIR) -> int:
    """Delete all but the newest `keep` backups and any leftover .partial files."""
    removed = 0
    for old in list_backups(backup_dir)[keep:]:
        old.unlink()
        removed += 1
    for stale in backup_dir.glob("*.partial"):  # left by a crashed run
        stale.unlink()
    return removed


def run_backup(keep: int, backup_dir: Path = BACKUP_DIR) -> Path:
    if shutil.which("pg_dump") is None:
        sys.exit("pg_dump not found: install postgresql-client (see PLAN.md, Phase 5)")
    s = get_settings()
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)  # customer messages inside
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    final = backup_dir / f"{s.db_name}_{stamp}.dump"
    partial = final.with_suffix(".dump.partial")
    env = {**os.environ, "PGPASSWORD": s.db_password.get_secret_value()}
    conn = ["-h", s.db_host, "-p", str(s.db_port), "-U", s.db_user]

    old_umask = os.umask(0o077)
    try:
        subprocess.run(["pg_dump", *conn, "-d", s.db_name, "-Fc", "--no-owner", "-f", str(partial)],
                       env=env, check=True)
    finally:
        os.umask(old_umask)
    listing = subprocess.run(["pg_restore", "--list", str(partial)], capture_output=True, text=True)
    if listing.returncode != 0 or "TABLE DATA public messages" not in listing.stdout:
        partial.unlink(missing_ok=True)
        sys.exit("backup check failed: pg_restore --list did not show the messages table")
    partial.rename(final)
    prune(keep, backup_dir)
    return final


def _gpg(args: list[str], passphrase: str) -> None:
    """gpg with its own empty home (no keyring needed for a passphrase); the passphrase goes in on stdin."""
    with tempfile.TemporaryDirectory() as home:
        run = subprocess.run(["gpg", "--homedir", home, "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback",
                              "--passphrase-fd", "0", *args], input=passphrase.encode(), capture_output=True)
    if run.returncode != 0:
        raise RuntimeError(f"gpg failed ({run.returncode})")  # never echo stderr: it may name files only, but keep it short


def encrypt(path: Path, passphrase: str) -> Path:
    out = path.with_name(path.name + ".gpg")
    _gpg(["--symmetric", "--cipher-algo", "AES256", "-o", str(out), str(path)], passphrase)
    out.chmod(0o600)
    return out


def decrypt(path: Path, out: Path, passphrase: str) -> Path:
    _gpg(["--decrypt", "-o", str(out), str(path)], passphrase)
    return out


def offsite(path: Path) -> str:
    """Encrypt + send to the alert bot. Returns what happened (no secrets)."""
    from app.alerts import bot

    s = get_settings()
    if not (s.backup_passphrase and s.backup_passphrase.get_secret_value()) or not bot.configured():
        return "off-server copy OFF (BACKUP_PASSPHRASE / alert bot not set)"
    encrypted = encrypt(path, s.backup_passphrase.get_secret_value())
    try:
        n = bot.send_file(encrypted, f"🗄 Backup {path.name} (encrypted; restore: scripts/restore_backup.py)")
    finally:
        encrypted.unlink(missing_ok=True)  # the plain dump stays local; the encrypted copy lives in the chat
    return f"sent to the alert bot ({n} file{'s' if n > 1 else ''})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    try:
        path = run_backup(max(args.keep, 1))
        copy = offsite(path)
    except (Exception, SystemExit) as exc:
        reason = str(exc) if isinstance(exc, SystemExit) else type(exc).__name__
        try:
            from app.alerts import bot

            if bot.configured():
                bot.send(f"❌ Backup failed: {reason[:200]}")
        except Exception:
            pass
        sys.exit(f"backup failed: {reason}")
    print(f"backup ok: {path.name} ({path.stat().st_size // 1024} KiB); "
          f"{len(list_backups())} kept in {BACKUP_DIR}; {copy}")


if __name__ == "__main__":
    main()
