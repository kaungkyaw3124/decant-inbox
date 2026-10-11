from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from telethon.tl import types

from app.listener.save import from_telethon, save_message

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def user(id=42, **kw):
    kw.setdefault("first_name", "Ko")
    kw.setdefault("last_name", "Aung")
    kw.setdefault("username", "koaung")
    return types.User(id=id, **kw)


def message(id=5, peer=None, text="stw intensely ၅ ml ဝယ်ချင်လို့ပါ", out=False):
    return types.Message(id=id, peer_id=peer or types.PeerUser(42), date=NOW, message=text, out=out)


def test_keeps_incoming_private_text_from_user():
    msg = from_telethon(message(), user())
    assert msg is not None
    assert (msg.external_chat_id, msg.external_message_id, msg.external_user_id) == ("42", "5", "42")
    assert msg.display_name == "Ko Aung" and msg.username == "koaung"
    assert msg.text == "stw intensely ၅ ml ဝယ်ချင်လို့ပါ"  # raw, not normalized
    assert msg.received_at == NOW


@pytest.mark.parametrize(
    ("msg", "sender"),
    [
        (message(peer=types.PeerChat(7)), user()),                      # group
        (message(peer=types.PeerChannel(7)), user()),                   # channel
        (message(), user(bot=True)),                                    # bot
        (message(), user(is_self=True)),                                # Saved Messages
        (message(), user(support=True)),                                # Telegram support
        (message(peer=types.PeerUser(777000)), user(id=777000)),        # login codes
        (message(text=""), user()),                                     # media, no caption
        (message(text="   "), user()),
        (message(), types.Channel(id=7, title="x", photo=types.ChatPhotoEmpty(), date=NOW)),
    ],
)
def test_ignores_everything_else(msg, sender):
    assert from_telethon(msg, sender) is None


def test_keeps_outgoing_as_direction_out():  # v2: the conversation view needs our replies too
    msg = from_telethon(message(out=True), user())
    assert msg.direction == "out" and msg.external_user_id == "42"


def test_save_is_idempotent_and_updates_customer(db):
    from app.core.db import SessionLocal

    first = from_telethon(message(), user())
    with SessionLocal.begin() as s:
        assert save_message(s, first) is True
    with SessionLocal.begin() as s:  # same message again (listener + history import)
        assert save_message(s, first) is False
    renamed = from_telethon(message(id=6, text="ရှိလား"), user(username="newname"))
    with SessionLocal.begin() as s:
        assert save_message(s, renamed) is True

    with db.connect() as c:
        customers = c.execute(text("SELECT external_user_id, username FROM customers")).all()
        messages = c.execute(text(
            "SELECT external_message_id, raw_text, normalized_text FROM messages ORDER BY id"
        )).all()
    assert customers == [("42", "newname")]
    assert messages == [
        ("5", "stw intensely ၅ ml ဝယ်ချင်လို့ပါ", "stw intensely 5 ml ဝယ်ချင်လို့ပါ"),
        ("6", "ရှိလား", "ရှိလား"),
    ]
