"""S2 EVALUATION GATE (docs/SPEC-v4.6-ai.md): run tests/fixtures/ai_eval.csv against the REAL
AI provider with the live product list, print ✅/❌ per case, accuracy by field, cost and
latency, and save a report under data/exports/ (git-ignored).

PASS: intent+products correct >= 90%, ZERO wrong product ids, not_in_list never mapped.
Exit code 0 = pass, 1 = fail, 2 = could not run (no key / provider error on every case).

Usage: .venv/bin/python -m scripts.ai_eval [--reasoning low|medium] [--model NAME] [--only o01,o02]

Fixture columns: expect_intent "a/b" = either is right; expect_items "Name@5ml*2;!words@10ml"
(! = not in our list, ? = must stay unknown, size "any" = not checked, empty = no items, * = not checked;
`allowed` = products that may appear when items are not checked).
"""
import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.ai import prompt, providers
from app.ai import settings as ai_settings
from app.ai.privacy import mask
from app.ai.service import Understood, understand
from app.core.config import BASE_DIR
from app.core.db import SessionLocal
from app.models import Product

FIXTURE = BASE_DIR / "tests" / "fixtures" / "ai_eval.csv"
EXPORTS = BASE_DIR / "data" / "exports"
PASS_ACCURACY = 0.90


@dataclass(frozen=True)
class Expected:
    kind: str  # product | not_in_list | unclear
    product_id: int | None
    size: str | None  # "5ml" | "full" | None (no size) | "*" (any)
    qty: int


def parse_items(spec: str, ids: dict[str, int]) -> list[Expected] | None:
    """None = not checked."""
    spec = spec.strip()
    if spec == "*":
        return None
    out = []
    for part in filter(None, (p.strip() for p in spec.split(";"))):
        name, _, rest = part.partition("@")
        size, _, qty = (rest or "-").partition("*")
        size = None if size in ("", "-") else "*" if size == "any" else size
        kind = "not_in_list" if name.startswith("!") else "unclear" if name.startswith("?") else "product"
        pid = ids[name.lower()] if kind == "product" else None
        out.append(Expected(kind, pid, size, int(qty or 1)))
    return out


@dataclass
class Score:
    intent: bool
    products: bool
    sizes: bool
    qty: bool
    not_in_list: bool
    wrong_product: bool  # a product id that is not one of the expected ones
    nil_mapped: bool  # a not-in-list case mapped to a product
    notes: list[str]


def score(row: dict, got: Understood, ids: dict[str, int]) -> Score:
    expected = parse_items(row["expect_items"], ids)
    allowed = {ids[n.strip().lower()] for n in row.get("allowed", "").split(";") if n.strip()}
    r = got.result
    notes = []
    if r is None:
        return Score(False, False, False, False, False, False, False, ["no result: " + ", ".join(got.problems)])
    intent_ok = r.intent in row["expect_intent"].split("/")
    if not intent_ok:
        notes.append(f"intent {r.intent} (want {row['expect_intent']})")
    got_pids = [i.product_id for i in r.items if i.product_id is not None]
    if expected is None:
        wrong = [p for p in got_pids if p not in allowed]
        if wrong:
            notes.append(f"unexpected product ids {wrong}")
        return Score(intent_ok, not wrong, True, True, True, bool(wrong), False, notes)
    want_pids = [e.product_id for e in expected if e.kind == "product"]
    wrong = [p for p in got_pids if p not in want_pids]
    products_ok = Counter(got_pids) == Counter(want_pids)
    nil_wanted = sum(e.kind == "not_in_list" for e in expected)
    nil_got = sum(1 for i in r.items if i.product_id is None and i.not_in_list)
    nil_ok = nil_got == nil_wanted
    nil_mapped = nil_wanted > 0 and bool(wrong)
    if not products_ok:
        notes.append(f"products {got_pids} (want {want_pids})")
    if not nil_ok:
        notes.append(f"not_in_list {nil_got} (want {nil_wanted})")
    sizes_ok = qty_ok = True
    for e in expected:
        if e.kind == "product":
            match = next((i for i in r.items if i.product_id == e.product_id), None)
        else:
            match = next((i for i in r.items if i.product_id is None), None)
        if match is None:
            continue
        if e.size != "*" and match.size != e.size:
            sizes_ok = False
            notes.append(f"size {match.size} (want {e.size})")
        if match.qty != e.qty:
            qty_ok = False
            notes.append(f"qty {match.qty} (want {e.qty})")
    return Score(intent_ok, products_ok and nil_ok, sizes_ok, qty_ok, nil_ok, bool(wrong), nil_mapped, notes)


