"""Filter Telegram messages and save them. Used by both the live listener and the
history import, so both apply exactly the same rules.

Saves only private chats with a real user (not a bot, not Saved Messages, not
Telegram's service account): incoming messages AND our own outgoing ones (sent from
the dashboard or from the owner's phone), so the conversation view is complete.
Photos: metadata only (size, mime, album id); the file is downloaded only when an
admin opens it. Writes customers + messages only.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from telethon.tl import types

from app.models import Customer, Message
from app.parser.normalize import normalize

CHANNEL = "telegram"
TELEGRAM_SERVICE_USER_ID = 777000  # sends login codes; must never be stored


@dataclass(frozen=True)
class ChatMessage:
    external_chat_id: str
    external_message_id: str
    external_user_id: str  # the customer (the other side of the private chat)
    username: str | None
    display_name: str | None
    text: str  # caption for photos, "" if none
    received_at: datetime
    direction: str = "in"  # out = sent by us
    kind: str = "text"  # text | photo | other
    grouped_id: str | None = None
    media_size: int | None = None
    media_mime: str | None = None


def is_customer_chat(peer) -> bool:
    """A private chat with a real person (the chat's user, not the message sender)."""
    return (isinstance(peer, types.User) and not peer.bot and not peer.is_self
            and not peer.support and peer.id != TELEGRAM_SERVICE_USER_ID)


def _photo_size(photo) -> int | None:
    sizes = []
    for s in getattr(photo, "sizes", None) or []:
        if isinstance(s, types.PhotoSizeProgressive) and s.sizes:
            sizes.append(max(s.sizes))
        elif hasattr(s, "size") and isinstance(s.size, int):
            sizes.append(s.size)
    return max(sizes) if sizes else None


def media_info(message) -> tuple[str, int | None, str | None]:
    """(kind, size in bytes, mime). Images sent "as file" count as photos too."""
    media = getattr(message, "media", None)
    if media is None or isinstance(media, types.MessageMediaWebPage):  # link preview = text
        return "text", None, None
    if isinstance(media, types.MessageMediaPhoto) and isinstance(media.photo, types.Photo):
        return "photo", _photo_size(media.photo), "image/jpeg"
    if isinstance(media, types.MessageMediaDocument) and isinstance(media.document, types.Document):
        mime = media.document.mime_type or ""
        is_sticker = any(isinstance(a, types.DocumentAttributeSticker) for a in media.document.attributes)
        if mime.startswith("image/") and not is_sticker:
            return "photo", media.document.size, mime[:64]
    return "other", None, None


def from_telethon(message, peer) -> ChatMessage | None:
    """Return the message to store, or None if it must be ignored. `peer` is the user
    the private chat is with (for incoming messages that is also the sender)."""
    if not isinstance(message, types.Message) or not isinstance(message.peer_id, types.PeerUser):
        return None  # service messages, groups, channels
    if not is_customer_chat(peer) or message.peer_id.user_id != peer.id:
        return None
    text = message.message or ""
    kind, size, mime = media_info(message)
    if kind == "text" and not text.strip():
        return None
    name = " ".join(p for p in (peer.first_name, peer.last_name) if p) or None
    return ChatMessage(
        external_chat_id=str(peer.id),
        external_message_id=str(message.id),
        external_user_id=str(peer.id),
        username=peer.username,
        display_name=name,
        text=text,
        received_at=message.date,
        direction="out" if message.out else "in",
        kind=kind,
        grouped_id=str(message.grouped_id) if message.grouped_id else None,
        media_size=size,
        media_mime=mime,
    )


def upsert_customer(session: Session, msg: ChatMessage) -> int:
    stmt = insert(Customer).values(
        channel=CHANNEL, external_user_id=msg.external_user_id,
        username=msg.username, display_name=msg.display_name,
    )
    return session.execute(
        stmt.on_conflict_do_update(
            index_elements=["channel", "external_user_id"],
            set_={"username": stmt.excluded.username, "display_name": stmt.excluded.display_name},
        ).returning(Customer.id)
    ).scalar_one()


def insert_message(session: Session, msg: ChatMessage, customer_id: int) -> tuple[int, bool]:
    """Insert (idempotent). Returns (message id, inserted?)."""
    inserted = session.execute(
        insert(Message).values(
            channel=CHANNEL,
            external_chat_id=msg.external_chat_id,
            external_message_id=msg.external_message_id,
            customer_id=customer_id,
            raw_text=msg.text,
            normalized_text=normalize(msg.text, keep_newlines=True),
            received_at=msg.received_at,
            direction=msg.direction,
            kind=msg.kind,
            grouped_id=msg.grouped_id,
            media_size=msg.media_size,
            media_mime=msg.media_mime,
        ).on_conflict_do_nothing(index_elements=["channel", "external_chat_id", "external_message_id"])
        .returning(Message.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted, True
    existing = session.scalar(select(Message.id).where(
        Message.channel == CHANNEL, Message.external_chat_id == msg.external_chat_id,
        Message.external_message_id == msg.external_message_id))
    return existing, False


def save_message(session: Session, msg: ChatMessage) -> bool:
    """Upsert the customer and insert the message. Returns False if it already existed."""
    return insert_message(session, msg, upsert_customer(session, msg))[1]
