"""docs/SPEC-v5.0-go-live-pack.md G1/L1: the alert service (systemd user unit decant-alerts, its own process so it
still reports when the parser or the listener is down).

Every 30 s it looks at what needs the owner and sends NEW problems to the alert bot within ~1 min:
service down (health checks), customer waiting > 5 min, payment to check, AI key refused / no credit, backup
failed, disk > 85 %, tunnel URL changed (with the new link). A fixed problem gets one "✅ resolved" line
(services, backup, disk, AI). The same alert at most once per 30 min; at most 20 alerts per hour. Daily summary
at 21:00 (shop time). Numbers and names only; message text only with "include message preview" ON.
State (what is open, what was sent) lives in app_settings "alerts_state"; the owner's choices in "alerts".

Usage: .venv/bin/python -m app.alerts.service [--once]
"""
import argparse
import logging
import shutil
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.alerts import bot
from app.core.config import BASE_DIR
from app.core.db import SessionLocal
from app.models import AppSetting, AutoRun, Order

log = logging.getLogger("alerts")
SETTING, STATE = "alerts", "alerts_state"
TYPES = {  # type -> label (Settings page)
    "service": "Service down", "waiting": "Customer waiting more than 5 min", "payment": "Payment to check",
    "ai": "AI key refused / no credit", "backup": "Backup failed", "disk": "Disk more than 85 % full",
    "tunnel": "New dashboard link", "login": "Login from a new device", "summary": "Daily summary at 21:00",
}
RESOLVES = ("service", "backup", "disk", "ai")  # a "resolved" line when fixed (not for each answered customer)
WAIT_ALERT = timedelta(minutes=5)
SAME_AGAIN = timedelta(minutes=30)
PER_HOUR = 20
SUMMARY_HOUR = 21
DISK_FULL = 0.85
TUNNEL_FILE = BASE_DIR / "TUNNEL_URL"


def settings(session: Session) -> dict:
    row = session.get(AppSetting, SETTING)
    value = row.value if row else {}
    return {"types": {k: value.get("types", {}).get(k, True) for k in TYPES}, "preview": value.get("preview", False)}


def save_settings(session: Session, types: dict[str, bool], preview: bool, user_id: int | None) -> None:
    _put(session, SETTING, {"types": {k: bool(types.get(k)) for k in TYPES}, "preview": preview}, user_id)


def _put(session: Session, key: str, value: dict, user_id: int | None = None) -> None:
    stmt = insert(AppSetting).values(key=key, value=value, updated_by=user_id)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


def dashboard_url() -> str | None:
    try:
        url = TUNNEL_FILE.read_text().strip()
    except OSError:
        return None
    return url if url.startswith("https://") else None


def _name(customer) -> str:
    return customer.display_name or (f"@{customer.username}" if customer.username else f"customer {customer.id}")


def problems(session: Session, now: datetime, preview: bool) -> dict[str, tuple[str, str]]:
    """Open problems now: key -> (type, text)."""
    from app.web.auto import needs_you  # late imports: the web modules are heavy
    from app.web.health import run_checks

    found: dict[str, tuple[str, str]] = {}
    for check in run_checks(session):
        if not check.ok:
            kind = "backup" if check.name == "backup" else "disk" if check.name == "disk" else "service"
            found[f"check:{check.name}"] = (kind, f"❌ {check.name}: {check.detail}")
    disk = shutil.disk_usage(BASE_DIR)
    if disk.used / disk.total > DISK_FULL:
        found["disk"] = ("disk", f"💾 Disk {disk.used / disk.total:.0%} full ({disk.free // 2**30} GiB free)")
    items = needs_you(session, now)
    for c, m, held in items["waiting"]:
        if now - m.received_at >= WAIT_ALERT:
            text = f"⏰ {_name(c)} waiting {int((now - m.received_at).total_seconds() // 60)} min"
            found[f"waiting:{m.id}"] = ("waiting", text + (f": “{(m.raw_text or '')[:80]}”" if preview else ""))
    for row in items["unanswered"]:
        if now - row.last_at >= WAIT_ALERT:
            text = f"⏰ {_name(row.customer)} waiting {int((now - row.last_at).total_seconds() // 60)} min"
            found[f"waiting:{row.message_ids[-1]}"] = ("waiting", text + (f": “{row.last_text[:80]}”" if preview else ""))
    for check, order, c in items["payments"]:
        found[f"payment:{check.id}"] = ("payment", f"💳 Payment to check: {_name(c)}, {order.total_mmk or 0:,} Ks")
    for notice in items["ai_notices"]:
        found[f"ai:{notice[:60]}"] = ("ai", f"🧠 {notice}")
    return found


