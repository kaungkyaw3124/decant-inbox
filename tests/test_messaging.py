"""Step 2: outgoing + photo capture, outbox sender (fake Telegram client), rate limit,
photo download, reply composing, and the chat pages."""
import asyncio
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from telethon import errors
from telethon.tl import types

from app.core.db import SessionLocal
from app.listener import sender
from app.listener.save import ChatMessage, from_telethon, save_message
from app.models import Outbox
from app.parser.worker import run_batch
from app.replies import compose
from app.replies import templates as replies
from tests.test_prices import STW, run_import, xlsx
from tests.test_web import client, log_in  # noqa: F401  (fixture)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def user(id=42, **kw):
    kw.setdefault("first_name", "Ko")
    kw.setdefault("username", "koaung")
    return types.User(id=id, **kw)


def tg_message(id=5, text="hi", out=False, media=None, grouped_id=None, peer=42):
    return types.Message(id=id, peer_id=types.PeerUser(peer), date=NOW, message=text, out=out,
                         media=media, grouped_id=grouped_id)


def photo_media(size=54321):
    photo = types.Photo(id=1, access_hash=2, file_reference=b"", date=NOW, dc_id=1, sizes=[
        types.PhotoSize(type="m", w=320, h=320, size=1000),
        types.PhotoSizeProgressive(type="y", w=1280, h=1280, sizes=[100, 2000, size])])
    return types.MessageMediaPhoto(photo=photo)


def document_media(mime, attributes=()):
    doc = types.Document(id=1, access_hash=2, file_reference=b"", date=NOW, mime_type=mime, size=777,
                         dc_id=1, attributes=list(attributes))
    return types.MessageMediaDocument(document=doc)


def add(msg_id, body, direction="in", customer="42", when=None, kind="text", grouped_id=None):
    with SessionLocal.begin() as s:
        save_message(s, ChatMessage(customer, str(msg_id), customer, None, f"User {customer}", body,
                                    when or datetime.now(UTC), direction=direction, kind=kind,
                                    grouped_id=grouped_id, media_size=1234 if kind == "photo" else None,
                                    media_mime="image/jpeg" if kind == "photo" else None))


def customer_id(db, external="42") -> int:
    with db.connect() as c:
        return c.execute(text("SELECT id FROM customers WHERE external_user_id = :e"), {"e": external}).scalar()


def scalar(db, sql, **params):
    with db.connect() as c:
        return c.execute(text(sql), params).scalar()


# ---------- capture ----------

def test_outgoing_and_media_are_captured():
    out = from_telethon(tg_message(text="18,000 ကျပ်ပါ", out=True), user())
    assert (out.direction, out.kind, out.external_user_id) == ("out", "text", "42")

    photo = from_telethon(tg_message(text="", media=photo_media(), grouped_id=999), user())
    assert (photo.kind, photo.media_size, photo.media_mime, photo.grouped_id, photo.text) == (
        "photo", 54321, "image/jpeg", "999", "")

    as_file = from_telethon(tg_message(text="", media=document_media("image/png")), user())
    assert (as_file.kind, as_file.media_size, as_file.media_mime) == ("photo", 777, "image/png")

    sticker = from_telethon(tg_message(text="", media=document_media(
        "image/webp", [types.DocumentAttributeSticker(alt="x", stickerset=types.InputStickerSetEmpty())])), user())
    assert sticker.kind == "other"
    voice = from_telethon(tg_message(text="", media=document_media("audio/ogg")), user())
    assert voice.kind == "other"


@pytest.mark.parametrize("msg,peer", [
    (tg_message(out=True), user(is_self=True)),  # Saved Messages
    (tg_message(out=True), user(bot=True)),
    (tg_message(peer=43), user()),  # peer and chat don't match
    (tg_message(text=" "), user()),
    (types.MessageService(id=1, peer_id=types.PeerUser(42), date=NOW, action=types.MessageActionEmpty()), user()),
])
def test_still_ignored(msg, peer):
    assert from_telethon(msg, peer) is None


