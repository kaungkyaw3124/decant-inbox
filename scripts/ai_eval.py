"""S2 EVALUATION GATE (docs/SPEC-v4.6-ai.md): run tests/fixtures/ai_eval.csv against the REAL
AI provider with the live product list, print ✅/❌ per case, accuracy by field, cost and
latency, and save a report under data/exports/ (git-ignored).

PASS: intent+products correct >= 90%, ZERO wrong product ids, not_in_list never mapped, and (v4.11) "remove"
only for products in the case's cart.
Exit code 0 = pass, 1 = fail, 2 = could not run (no key / provider error on every case).

Usage: .venv/bin/python -m scripts.ai_eval [--reasoning low|medium] [--model NAME] [--only o01,o02]

Fixture columns: expect_intent "a/b" = either is right; expect_items "Name@5ml*2;!words@10ml"
(! = not in our list, ? = must stay unknown, size "any" = not checked, empty = no items, * = not checked;
`allowed` = products that may appear when items are not checked).
docs/SPEC-v4.11-ai-first.md: ">remove" / ">add" / ">ask_price" after an item = its action must be that;
"?ysl@10ml{Y Eau de Parfum|Libre}" = unknown with candidates: the AI must offer 2-3 of those (never others).

docs/SPEC-v4.12-address-payment-ai.md:
  --addresses  tests/fixtures/ai_eval_address.csv through the AI + our validator (the same code as the
               app). PASS: township correct >= 95%, full_text never contains a phone (the AI's text and the
               saved text), 0 keyword-only messages accepted as an address.
  --screens    tests/fixtures/payment_screens/ (synthetic receipts) through the screenshot reader. PASS:
               amount exact >= 95%, transaction_no exact >= 90%, is_payment_receipt correct 100%.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.ai import checker, prompt, providers
from app.ai import settings as ai_settings
from app.ai.privacy import mask
from app.ai.service import Understood, understand
from app.core.config import BASE_DIR
from app.core.db import SessionLocal
from app.models import Product

FIXTURE = BASE_DIR / "tests" / "fixtures" / "ai_eval.csv"
ADDRESS_FIXTURE = BASE_DIR / "tests" / "fixtures" / "ai_eval_address.csv"
PASS_TOWNSHIP = 0.95
_PHONE = re.compile(r"\[PHONE\]|(?:\+?95|0)\s*9(?:[\s-]?\d){7,9}")
EXPORTS = BASE_DIR / "data" / "exports"
PASS_ACCURACY = 0.90


@dataclass(frozen=True)
class Expected:
    kind: str  # product | not_in_list | unclear
    product_id: int | None
    size: str | None  # "5ml" | "full" | None (no size) | "*" (any)
    qty: int
    action: str | None = None  # v4.11: add | remove | ask_price (None = not checked)
    candidates: frozenset[int] = frozenset()  # v4.11: the AI should offer 2-3 of these


def parse_items(spec: str, ids: dict[str, int]) -> list[Expected] | None:
    """None = not checked."""
    spec = spec.strip()
    if spec == "*":
        return None
    out = []
    for part in filter(None, (p.strip() for p in spec.split(";"))):
        part, _, action = part.partition(">")
        part, _, candidates = part.partition("{")
        name, _, rest = part.partition("@")
        size, _, qty = (rest or "-").partition("*")
        size = None if size in ("", "-") else "*" if size == "any" else size
        kind = "not_in_list" if name.startswith("!") else "unclear" if name.startswith("?") else "product"
        pid = ids[name.lower()] if kind == "product" else None
        options = frozenset(ids[c.strip().lower()] for c in candidates.rstrip("}").split("|") if c.strip())
        out.append(Expected(kind, pid, size, int(qty or 1), action.strip() or None, options))
    return out


def cart_ids(row: dict, ids: dict[str, int]) -> set[int]:
    """Products in the case's cart ("Y Eau de Parfum 10ml x1; ...")."""
    found = set()
    for line in filter(None, (x.strip().lower() for x in row.get("cart", "").split(";"))):
        name = max((n for n in ids if line.startswith(n)), key=len, default=None)
        if name:
            found.add(ids[name])
    return found


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
    remove_not_in_cart: bool = False  # v4.11: "remove" of a product that is not in the cart


