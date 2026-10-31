"""docs/SPEC-v4.20-automation-goal.md A1: generated simulator scenarios -> tests/sim/scenarios/50_generated.yaml.

Our code picks WHAT each customer wants (persona, product, size, quantity, intent, contact) from the TEST catalog
and computes every expected fact (prices from scripts/make_sample_prices.py, never from the AI). The AI only
writes HOW the customer says it (Burmese / English / mixed / Zawgyi / typos / nicknames). A rules check rejects
a written text that contradicts the facts (another size number, a missing product word, a price in it ...).
No real customer data. Re-run only to refresh the wording; commit the YAML.

Usage: .venv/bin/python -m scripts.sim_generate [--n 100] [--seed 4200]   (needs OPENAI_API_KEY; ~$0.01)
"""
import argparse
import csv
import random
import re
import sys

import yaml

from app.core.config import BASE_DIR, get_settings
from scripts.make_sample_prices import SAMPLE

OUT = BASE_DIR / "tests" / "sim" / "scenarios" / "50_generated.yaml"
PERSONAS = {
    "burmese": "writes only in Burmese (Unicode), polite, uses words like ရှင့် / ခင်ဗျာ / နော်",
    "english": "writes only in simple English, short",
    "mixed": "mixes Burmese and English in one sentence, like most Myanmar online shoppers",
    "zawgyi": "types Burmese with the old Zawgyi font encoding (e.g. ဝယ္ခ်င္တယ္, ရွိလား), product names in English",
    "typos": "makes small spelling mistakes in the product name (one letter wrong or missing), lowercase",
    "nickname": "uses the given nickname of the product, not the full name",
    "chatty": "writes a long friendly message with some small talk around the request",
    "terse": "writes the shortest possible message",
}
INTENT_WORDS = {
    "buy": "wants to BUY it (order it)",
    "ask_price": "asks the PRICE",
    "ask_stock": "asks whether it is IN STOCK / available",
}
ADDRESSES = [  # (text, township or city piece the judge checks)
    ("အမှတ် 21 ၊ ဗိုလ်ချုပ်လမ်း ၊ ဗဟန်းမြို့နယ်", "township", "Bahan"),
    ("No. 5, Pyay Road, Kamayut", "township", "Kamayut"),
    ("အမှတ် 88 ၊ သုခလမ်း ၊ လှိုင်မြို့နယ်", "township", "Hlaing"),
    ("62 x 30 လမ်း", "city", "Mandalay"),
    ("66 str 28 str", "city", "Mandalay"),
]
MY_DIGITS = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["texts"],
          "properties": {"texts": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["n", "text"],
              "properties": {"n": {"type": "integer"}, "text": {"type": "string"}}}}}}
INSTRUCTIONS = """You write realistic Telegram messages that customers of a small perfume DECANT shop in Myanmar send.
For every numbered request write ONE customer message that says exactly what is asked: the product, the size
(if given; "full" = the full bottle) and the quantity (if more than 1), in the persona's style. Never add other
products, sizes, prices, phone numbers or addresses. Do not answer as the shop. Output JSON only."""