def test_outgoing_not_parsed_and_not_in_inbox(client, db):  # noqa: F811
    log_in(client)
    add(50, "stw intensely 5ml က 18,000 ကျပ်ပါ", direction="out")
    run_batch()
    assert scalar(db, "SELECT count(*) FROM parse_results pr JOIN messages m ON m.id = pr.message_id "
                      "WHERE m.direction = 'out'") == 0
    assert "18,000 ကျပ်ပါ" not in client.get("/?intent=all&status=all").text


# ---------- sender ----------

def test_rate_limiter():
    now = [0.0]
    limiter = sender.RateLimiter(clock=lambda: now[0])
    assert limiter.wait_time() == 0
    limiter.record()
    assert limiter.wait_time() == 3.0
    for _ in range(19):
        now[0] += 3
        limiter.record()
    now[0] += 3  # t=60: the first send just left the window
    assert limiter.wait_time() == 0
    now[0] -= 0.5  # t=59.5: 20 sends in the last 60 s
    assert limiter.wait_time() == pytest.approx(0.5)


class FakeClient:
    def __init__(self, fail=None):
        self.fail, self.sent, self.downloads = fail, [], []

    def is_connected(self):
        return True

    async def get_input_entity(self, peer):
        return peer

    async def send_message(self, entity, message, link_preview):
        if self.fail:
            raise self.fail
        self.sent.append((entity.user_id, message))
        return types.Message(id=900 + len(self.sent), peer_id=entity, date=NOW, message=message, out=True)

    async def get_messages(self, entity, ids):
        return tg_message(id=ids, text="", media=photo_media())

    async def download_media(self, message, file):
        self.downloads.append(file)
        with open(file, "wb") as f:
            f.write(b"\xff\xd8fakejpeg")
        return file


def queue(db, body="hello", customer="42", key="k1") -> int:
    with SessionLocal.begin() as s:
        row = Outbox(customer_id=customer_id(db, customer), text=body, reply_kind="custom", idempotency_key=key)
        s.add(row)
        s.flush()
        return row.id


def test_send_queued_message(db):
    add(1, "ရှိလား")
    oid = queue(db, "  STW 5ml က 18,000 ကျပ်ပါ။  ")
    client = FakeClient()
    assert asyncio.run(sender.send_next(client, sender.RateLimiter())) is True
    assert client.sent == [(42, "STW 5ml က 18,000 ကျပ်ပါ။")]
    with db.connect() as c:
        status, msg_id = c.execute(text("SELECT status, sent_message_id FROM outbox WHERE id = :i"), {"i": oid}).one()
        assert status == "sent"
        assert c.execute(text("SELECT direction, external_message_id FROM messages WHERE id = :i"),
                         {"i": msg_id}).one() == ("out", "901")
    # the listener event for the same message is a duplicate, not a second row
    with SessionLocal.begin() as s:
        assert save_message(s, from_telethon(tg_message(id=901, text="x", out=True), user())) is False
    assert asyncio.run(sender.send_next(client, sender.RateLimiter())) is False  # nothing left


def test_never_message_first(db):
    add(1, "only our message", direction="out")
    oid = queue(db)
    client = FakeClient()
    asyncio.run(sender.send_next(client, sender.RateLimiter()))
    assert client.sent == []
    assert scalar(db, "SELECT error FROM outbox WHERE id = :i", i=oid) == "this customer has never messaged us"


def test_flood_wait_keeps_queued_and_errors_fail(db):
    add(1, "hi")
    oid = queue(db)
    asyncio.run(sender.send_next(FakeClient(fail=errors.FloodWaitError(None, capture=0)), sender.RateLimiter()))
    assert scalar(db, "SELECT status FROM outbox WHERE id = :i", i=oid) == "queued"
    asyncio.run(sender.send_next(FakeClient(fail=ValueError("Could not find the input entity")), sender.RateLimiter()))
    with db.connect() as c:
        status, error = c.execute(text("SELECT status, error FROM outbox WHERE id = :i"), {"i": oid}).one()
    assert status == "failed" and error.startswith("ValueError: Could not find")


