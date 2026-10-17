"""Our own check of every AI answer (docs/SPEC-v4.6-ai.md S1). Any problem -> the whole
result is rejected and treated as "AI unsure" (the message goes to Needs you as before)."""
from app.ai.prompt import Catalog
from app.ai.types import ACTIONS, INTENTS, LEARN_KINDS, AIResult
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
        if item.action is not None and item.action not in ACTIONS:
            problems.append(f"{where}: unknown action {item.action}")
        if item.candidates:
            if item.product_id is not None:
                problems.append(f"{where}: candidates with a product id")
            if any(c is None or c not in products for c in item.candidates) or len(set(item.candidates)) != len(
                    item.candidates):
                problems.append(f"{where}: unknown or repeated candidate")
    if result.intent == "modify_cart" and any(i.action is None for i in result.items):
        problems.append("modify_cart: every item needs an action")
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



REMOVE_NOT_IN_CART_PENALTY = 0.15


def effective_action(result: AIResult, item) -> str:
    """add | remove | ask_price: the item's own action, else what the message intent says."""
    if item.action:
        return item.action
    return {"remove": "remove", "ask_price": "ask_price", "ask_stock": "ask_price"}.get(result.intent, "add")


def removes_in_cart(result: AIResult, cart_product_ids: set[int]) -> tuple[AIResult, list[str]]:
    """docs/SPEC-v4.11-ai-first.md L2: "remove" only for products in the cart. Other removes are
    dropped and the confidence goes down (so an unsure answer goes to a person)."""
    kept, dropped = [], []
    for n, item in enumerate(result.items):
        if effective_action(result, item) == "remove" and item.product_id not in cart_product_ids:
            dropped.append(f"item {n + 1}: remove of a product that is not in the cart")
            continue
        kept.append(item)
    if not dropped:
        return result, []
    confidence = max(round(result.confidence - REMOVE_NOT_IN_CART_PENALTY * len(dropped), 2), 0.0)
    return AIResult(result.intent, tuple(kept), result.learn, confidence, result.reason, result.draft_answer), dropped
