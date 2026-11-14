"""docs/SPEC-v5.3-performance-pc.md M3: live updates for the open dashboard tab (Server-Sent Events).

The stream says only WHAT changed, never customer data: "thread" (the open chat got a message / a reply changed
status / a photo loaded), "list" (any new message: the chat list), "counts" ({"needs": n} for the menu badge).
The browser then fetches that part through the normal, logged-in routes. Woken at once by the Postgres NOTIFY
of v4.18 (new_message, outbox), else it looks every 2 s. A stream ends after 5 minutes (the browser reconnects,
so a logged-out or expired session stops it); the thread's own polling stays as the fallback.
docs/SPEC-v5.9 B7: ONE listening connection and one look per 2 s for all open tabs (the hub below); the
snapshot is shared by every tab of the same view; at most MAX_STREAMS tabs per user (more get 204 and poll).
"""
import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.core.db import SessionLocal
from app.core.notify import AsyncWaiter
from app.models import MediaDownload, Message, Outbox
from app.web.auth import LoginRequired, current_user
from app.web.deps import needs_count

router = APIRouter()
LOOK_EVERY = 2.0
STREAM_SECONDS = 300
PING_EVERY = 15
MAX_STREAMS = 3


class Hub:
    """One background task: LISTEN once, tick every LOOK_EVERY s (sooner on a NOTIFY); every stream waits for
    the tick and reads the snapshot of its view, computed once per tick."""

    def __init__(self):
        self.tick, self.changed, self.task, self.loop = 0, None, None, None
        self.cache: dict[tuple, tuple[int, asyncio.Future]] = {}
        self.streams: dict[int, dict[object, float]] = {}  # user id -> {stream: started (monotonic)}

    def open_streams(self, user_id: int) -> int:
        # a stream whose finally never ran (client gone before the first byte) stops counting after its lifetime
        mine = self.streams.setdefault(user_id, {})
        for token in [t for t, at in mine.items() if time.monotonic() - at > STREAM_SECONDS + 30]:
            del mine[token]
        return len(mine)

    async def _run(self) -> None:
        waiter = AsyncWaiter("new_message", "outbox")
        try:
            while True:
                await waiter.wait(LOOK_EVERY)
                self.tick += 1
                self.changed.set()
                self.changed = asyncio.Event()
                self.cache = {k: v for k, v in self.cache.items() if v[0] >= self.tick - 1}
        finally:
            if waiter.conn is not None:
                await waiter.conn.close()

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        if self.task is None or self.task.done() or self.loop is not loop:  # (tests: a new loop per client)
            self.loop, self.changed, self.cache = loop, asyncio.Event(), {}
            self.task = loop.create_task(self._run())

    async def next_tick(self) -> None:
        self.start()
        await self.changed.wait()

    async def snapshot(self, customer_id: int | None, role: str) -> dict:
        self.start()
        key, tick = (customer_id, role), self.tick
        hit = self.cache.get(key)
        if hit is None or hit[0] != tick:
            future = asyncio.ensure_future(run_in_threadpool(snapshot, customer_id, role))
            self.cache[key] = hit = (tick, future)
        return await asyncio.shield(hit[1])


hub = Hub()


def snapshot(customer_id: int | None, role: str) -> dict:
    with SessionLocal() as s:
        state = {"list": s.scalar(select(func.max(Message.id))), "counts": {"needs": needs_count(s, role)}}
        if customer_id:
            state["thread"] = [
                s.scalar(select(func.max(Message.id)).where(Message.customer_id == customer_id)),
                s.execute(select(Outbox.id, Outbox.status).where(Outbox.customer_id == customer_id)
                          .order_by(Outbox.id.desc()).limit(5)).all(),
                s.execute(select(MediaDownload.message_id, MediaDownload.status).join(Message)
                          .where(Message.customer_id == customer_id)
                          .order_by(MediaDownload.message_id.desc()).limit(5)).all()]
        return json.loads(json.dumps(state, default=list))


@router.get("/events")
async def events(request: Request, customer: int | None = None):
    def who() -> tuple[int, str] | None:
        with SessionLocal() as db:  # not get_db: no connection may stay open for the whole stream
            try:
                user = current_user(request, db)
                return user.id, user.role
            except LoginRequired:
                return None

    found = await run_in_threadpool(who)
    if found is None:
        return Response(status_code=204)  # EventSource stops on 204 (no reconnect loop on the login page)
    user_id, role = found
    if hub.open_streams(user_id) >= MAX_STREAMS:
        return Response(status_code=204)  # this tab keeps its own polling
    token = object()
    hub.streams[user_id][token] = time.monotonic()

    async def stream():
        last, pinged, end = None, time.monotonic(), time.monotonic() + STREAM_SECONDS
        try:
            yield "retry: 3000\n\n"
            while time.monotonic() < end and not await request.is_disconnected():
                now = await hub.snapshot(customer, role)
                for key in ("thread", "list", "counts"):
                    if last is not None and now.get(key) != last.get(key):
                        yield f"event: {key}\ndata: {json.dumps(now[key] if key == 'counts' else {})}\n\n"
                last = now
                if time.monotonic() - pinged > PING_EVERY:
                    pinged = time.monotonic()
                    yield ": ping\n\n"
                await hub.next_tick()
        finally:
            hub.streams.get(user_id, {}).pop(token, None)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