def test_photo_download(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sender, "MEDIA_DIR", tmp_path / "media")
    add(7, "", kind="photo")
    mid = scalar(db, "SELECT id FROM messages")
    with db.begin() as c:
        c.execute(text("INSERT INTO media_downloads (message_id) VALUES (:m)"), {"m": mid})
    client = FakeClient()
    assert asyncio.run(sender.download_next(client)) is True
    with db.connect() as c:
        status, path = c.execute(text("SELECT status, path FROM media_downloads")).one()
    assert (status, path) == ("done", f"{mid}.jpg")
    assert (tmp_path / "media" / path).stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "media").stat().st_mode & 0o777 == 0o700


# ---------- composing ----------

@pytest.fixture
def priced(db, tmp_path):
    from scripts.seed_catalog import seed
    from tests.test_seed_catalog import write_csvs

    seed(write_csvs(tmp_path))
    run_import(xlsx(STW, ["Dior", "Sauvage Eau de Parfum", 100, 420000, None, 20000, None, "no"]))
    with db.connect() as c:
        return dict(c.execute(text("SELECT name, id FROM products")).all())


def test_price_reply(priced):
    stw, sauvage, y = (priced["Stronger With You Intensely"], priced["Sauvage Eau de Parfum"], priced["Y Eau de Parfum"])
    with SessionLocal() as s:
        texts = replies.load(s)
        r = compose.price_reply(s, [compose.PriceItem(stw, "5")], texts)
        assert r.text == "Stronger With You Intensely 5ml က 18,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။" and not r.problems
        r = compose.price_reply(s, [compose.PriceItem(stw, "100")], texts)  # 100 = bottle size
        assert r.text.startswith("Stronger With You Intensely Full 100ml က 380,000")
        r = compose.price_reply(s, [compose.PriceItem(stw, "all")], texts)
        assert r.text == ("Stronger With You Intensely\n• 2ml – 8,000 ကျပ်\n• 5ml – 18,000 ကျပ်\n"
                          "• 10ml – 33,000 ကျပ်\n• Full 100ml – 380,000 ကျပ်")
        r = compose.price_reply(s, [compose.PriceItem(stw, "3"), compose.PriceItem(y, "5")], texts)
        assert r.text == "" and len(r.problems) == 2 and "Sizes sold: 2ml, 5ml, 10ml, Full 100ml" in r.problems[0]
        assert "no prices yet" in r.problems[1]
        r = compose.price_reply(s, [compose.PriceItem(sauvage, "5"), compose.PriceItem(stw, "full")], texts)
        assert r.text.splitlines() == ["Sauvage Eau de Parfum 5ml လောလောဆယ် ကုန်နေပါတယ်နော်။",
                                       "Stronger With You Intensely Full 100ml က 380,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"]
        assert r.notes and not r.problems
        r = compose.price_reply(s, [compose.PriceItem(sauvage, "all")], texts)
        assert r.text == "Sauvage Eau de Parfum လောလောဆယ် ကုန်နေပါတယ်နော်။"


def test_greeting_rule(db):
    add(1, "hi", when=datetime.now(UTC) - timedelta(hours=1))
    cid = customer_id(db)
    with SessionLocal() as s:
        assert compose.needs_greeting(s, cid) is True
    add(2, "ok", direction="out", when=datetime.now(UTC) - timedelta(hours=7))
    with SessionLocal() as s:
        assert compose.needs_greeting(s, cid) is True
    add(3, "ok", direction="out", when=datetime.now(UTC) - timedelta(hours=5))
    with SessionLocal() as s:
        assert compose.needs_greeting(s, cid) is False


def test_recent_requests(priced, db):
    add(1, "stw intensely 5ml ရှိလား", when=datetime.now(UTC) - timedelta(hours=2))
    add(2, "sauvage edp ဘယ်လောက်လဲ", when=datetime.now(UTC) - timedelta(hours=1))
    add(3, "ysl y", when=datetime.now(UTC) - timedelta(hours=30))  # too old
    run_batch()
    with SessionLocal() as s:
        items = compose.recent_requests(s, customer_id(db))
    assert [(i.product_id, i.size) for i in items] == [
        (priced["Sauvage Eau de Parfum"], "all"), (priced["Stronger With You Intensely"], "5")]


# ---------- web ----------

