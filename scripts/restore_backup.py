"""docs/SPEC-v5.0-go-live-pack.md G2: restore a backup into a database (default: a SCRATCH copy, never live).

  .venv/bin/python -m scripts.restore_backup FILE [--db NAME]
FILE = backups/product_requests_<time>.dump, or the encrypted .dump.gpg from the alert bot chat (several
.partN files: first `cat FILE.part* > FILE`). The passphrase comes from BACKUP_PASSPHRASE in .env, or is asked.
The target database is dropped and created again, then the row counts of the main tables are printed.
To make it the LIVE database (only after checking the scratch copy): stop the services, run with
--db product_requests --live, start the services.
"""
import argparse
import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from scripts.backup_db import decrypt

TABLES = ("customers", "messages", "orders", "order_items", "products", "outbox")


def restore(dump: Path, db_name: str) -> dict[str, int]:
    s = get_settings()
    admin = create_engine(s.database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()
    env = {**os.environ, "PGPASSWORD": s.db_password.get_secret_value()}
    run = subprocess.run(["pg_restore", "-h", s.db_host, "-p", str(s.db_port), "-U", s.db_user, "-d", db_name,
                          "--no-owner", str(dump)], env=env, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError("pg_restore failed: " + run.stderr[-500:])
    engine = create_engine(s.database_url.set(database=db_name))
    with engine.connect() as c:
        counts = {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in TABLES}
    engine.dispose()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--db", default=get_settings().db_name + "_restore")
    parser.add_argument("--live", action="store_true", help="allow restoring over the live database")
    args = parser.parse_args()
    if args.db == get_settings().db_name and not args.live:
        sys.exit("That is the LIVE database. Check a scratch restore first, then add --live.")
    with tempfile.TemporaryDirectory() as tmp:
        dump = args.file
        if dump.suffix == ".gpg":
            s = get_settings()
            phrase = s.backup_passphrase.get_secret_value() if s.backup_passphrase else getpass.getpass("Passphrase: ")
            dump = decrypt(args.file, Path(tmp) / args.file.stem, phrase)
        counts = restore(dump, args.db)
    print(f"restored into {args.db}: " + ", ".join(f"{t} {n}" for t, n in counts.items()))


if __name__ == "__main__":
    main()
