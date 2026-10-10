"""Create a dashboard user, or set a new password for an existing one.
The password is typed at the prompt (never on the command line, never stored in plain text).

Usage: .venv/bin/python -m scripts.create_user USERNAME [--role owner|staff]
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--role", choices=ROLES, default="owner")
    args = parser.parse_args()
    username = args.username.strip().lower()

    password = getpass.getpass(f"New password for {username} (min {MIN_LENGTH} chars): ")
    if len(password) < MIN_LENGTH:
        sys.exit("Too short, nothing changed.")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords differ, nothing changed.")

    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            session.add(User(username=username, password_hash=hash_password(password), role=args.role))
            print(f"Created {args.role} user {username}.")
        else:
            user.password_hash = hash_password(password)
            print(f"Password updated for {username} (role {user.role}).")


if __name__ == "__main__":
    main()
