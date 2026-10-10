"""One-time interactive login. The owner types the phone number, the login code
and (if set) the 2FA password. Creates secrets/telegram.session (chmod 600).

Usage: .venv/bin/python -m app.listener.login
"""
import asyncio

from app.listener.client import make_client, secure_session_file


async def main() -> None:
    client = make_client()
    await client.start()  # prompts for phone, code and 2FA password on the terminal
    try:
        me = await client.get_me()
        print(f"Logged in as user id {me.id}. Session saved; keep secrets/ private.")
    finally:
        await client.disconnect()
        secure_session_file()


if __name__ == "__main__":
    asyncio.run(main())