def context(row: dict) -> prompt.Context:
    history = tuple(f"{h[:1]}: {mask(h[2:].strip())}" for h in row["history"].split("|") if h.strip())
    cart = tuple(x.strip() for x in row["cart"].split(";") if x.strip())
    paid = tuple(x.strip() for x in row["last_paid"].split(";") if x.strip())
    return prompt.Context(mask(row["message"]), history, cart, paid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reasoning", choices=ai_settings.REASONING)
    parser.add_argument("--model")
    parser.add_argument("--only", help="comma-separated case ids")
    args = parser.parse_args()
    provider = providers.get()
    if provider is None:
        print("AI provider is off or OPENAI_API_KEY is missing in .env")
        return 2
    with SessionLocal() as session:
        cfg = ai_settings.load(session)
        catalog = prompt.load_catalog(session)
        ids = {name.lower(): pid for pid, name in session.execute(select(Product.id, Product.name)
                                                                  .where(Product.active))}
    model, reasoning = args.model or cfg["model"], args.reasoning or cfg["reasoning"]
    rows = list(csv.DictReader(FIXTURE.open(encoding="utf-8")))
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in wanted]
    print(f"AI evaluation: {len(rows)} cases, model {model}, reasoning {reasoning}\n")
    results = []
    for row in rows:
        got = understand(provider, catalog, context(row), model, reasoning)
        s = score(row, got, ids)
        ok = s.intent and s.products and not s.wrong_product
        results.append((row, got, s, ok))
        mark = "✅" if ok else "❌"
        extra = "" if ok else "  <- " + "; ".join(s.notes)
        print(f"{mark} {row['id']:4} {row['message'][:48]:48} {got.result.intent if got.result else '-':13}"
              f"{(got.result.confidence if got.result else 0):.2f}{extra}")
    n = len(results) or 1
    answered = [x for x in results if x[1].result is not None]
    if not answered:
        print("\nNo case got an answer:", Counter(p for x in results for p in x[1].problems).most_common(3))
        return 2
    field_acc = {f: sum(getattr(x[2], f) for x in results) / n
                 for f in ("intent", "products", "sizes", "qty", "not_in_list")}
    both = sum(x[3] for x in results) / n
    wrong = sum(x[2].wrong_product for x in results)
    nil_mapped = sum(x[2].nil_mapped for x in results)
    cost = sum(x[1].cost for x in results)
    latency = sum(x[1].latency_ms for x in answered) / len(answered)
    cached = sum(x[1].cached_tokens for x in results)
    tokens_in = sum(x[1].input_tokens for x in results)
    passed = both >= PASS_ACCURACY and wrong == 0 and nil_mapped == 0
    summary = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"), "model": model, "reasoning": reasoning,
        "cases": len(results), "intent_and_products": round(both, 3),
        "by_field": {k: round(v, 3) for k, v in field_acc.items()}, "wrong_product_cases": wrong,
        "not_in_list_mapped": nil_mapped, "cost_usd": round(cost, 5), "avg_latency_ms": round(latency),
        "input_tokens": tokens_in, "cached_tokens": cached, "rejected_or_errors": len(results) - len(answered)
                                                                                  + sum(bool(x[1].problems) for x in answered),
        "passed": passed,
    }
    print(f"\nintent+products {both:.0%} (need {PASS_ACCURACY:.0%}) · wrong product ids in {wrong} cases (need 0) · "
          f"not_in_list mapped {nil_mapped} (need 0)")
    print("by field: " + " · ".join(f"{k} {v:.0%}" for k, v in field_acc.items()))
    print(f"cost ${cost:.4f} · avg latency {latency:.0f} ms · cached input {cached}/{tokens_in} tokens")
    print("PASS ✅" if passed else "FAIL ❌")
    EXPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = EXPORTS / f"ai_eval_{stamp}.json"
    report.write_text(json.dumps({"summary": summary, "cases": [
        {"id": r["id"], "ok": ok, "notes": s.notes, "result": g.result.to_json() if g.result else None,
         "problems": g.problems, "latency_ms": g.latency_ms, "cost_usd": g.cost}
        for r, g, s, ok in results]}, ensure_ascii=False, indent=1), encoding="utf-8")
    report.chmod(0o600)
    (EXPORTS / "ai_eval_latest.json").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"report: {report.relative_to(BASE_DIR)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
