"""Guard for the hard rule: the Telegram account is READ-ONLY."""
import ast
from pathlib import Path

LISTENER_DIR = Path(__file__).parent.parent / "app" / "listener"
FORBIDDEN = {
    "send_message", "send_file", "reply", "respond", "edit", "edit_message", "delete",
    "delete_messages", "delete_dialog", "forward_to", "forward_messages", "pin", "unpin",
    "pin_message", "unpin_message", "mark_read", "send_read_acknowledge", "action",
    "ReadHistoryRequest", "ReadMessageContentsRequest", "SendMessageRequest",
    "UpdateStatusRequest",
}


def test_listener_code_never_calls_write_methods():
    offenders = []
    for path in LISTENER_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            name = None
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            if name in FORBIDDEN:
                offenders.append(f"{path.name}:{node.lineno} {name}")
    assert not offenders, f"write calls on the Telegram account: {offenders}"
