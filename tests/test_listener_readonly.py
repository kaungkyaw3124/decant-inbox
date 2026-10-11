"""Guard for the hard rule: the Telegram account is read-only, except that
app/listener/sender.py may call send_message (once) to send what an admin queued.
Never edit, delete, forward, pin or mark-read anywhere."""
import ast
from pathlib import Path

APP_DIR = Path(__file__).parent.parent / "app"
FORBIDDEN = {
    "send_message", "send_file", "reply", "respond", "edit", "edit_message", "delete",
    "delete_messages", "delete_dialog", "forward_to", "forward_messages", "pin", "unpin",
    "pin_message", "unpin_message", "mark_read", "send_read_acknowledge", "action",
    "ReadHistoryRequest", "ReadMessageContentsRequest", "SendMessageRequest",
    "UpdateStatusRequest", "SendMediaRequest", "EditMessageRequest", "DeleteMessagesRequest",
    "ForwardMessagesRequest", "UpdatePinnedMessageRequest",
}
SENDER = APP_DIR / "listener" / "sender.py"


def names(path: Path) -> list[tuple[str, int]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Attribute):
            found.append((node.attr, node.lineno))
        elif isinstance(node, ast.Name):
            found.append((node.id, node.lineno))
    return found


def test_only_the_sender_writes_to_telegram():
    offenders = []
    for path in (APP_DIR / "listener").rglob("*.py"):
        for name, line in names(path):
            if name in FORBIDDEN and not (path == SENDER and name == "send_message"):
                offenders.append(f"{path.relative_to(APP_DIR)}:{line} {name}")
    assert not offenders, f"write calls on the Telegram account: {offenders}"


def test_sender_sends_once_and_only_the_listener_uses_telethon():
    assert [n for n, _ in names(SENDER)].count("send_message") == 1
    for path in APP_DIR.rglob("*.py"):
        if (APP_DIR / "listener") not in path.parents:
            assert "telethon" not in path.read_text(), f"{path.relative_to(APP_DIR)} must not use Telethon"
