"""Our own check of every AI answer (docs/SPEC-v4.6-ai.md S1). Any problem -> the whole
result is rejected and treated as "AI unsure" (the message goes to Needs you as before)."""
from app.ai.prompt import Catalog
from app.ai.types import INTENTS, LEARN_KINDS, AIResult
from app.parser.normalize import normalize

MAX_QTY = 20
LEARN_INTENTS = ("buy", "ask_price", "ask_stock", "remove", "cancel_order", "ask_delivery", "greeting",
                 "previous_item", "change_info")


def parse(data: dict) -> tuple[AIResult | None, list[str]]:
    try:
        return AIResult.from_json(data), []
    except (KeyError, TypeError, ValueError) as exc:
        return None, [f"invalid JSON ({type(exc).__name__})"]


def check(result: AIResult, catalog: Catalog, message_text: str) -> list[str]:
    """Problems found (empty = OK). message_text: what was sent as the customer message (masked)."""
    problems = []
    products = catalog.by_id()
    if result.intent not in INTENTS:
        problems.append(f"unknown intent {result.intent}")
    if not 0.0 <= result.confidence <= 1.0:
        problems.append("confidence outside 0-1")
    for n, item in enumerate(result.items):
        where = f"item {n + 1}"
        if item.product_id is not None:
            product = products.get(item.product_id)
            if product is None:
                problems.append(f"{where}: unknown or inactive product id {item.product_id}")
            elif item.size is not None and item.size not in product.sizes:
                problems.append(f"{where}: size {item.size} not sold for product {item.product_id}")
            if item.not_in_list:
                problems.append(f"{where}: not_in_list with a product id")
        if item.size is not None and item.size != "full" and item.size_ml is None:
            problems.append(f"{where}: bad size {item.size}")
        if not 1 <= item.qty <= MAX_QTY:
            problems.append(f"{where}: quantity {item.qty} outside 1-{MAX_QTY}")
    text = normalize(message_text)
    for n, learn in enumerate(result.learn):
        where = f"learn {n + 1}"
        if learn.kind not in LEARN_KINDS:
            problems.append(f"{where}: unknown kind")
            continue
        words = normalize(learn.text)
        if len(words.replace(" ", "")) < 2 or words not in text:
            problems.append(f"{where}: text not in the message")
        if "[" in words:
            problems.append(f"{where}: masked text")
        if learn.kind == "nickname" and (learn.product_id is None or learn.product_id not in products):
            problems.append(f"{where}: nickname without a known product")
        if learn.kind != "nickname" and learn.product_id is not None:
            problems.append(f"{where}: product id on a {learn.kind}")
        if learn.kind == "intent_phrase" and learn.intent not in LEARN_INTENTS:
            problems.append(f"{where}: phrase without a learnable intent")
    return problems