def test_chat_pages_and_send(client, db):  # noqa: F811
    token = log_in(client)
    cid = customer_id(db)
    page = client.get("/chats").text
    assert f'href="/chats/{cid}"' in page and "waiting for reply" in page

    page = client.get(f"/chats/{cid}").text
    assert "stw intensely ၅ ml ဝယ်ချင်လို့ပါ" in page and "Open in Telegram" in page
    assert "မင်္ဂလာပါ။" in page  # greeting pre-filled: we never messaged them
    key = re.search(r'name="key" value="([^"]+)"', page).group(1)

    data = {"csrf": token, "key": key, "reply_kind": "custom", "text": "မင်္ဂလာပါ။\r\nရပါတယ်"}
    r = client.post(f"/chats/{cid}/send", data=data, follow_redirects=False)
    assert r.status_code == 303
    client.post(f"/chats/{cid}/send", data=data)  # double tap
    with db.connect() as c:
        assert c.execute(text("SELECT text, status, created_by FROM outbox")).all() == [("မင်္ဂလာပါ။\nရပါတယ်", "queued", 1)]
        assert c.execute(text("SELECT action FROM audit_log")).scalars().all() == ["outbox.queue"]
    page = client.get(f"/chats/{cid}").text
    assert "⏳ queued" in page and 'hx-trigger="every 4s"' in page
    assert "Starts with the greeting" not in page  # a queued message counts as messaging them

    oid = scalar(db, "SELECT id FROM outbox")
    client.post(f"/chats/{cid}/outbox/{oid}/cancel", data={"csrf": token})
    assert scalar(db, "SELECT status FROM outbox") == "cancelled"
    assert client.post(f"/chats/{cid}/outbox/{oid}/retry", data={"csrf": token}).status_code == 400


def test_cannot_message_first(client, db):  # noqa: F811
    token = log_in(client)
    add(60, "hello from the phone", direction="out", customer="99")
    cid = customer_id(db, "99")
    assert "never messaged us" in client.get(f"/chats/{cid}").text
    r = client.post(f"/chats/{cid}/send", data={"csrf": token, "key": "x", "text": "hi"})
    assert r.status_code == 400
    assert scalar(db, "SELECT count(*) FROM outbox") == 0


def test_price_compose_page(client, db):  # noqa: F811
    token = log_in(client)
    run_import(xlsx(STW))
    add(80, "stw intensely ၅ ml ရှိလား")  # now, so within the 24 h context window
    run_batch()
    cid = customer_id(db)
    page = client.get(f"/chats/{cid}?compose=price").text  # pre-selected from it
    stw = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    assert f'<option value="{stw}" selected>' in page and '<option value="5" selected>' in page
    page = client.get(f"/chats/{cid}?compose=price&make=1&p1={stw}&s1=5").text
    assert "Stronger With You Intensely 5ml က 18,000 ကျပ်ပါ။" in page and 'value="price"' in page
    page = client.get(f"/chats/{cid}?compose=price&make=1&p1={stw}&s1=3").text
    assert "3ml has no price" in page and "/send" not in page  # problem blocks sending
    assert token


def test_photo_request_and_serving(client, db, tmp_path, monkeypatch):  # noqa: F811
    from app.web import chats

    token = log_in(client)
    add(70, "", kind="photo", grouped_id="5")
    add(71, "", kind="photo", grouped_id="5")
    mid = scalar(db, "SELECT min(id) FROM messages WHERE kind = 'photo'")
    cid = customer_id(db)
    page = client.get(f"/chats/{cid}").text
    assert "Show photo (1 KB)" in page and "several photos sent together" in page
    assert client.get(f"/media/{mid}").status_code == 404

    client.post(f"/messages/{mid}/photo", data={"csrf": token})
    assert scalar(db, "SELECT status FROM media_downloads") == "queued"
    assert "Loading photo" in client.get(f"/chats/{cid}").text

    monkeypatch.setattr(chats, "MEDIA_DIR", tmp_path)
    (tmp_path / f"{mid}.jpg").write_bytes(b"\xff\xd8jpeg")
    with db.begin() as c:
        c.execute(text("UPDATE media_downloads SET status = 'done', path = :p"), {"p": f"../../{mid}.jpg"})
    r = client.get(f"/media/{mid}")
    assert r.status_code == 200 and r.content == b"\xff\xd8jpeg" and r.headers["content-type"] == "image/jpeg"