def score(row: dict, got: Understood, ids: dict[str, int]) -> Score:
    expected = parse_items(row["expect_items"], ids)
    allowed = {ids[n.strip().lower()] for n in row.get("allowed", "").split(";") if n.strip()}
    r = got.result
    notes = []
    if r is None:
        return Score(False, False, False, False, False, False, False, ["no result: " + ", ".join(got.problems)])
    in_cart = cart_ids(row, ids)
    bad_remove = any(checker.effective_action(r, i) == "remove" and i.product_id not in in_cart for i in r.items)
    if bad_remove:
        notes.append("remove of a product that is not in the cart")
    intent_ok = r.intent in row["expect_intent"].split("/")
    if not intent_ok:
        notes.append(f"intent {r.intent} (want {row['expect_intent']})")
    got_pids = [i.product_id for i in r.items if i.product_id is not None]
    if expected is None:
        wrong = [p for p in got_pids if p not in allowed]
        if wrong:
            notes.append(f"unexpected product ids {wrong}")
        return Score(intent_ok, not wrong, True, True, True, bool(wrong), False, notes, bad_remove)
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
            match = next((i for i in r.items if i.product_id is None and bool(i.not_in_list) == (
                e.kind == "not_in_list")), None)
        if match is None:
            continue
        if e.size != "*" and match.size != e.size:
            sizes_ok = False
            notes.append(f"size {match.size} (want {e.size})")
        if match.qty != e.qty:
            qty_ok = False
            notes.append(f"qty {match.qty} (want {e.qty})")
        if e.action and checker.effective_action(r, match) != e.action:
            products_ok = False
            notes.append(f"action {checker.effective_action(r, match)} (want {e.action})")
        if e.candidates and not (2 <= len(match.candidates) <= 3 and set(match.candidates) <= e.candidates):
            products_ok = False
            notes.append(f"candidates {list(match.candidates)} (want 2-3 of {sorted(e.candidates)})")
    return Score(intent_ok, products_ok and nil_ok, sizes_ok, qty_ok, nil_ok, bool(wrong), nil_mapped, notes,
                 bad_remove)


def context(row: dict, with_address: bool = False) -> prompt.Context:
    """with_address: as the app sends it with the owner's switch ai_address ON (docs/SPEC-v4.12)."""
    history = tuple(f"{h[:1]}: {mask(h[2:].strip(), with_address)}" for h in row["history"].split("|") if h.strip())
    cart = tuple(x.strip() for x in row["cart"].split(";") if x.strip())
    paid = tuple(x.strip() for x in row["last_paid"].split(";") if x.strip())
    return prompt.Context(mask(row["message"], with_address), history, cart, paid, with_address)


def _save(name: str, summary: dict, cases: list[dict]) -> None:
    EXPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = EXPORTS / f"{name}_{stamp}.json"
    report.write_text(json.dumps({"summary": summary, "cases": cases}, ensure_ascii=False, indent=1), encoding="utf-8")
    report.chmod(0o600)
    latest = EXPORTS / f"{name}_latest.json"
    latest.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    latest.chmod(0o600)
    print(f"report: {report.relative_to(BASE_DIR)}")