def catalog() -> list[dict]:
    aliases: dict[str, list[str]] = {}
    with open(BASE_DIR / "data" / "aliases.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            aliases.setdefault(row["product_name"], []).append(row["alias"])
    return [{"brand": b, "name": n, "full_ml": ml, "full": full, "sizes": {2: p2, 5: p5, 10: p10}, "stock": stock,
             "aliases": aliases.get(n, [])}
            for b, n, ml, full, p2, p5, p10, stock in SAMPLE]


def fmt(n: int) -> str:
    return f"{n:,}"


def plan(n: int, rng: random.Random) -> list[dict]:
    """What each generated customer wants (no wording yet)."""
    products = [p for p in catalog() if p["stock"]]
    out = []
    for k in range(n):
        p = rng.choice(products)
        persona = rng.choice(list(PERSONAS))
        kind = rng.choices(["single", "flow", "not_sold"], [55, 30, 15])[0]
        sold = [s for s, price in p["sizes"].items() if price]
        if kind == "not_sold":
            size = rng.choice([s for s in (3, 15, 20, 30) if s != p["full_ml"]])
            intent = rng.choice(["buy", "ask_stock"])
        else:
            size = rng.choice(sold)
            intent = "buy" if kind == "flow" else rng.choice(list(INTENT_WORDS))
        qty = rng.choice([1, 1, 1, 2]) if intent == "buy" and kind != "not_sold" else 1
        nick = rng.choice(p["aliases"]) if persona == "nickname" and p["aliases"] else None
        out.append({"k": k, "product": p, "persona": persona, "kind": kind, "size": size, "intent": intent,
                    "qty": qty, "nickname": nick, "address": rng.choice(ADDRESSES),
                    "phone": f"0942{rng.randint(1000000, 9999999)}"})
    return out


def request_line(r: dict) -> str:
    p = r["product"]
    name = f'"{r["nickname"]}" (nickname)' if r["nickname"] else f'{p["brand"]} {p["name"]}'
    qty = f", quantity {r['qty']}" if r["qty"] > 1 else ""
    return (f'{r["k"]}. persona: {PERSONAS[r["persona"]]}. Product: {name}, size {r["size"]}ml{qty}. '
            f'The customer {INTENT_WORDS[r["intent"]]}.')


def check(r: dict, text: str) -> str | None:
    """Why this written text contradicts the plan (None = fine)."""
    flat = text.translate(MY_DIGITS).lower()
    numbers = set(re.findall(r"\d+", flat))
    if str(r["size"]) not in numbers:
        return "size number missing"
    extra = numbers - {str(r["size"]), str(r["qty"]), "540", "1"}  # "Baccarat Rouge 540", "1 Million"
    if extra:
        return f"other numbers {sorted(extra)}"
    if r["qty"] > 1 and str(r["qty"]) not in numbers:
        return "quantity missing"
    if "ကျပ်" in text or "ks" in flat or "mmk" in flat:
        return "a price in the text"
    words = {w for alias in [r["product"]["name"], *r["product"]["aliases"]] for w in alias.lower().split() if len(w) > 2}
    if r["persona"] != "typos" and not any(w in flat for w in words):
        return "product not named"
    return None


def scenario(r: dict, text: str) -> dict:
    p, size = r["product"], r["size"]
    price = p["sizes"].get(size)
    tags = ["generated", r["persona"], r["kind"], r["intent"]]
    if r["kind"] == "not_sold":
        first = {"reply": "auto", "contains": [f"{size}ml မရှိပါဘူး", "ဘယ် size ယူမလဲ"], "products": [p["name"]]}
        if r["intent"] == "buy":
            first["cart"] = []
        return {"id": f"gen-{r['k']:03d}", "hand": False, "tags": tags, "turns": [{"say": text, "expect": first}]}
    line = f"{p['name']} {size}ml"
    if r["intent"] == "buy":
        total = price * r["qty"]
        first = {"reply": "auto", "contains": [fmt(total)], "cart": [f"{line} x{r['qty']}"]}
    else:
        first = {"reply": "auto", "contains": [fmt(price)], "cart": [], "products": [p["name"]]}
    turns = [{"say": text, "expect": first}]
    if r["kind"] == "flow":
        address, key, piece = r["address"]
        turns += [{"say": r["phone"], "expect": {"reply": "auto", "contains": [r["phone"], "လိပ်စာ"],
                                                  "phone": r["phone"]}},
                  {"say": address, "expect": {"reply": "auto", "contains": ["KPay – 09000000001", fmt(price * r["qty"])],
                                              "status": "waiting_payment", key: piece}}]
    return {"id": f"gen-{r['k']:03d}", "hand": False, "tags": tags, "turns": turns}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=4200)
    args = parser.parse_args()
    from app.ai import providers

    s = get_settings()
    if s.openai_api_key is None:
        print("needs OPENAI_API_KEY in .env")
        return 2
    ai = providers.OpenAIProvider(s.openai_api_key.get_secret_value(), 60)
    rng = random.Random(args.seed)
    wanted, scenarios, rejected, cost = plan(args.n * 2, rng), [], [], 0.0  # twice as many: some get rejected
    for start in range(0, len(wanted), 20):
        if len(scenarios) >= args.n:
            break
        batch = wanted[start:start + 20]
        reply = ai._call(INSTRUCTIONS, SCHEMA, "\n".join(request_line(r) for r in batch), s.ai_model, "low",
                         "customer_messages")
        cost += providers.cost_usd(reply.input_tokens, reply.cached_tokens, reply.output_tokens)
        written = {t["n"]: t["text"].strip() for t in reply.data.get("texts", [])}
        for r in batch:
            text = written.get(r["k"])
            why = "not written" if not text else check(r, text)
            if why:
                rejected.append((r["k"], why))
            elif len(scenarios) < args.n:
                scenarios.append(scenario(r, text))
    header = ("# GENERATED by scripts/sim_generate.py (seed %d): the AI wrote the wording, our code the facts and\n"
              "# expectations (TEST prices). hand: false. Rejected by the rules check: %d. Do not edit by hand.\n"
              % (args.seed, len(rejected)))
    OUT.write_text(header + yaml.safe_dump(scenarios, allow_unicode=True, sort_keys=False, width=120))
    print(f"wrote {len(scenarios)} scenarios to {OUT.relative_to(BASE_DIR)}; rejected {len(rejected)}: "
          f"{dict((w, sum(1 for _, x in rejected if x == w)) for _, w in rejected)}; cost ${cost:.4f}")
    return 0 if len(scenarios) >= args.n else 1


if __name__ == "__main__":
    sys.exit(main())
