"""What the AI answers (the strict JSON schema in prompt.py has the same shape)."""
from dataclasses import asdict, dataclass

INTENTS = ("buy", "ask_price", "ask_stock", "remove", "cancel_order", "confirm", "done", "address", "ask_delivery",
           "greeting", "previous_item", "change_info", "payment_sent", "modify_cart", "question", "other")
LEARN_KINDS = ("nickname", "intent_phrase", "not_stocked")
ACTIONS = ("add", "remove", "ask_price")  # docs/SPEC-v4.11-ai-first.md L2


@dataclass(frozen=True)
class AIItem:
    product_id: int | None
    size: str | None  # "5ml" | "full" | None
    qty: int
    not_in_list: str | None  # the customer's words for a perfume we don't have
    unclear_text: str | None  # words the AI could not map
    action: str | None = None  # add | remove | ask_price (L2); None = what the intent says
    candidates: tuple[int, ...] = ()  # 2-3 listed products it may be (L3: the customer chooses)

    @property
    def is_full(self) -> bool:
        return self.size == "full"

    @property
    def size_ml(self) -> int | None:
        if self.size and self.size.endswith("ml") and self.size[:-2].isdigit():
            return int(self.size[:-2])
        return None


@dataclass(frozen=True)
class AILearn:
    text: str
    kind: str
    product_id: int | None
    intent: str | None


@dataclass(frozen=True)
class AIResult:
    intent: str
    items: tuple[AIItem, ...]
    learn: tuple[AILearn, ...]
    confidence: float
    reason: str
    draft_answer: str | None
    address: dict | None = None  # docs/SPEC-v4.12-address-payment-ai.md N1 (only with ai_address ON)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "AIResult":
        """ValueError / TypeError / KeyError when the shape is wrong (the checker treats that as
        "invalid JSON")."""
        if not isinstance(data, dict):
            raise ValueError("not an object")
        items = tuple(AIItem(_opt_int(i["product_id"]), _opt_str(i["size"]), int(i["qty"]),
                             _opt_str(i["not_in_list"]), _opt_str(i["unclear_text"]),
                             _opt_str(i.get("action")),  # missing in answers stored before v4.11
                             tuple(_opt_int(c) for c in (i.get("candidates") or []))) for i in data["items"])
        learn = tuple(AILearn(str(x["text"]), str(x["kind"]), _opt_int(x["product_id"]), _opt_str(x["intent"]))
                      for x in data["learn"])
        confidence = float(data["confidence"])
        address = data.get("address")
        if address is not None and (not isinstance(address, dict) or not isinstance(address.get("full_text", ""),
                                                                                    (str, type(None)))):
            raise ValueError("address is not an object")
        return cls(str(data["intent"]), items, learn, confidence, str(data["reason"] or "")[:300],
                   _opt_str(data["draft_answer"]), address)


def _opt_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer")
    return value


def _opt_str(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected a string")
    return value.strip() or None