def eval_addresses(provider, catalog: prompt.Catalog, model: str, reasoning: str, only: set[str] | None) -> int:
    from app.orders import address

    rows = [r for r in csv.DictReader(ADDRESS_FIXTURE.open(encoding="utf-8")) if not only or r["id"] in only]
    print(f"Address evaluation: {len(rows)} cases, model {model}, reasoning {reasoning}\n")
    cases, township_ok, township_n, phones, keyword_accepted, cost, errors = [], 0, 0, 0, 0, 0.0, 0
    for row in rows:
        ctx = prompt.Context(mask(row["message"], True), (), (), (), True, row["asked"] or None,
                             mask(row["partial"], True) if row["partial"] else None)
        got = understand(provider, catalog, ctx, model, reasoning)
        cost += got.cost
        notes = []
        if got.result is None:
            errors += 1
            notes.append("no result: " + ", ".join(got.problems))
        raw = (got.result.address or {}) if got.result else {}
        partial = {"full_text": row["partial"]} if row["partial"] else None
        check = address.combine({"address": got.result.address} if got.result else None,
                                address.from_rules(row["message"]), partial)
        accepted = check is not None and check.status in ("valid", "partial")
        status = check.status if check else "none"
        township = check.township.en if check is not None and check.township else ""
        ok = True
        if row["expect_status"] == "none":
            if accepted:
                keyword_accepted, ok = keyword_accepted + 1, False
                notes.append(f"accepted as an address ({status}: {check.parts.full_text})")
        else:
            township_n += 1
            if township == row["expect_township"]:
                township_ok += 1
            else:
                ok = False
                notes.append(f"township {township or '-'} (want {row['expect_township'] or '-'})")
            if status != row["expect_status"]:
                notes.append(f"status {status} (want {row['expect_status']})")  # shown, not part of the gate
        phone = bool(_PHONE.search(raw.get("full_text") or "")) or bool(
            check is not None and _PHONE.search(check.parts.full_text.translate(str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789"))))
        if phone:
            phones, ok = phones + 1, False
            notes.append("phone in full_text")
        print(f"{'✅' if ok else '❌'} {row['id']:4} {row['message'][:44]:44} {status:8} {township or '-':16}"
              + ("" if ok else "  <- " + "; ".join(notes)) + (f"  ({'; '.join(notes)})" if ok and notes else ""))
        cases.append({"id": row["id"], "ok": ok, "notes": notes, "status": status, "township": township,
                      "ai_address": raw or None, "saved_text": check.parts.full_text if check else None,
                      "cost_usd": got.cost})
    acc = township_ok / (township_n or 1)
    passed = acc >= PASS_TOWNSHIP and phones == 0 and keyword_accepted == 0 and errors < len(rows)
    summary = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "model": model, "reasoning": reasoning,
               "cases": len(rows), "township_correct": round(acc, 3), "phone_in_full_text": phones,
               "keyword_only_accepted": keyword_accepted, "errors": errors, "cost_usd": round(cost, 5),
               "passed": passed}
    print(f"\ntownship correct {acc:.0%} (need {PASS_TOWNSHIP:.0%}) · phone in full_text {phones} (need 0) · "
          f"keyword-only accepted {keyword_accepted} (need 0) · errors {errors} · cost ${cost:.4f}")
    print("PASS ✅" if passed else "FAIL ❌")
    _save("ai_eval_address", summary, cases)
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reasoning", choices=ai_settings.REASONING)
    parser.add_argument("--model")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--addresses", action="store_true", help="the 4.12 address set instead")
    parser.add_argument("--screens", action="store_true", help="the 4.12 payment-screenshot set instead")
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
    only = set(args.only.split(",")) if args.only else None
    if args.addresses:
        return eval_addresses(provider, catalog, model, reasoning, only)
    if args.screens:
        from app.ai import screens

        return screens.evaluate(provider, model, reasoning, only)
    rows = list(csv.DictReader(FIXTURE.open(encoding="utf-8")))
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in wanted]
    print(f"AI evaluation: {len(rows)} cases, model {model}, reasoning {reasoning}\n")
    results = []
    raw_bad_removes = 0
    for row in rows:
        got = understand(provider, catalog, context(row, bool(cfg["ai_address"])), model, reasoning)
        if got.result is not None:  # the same cart check as AUTO (service.auto_apply): removes only from the cart
            raw_bad_removes += score(row, got, ids).remove_not_in_cart
            got.result, dropped = checker.removes_in_cart(got.result, cart_ids(row, ids))
            got.problems = got.problems + dropped if dropped else got.problems
        s = score(row, got, ids)
        ok = s.intent and s.products and not s.wrong_product and not s.remove_not_in_cart
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
    bad_removes = sum(x[2].remove_not_in_cart for x in results)
    cost = sum(x[1].cost for x in results)
    latency = sum(x[1].latency_ms for x in answered) / len(answered)
    cached = sum(x[1].cached_tokens for x in results)
    tokens_in = sum(x[1].input_tokens for x in results)
    passed = both >= PASS_ACCURACY and wrong == 0 and nil_mapped == 0 and bad_removes == 0
    summary = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"), "model": model, "reasoning": reasoning,
        "cases": len(results), "with_address": bool(cfg["ai_address"]), "intent_and_products": round(both, 3),
        "by_field": {k: round(v, 3) for k, v in field_acc.items()}, "wrong_product_cases": wrong,
        "not_in_list_mapped": nil_mapped, "remove_not_in_cart": bad_removes,
        "remove_not_in_cart_before_checker": raw_bad_removes, "cost_usd": round(cost, 5), "avg_latency_ms": round(latency),
        "input_tokens": tokens_in, "cached_tokens": cached, "rejected_or_errors": len(results) - len(answered)
                                                                                  + sum(bool(x[1].problems) for x in answered),
        "passed": passed,
    }
    print(f"\nintent+products {both:.0%} (need {PASS_ACCURACY:.0%}) · wrong product ids in {wrong} cases (need 0) · "
          f"not_in_list mapped {nil_mapped} (need 0) · remove not in cart {bad_removes} (need 0; "
          f"{raw_bad_removes} dropped by the cart check)")
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