def daily_summary(session: Session, now: datetime) -> str:
    from app.ai import report
    from app.orders.sales import tz

    start = now.astimezone(tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    paid = session.execute(select(func.count(), func.coalesce(func.sum(Order.total_mmk), 0)).where(
        Order.paid_at >= start, Order.is_test.is_(False), Order.order_no.is_not(None))).one()
    to_pack = session.scalar(select(func.count()).select_from(Order).where(Order.status == "paid"))
    runs = dict(session.execute(select(AutoRun.status, func.count()).where(AutoRun.created_at >= start)
                                .group_by(AutoRun.status)).all())
    decided = sum(runs.values())
    auto_pct = f"{runs.get('replied', 0) / decided:.0%}" if decided else "—"
    cost = report.period(session, report.today_start(now)).cost
    from app.inventory import stock  # docs/SPEC-v5.1 I4: what to reorder

    low = stock.low_lines(session)
    return (f"📊 Today: {paid[0]} paid orders, {paid[1]:,} Ks · {to_pack} to pack · automatic {auto_pct}"
            f" · AI ${cost:.2f}" + ("\n🛒 Low stock: " + "; ".join(low) if low else ""))


def tick(now: datetime | None = None, send=None) -> list[str]:
    """One look. Returns the texts sent. send(text, button) defaults to the bot."""
    now = now or datetime.now(UTC)
    send = send or bot.send
    sent: list[str] = []
    with SessionLocal.begin() as session:
        cfg = settings(session)
        row = session.get(AppSetting, STATE)
        state = dict(row.value) if row else {}
        open_ = dict(state.get("open", {}))  # key -> {"type", "text", "since", "sent"}
        recent = [t for t in state.get("sent_times", []) if datetime.fromisoformat(t) > now - timedelta(hours=1)]
        link = dashboard_url()
        button = ("Open dashboard", link) if link else None

        def out(text: str, kind: str) -> bool | None:
            """True = sent; False = switched off / over the hourly limit; None = the bot failed (retry)."""
            if not cfg["types"].get(kind, True):
                return False
            if len(recent) >= PER_HOUR:
                state["dropped"] = state.get("dropped", 0) + 1
                return False
            extra = f"\n(+{state['dropped']} more alerts were held back: max {PER_HOUR} per hour)" \
                if state.get("dropped") else ""
            try:
                send(text + extra, button)
            except bot.BotError as exc:
                log.warning("alert not sent: %s", exc)
                return None
            state.pop("dropped", None)
            recent.append(now.isoformat())
            sent.append(text + extra)
            return True

        last_sent = state.setdefault("last_sent", {})
        found = problems(session, now, cfg["preview"])
        for key, (kind, text) in found.items():
            if key in open_:
                continue  # already told
            was = last_sent.get(key)
            if was and now - datetime.fromisoformat(was) < SAME_AGAIN:
                ok = False  # it flapped: the same alert at most once per 30 min
            else:
                ok = out(text, kind)
                if ok is None:
                    continue  # the bot failed: try again next time
                if ok:
                    last_sent[key] = now.isoformat()
            open_[key] = {"type": kind, "text": text, "since": now.isoformat(), "sent": bool(ok or was)}
        for key in [k for k in open_ if k not in found]:
            gone = open_.pop(key)
            if gone["type"] in RESOLVES and gone["sent"]:
                out(f"✅ resolved: {gone['text'].lstrip('❌💾🧠 ')}", gone["type"])
        if link and link != state.get("tunnel_url"):
            if state.get("tunnel_url"):  # not on the very first run
                out(f"🔗 New dashboard link: {link}", "tunnel")
            state["tunnel_url"] = link
        from app.orders.sales import tz

        local = now.astimezone(tz())
        if local.hour >= SUMMARY_HOUR and state.get("summary_day") != local.date().isoformat():
            state["summary_day"] = local.date().isoformat()
            out(daily_summary(session, now), "summary")
        state["open"], state["sent_times"] = open_, recent
        state["last_sent"] = {k: v for k, v in last_sent.items() if datetime.fromisoformat(v) > now - timedelta(days=1)}
        _put(session, STATE, state)
    return sent


def login_alert(username: str, ip: str, device: str) -> None:
    """docs/SPEC-v5.0 G3: a login from a device / IP not seen before (called by the web login)."""
    if not bot.configured():
        return
    with SessionLocal() as session:
        if not settings(session)["types"]["login"]:
            return
    try:
        bot.send(f"🔐 New login: {username} from {ip} ({device[:60]})")
    except bot.BotError as exc:
        log.warning("login alert not sent: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=30.0)
    args = parser.parse_args()
    log.info("alerts started (%s)", "ON" if bot.configured() else "OFF: ALERT_BOT_TOKEN / ALERT_CHAT_ID empty")
    while True:
        if bot.configured():
            try:
                for text in tick():
                    log.info("alert sent (%d chars)", len(text))
            except Exception:
                log.exception("alert check failed")
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
