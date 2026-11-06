"""docs/SPEC-v5.3-performance-pc.md M3: live updates for the open dashboard tab (Server-Sent Events).

The stream says only WHAT changed, never customer data: "thread" (the open chat got a message / a reply changed
status / a photo loaded), "list" (any new message: the chat list), "counts" ({"needs": n} for the menu badge).
The browser then fetches that part through the normal, logged-in routes. Woken at once by the Postgres NOTIFY
of v4.18 (new_message, outbox), else it looks every 2 s. A stream ends after 5 minutes (the browser reconnects,
so a logged-out or expired session stops it); the thread's own polling stays as the fallback.
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
    def who() -> str | None:
        with SessionLocal() as db:  # not get_db: no connection may stay open for the whole stream
            try:
                return current_user(request, db).role
            except LoginRequired:
                return None

    role = await run_in_threadpool(who)
    if role is None:
        return Response(status_code=204)  # EventSource stops on 204 (no reconnect loop on the login page)

    async def stream():
        waiter = AsyncWaiter("new_message", "outbox")
        last, pinged, end = None, time.monotonic(), time.monotonic() + STREAM_SECONDS
        yield "retry: 3000\n\n"
        try:
            while time.monotonic() < end and not await request.is_disconnected():
                now = await run_in_threadpool(snapshot, customer, role)
                for key in ("thread", "list", "counts"):
                    if last is not None and now.get(key) != last.get(key):
                        yield f"event: {key}\ndata: {json.dumps(now[key] if key == 'counts' else {})}\n\n"
                last = now
                if time.monotonic() - pinged > PING_EVERY:
                    pinged = time.monotonic()
                    yield ": ping\n\n"
                await waiter.wait(LOOK_EVERY)
        finally:
            if waiter.conn is not None:
                await waiter.conn.close()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
