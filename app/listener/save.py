"""Filter Telegram messages and save them. Used by both the live listener and the
history import, so both apply exactly the same rules.

Saves only: private chats, incoming, from a real user (not a bot, not ourselves,
not Telegram's service account), with text. Writes customers + messages only;
parsing and review state are other services' tables.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from telethon.tl import types

from app.models import Customer, Message
from app.parser.normalize import normalize

CHANNEL = "telegram"
TELEGRAM_SERVICE_USER_ID = 777000  # sends login codes; must never be stored


@dataclass(frozen=True)
class IncomingMessage:
    external_chat_id: str
    external_message_id: str
    external_user_id: str
    username: str | None
    display_name: str | None
    text: str
    received_at: datetime


def from_telethon(message, sender) -> IncomingMessage | None:
    """Return the message to store, or None if it must be ignored."""
    if message.out or not isinstance(message.peer_id, types.PeerUser):
        return None
    if not isinstance(sender, types.User):
        return None
    if sender.bot or sender.is_self or sender.support or sender.id == TELEGRAM_SERVICE_USER_ID:
        return None
    text = message.message or ""
    if not text.strip():  # media without caption, stickers, service messages
        return None
    name = " ".join(p for p in (sender.first_name, sender.last_name) if p) or None
    return IncomingMessage(
        external_chat_id=str(message.peer_id.user_id),
        external_message_id=str(message.id),
        external_user_id=str(sender.id),
        username=sender.username,
        display_name=name,
        text=text,
        received_at=message.date,
    )


def save_message(session: Session, msg: IncomingMessage) -> bool:
    """Upsert the customer and insert the message. Returns False if it already existed."""
    customer_stmt = insert(Customer).values(
        channel=CHANNEL,
        external_user_id=msg.external_user_id,
        username=msg.username,
        display_name=msg.display_name,
    )
    customer_id = session.execute(
        customer_stmt.on_conflict_do_update(
            index_elements=["channel", "external_user_id"],
            set_={
                "username": customer_stmt.excluded.username,
                "display_name": customer_stmt.excluded.display_name,
            },
        ).returning(Customer.id)
    ).scalar_one()

    inserted = session.execute(
        insert(Message)
        .values(
            channel=CHANNEL,
            external_chat_id=msg.external_chat_id,
            external_message_id=msg.external_message_id,
            customer_id=customer_id,
            raw_text=msg.text,
            normalized_text=normalize(msg.text),
            received_at=msg.received_at,
        )
        .on_conflict_do_nothing(
            index_elements=["channel", "external_chat_id", "external_message_id"]
        )
        .returning(Message.id)
    ).scalar_one_or_none()
    return inserted is not None
