"""docs/SPEC-v4.18-speed.md S1: wake up on a Postgres NOTIFY instead of waiting for the next poll.

Channels (triggers, migration d7e4a1b9c3f2): new_message (a customer message saved), outbox (a reply queued).
A Waiter sleeps at most `timeout` seconds and returns early on a notification. If the LISTEN connection
breaks, it falls back to a plain sleep and reconnects next time: the poll keeps everything working, so a
lost NOTIFY or a restart only costs one poll interval.
"""
import asyncio
import logging
import time

import psycopg

from app.core.config import get_settings

log = logging.getLogger("notify")


def _conninfo() -> str:
    return get_settings().database_url.set(drivername="postgresql").render_as_string(hide_password=False)


def notify(channel: str, payload: str = "") -> None:
    """Wake the listeners of `channel` now (e.g. an AI answer arrived in a worker thread)."""
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute("SELECT pg_notify(%s, %s)", (channel, payload))


class Waiter:
    def __init__(self, *channels: str):
        self.channels, self.conn = channels, None

    def wait(self, timeout: float) -> bool:
        """True = woken by a NOTIFY; False = the timeout passed."""
        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg.connect(_conninfo(), autocommit=True)
                for channel in self.channels:
                    self.conn.execute(f"LISTEN {channel}")
            woken = False
            for _ in self.conn.notifies(timeout=max(timeout, 0.0), stop_after=1):
                woken = True
            return woken
        except Exception:
            log.warning("LISTEN %s failed; polling", ",".join(self.channels))
            self.conn = None
            time.sleep(max(timeout, 0.0))
            return False


class AsyncWaiter:
    def __init__(self, *channels: str):
        self.channels, self.conn = channels, None

    async def wait(self, timeout: float) -> bool:
        try:
            if self.conn is None or self.conn.closed:
                self.conn = await psycopg.AsyncConnection.connect(_conninfo(), autocommit=True)
                for channel in self.channels:
                    await self.conn.execute(f"LISTEN {channel}")
            woken = False
            async for _ in self.conn.notifies(timeout=max(timeout, 0.0), stop_after=1):
                woken = True
            return woken
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("LISTEN %s failed; polling", ",".join(self.channels))
            self.conn = None
            await asyncio.sleep(max(timeout, 0.0))
            return False
