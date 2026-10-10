"""Daily database backup: pg_dump (custom format) into backups/, keeps the newest 14.

Each dump is written to a .partial file, checked with `pg_restore --list`, then
renamed, so a half-written or broken file never counts as a backup.
Run by the decant-backup.timer systemd unit; safe to run by hand.

Usage: .venv/bin/python -m scripts.backup_db [--keep 14]
Restore: pg_restore --clean --if-exists -h 127.0.0.1 -U appuser -d product_requests FILE
"""
import argparse
import os
import shutil
import subprocess
import sys
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    path = run_backup(max(args.keep, 1))
    print(f"backup ok: {path.name} ({path.stat().st_size // 1024} KiB); "
          f"{len(list_backups())} kept in {BACKUP_DIR}")


if __name__ == "__main__":
    main()
