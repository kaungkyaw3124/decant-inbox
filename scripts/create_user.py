"""Create a dashboard user, or set a new password for an existing one.
The password is typed at the prompt (never on the command line, never stored in plain text).

Usage: .venv/bin/python -m scripts.create_user USERNAME [--role owner|staff]
       .venv/bin/python -m scripts.create_user USERNAME --reset-2fa   (phone lost: 2-step login off, all logged out)
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import User
from app.models.users import ROLES
from app.web.auth import hash_password

MIN_LENGTH = 10


def reset_2fa(username: str) -> str:
    """docs/SPEC-v5.0 G3: over SSH only. 2-step login off, recovery codes gone, every session logged out."""
    from app.models import AuditLog

    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            return f"No user {username}."
        user.totp_secret, user.totp_recovery = None, []
        user.session_epoch += 1
        session.add(AuditLog(user_id=None, action="user.2fa_reset", details={"user_id": user.id, "via": "ssh"}))
    print(f"2-step login is OFF for {username}; all their sessions are logged out. Set it up again in My account.")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--role", choices=ROLES, default="owner")
    parser.add_argument("--reset-2fa", action="store_true", help="turn 2-step login off (lost phone)")
    args = parser.parse_args()
    username = args.username.strip().lower()
    if args.reset_2fa:
        sys.exit(reset_2fa(username) or None)  # None = exit 0

    password = getpass.getpass(f"New password for {username} (min {MIN_LENGTH} chars): ")
    if len(password) < MIN_LENGTH:
        sys.exit("Too short, nothing changed.")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords differ, nothing changed.")

    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            session.add(User(username=username, password_hash=hash_password(password), role=args.role,
                             language="my" if args.role == "staff" else "en"))  # staff start in Burmese
            print(f"Created {args.role} user {username}.")
        else:
            user.password_hash = hash_password(password)
            print(f"Password updated for {username} (role {user.role}).")


if __name__ == "__main__":
    main()
