"""docs/SPEC-v4.6-ai.md acceptance tests F1-F11 (fake provider, no network) + the AI page.
Customer messages in -> AI step (fake answers) -> cards / auto replies out -> DB state checked."""
import html
import re
from datetime import UTC, datetime, timedelta

import httpx2
import openai
import pytest
from sqlalchemy import text

from app.ai import checker, privacy, prompt, providers, service
from app.ai import settings as ai_settings
from app.ai.providers import AIError, FakeProvider
from app.ai.types import AIResult
from app.core.db import SessionLocal
from app.learning import patterns
from app.orders import auto
from scripts.reparse_all import reparse_all
from tests.test_cart import START, deliver, items, say, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, scalar
from tests.test_prices import run_import, xlsx
from tests.test_v4_teaching import auto_on, card_page, confirm, learned, outbox, pid, preview, y_shop
from tests.test_web import client, log_in  # noqa: F401  (fixture)

GOOD_GIRL = ["Carolina Herrera", "Good Girl", 80, 300000, 7000, 15000, 28000, "yes"]
YSL = "ysl edp 10 ml ရောယူပါမယ်"
HAWAS = "hawas for him 10ml ယူမယ်"
QUESTION = "ဒီအနံ့က ဘယ်လိုမျိုးလဲ ညနေဘက်သုံးလို့ရလား"
DRAFT = "ညနေဘက်လည်း သုံးလို့ရပါတယ်ရှင့်။"
Y_LIST = "• Y Eau de Parfum 10ml – 34,000 ကျပ်\nစုစုပေါင်း 34,000 ကျပ်ပါ။\nဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"


def answer(intent="buy", items=(), learn=(), confidence=0.95, reason="test reason", draft=None) -> dict:
    """items: (product_id, size, qty, not_in_list, unclear_text); learn: (text, kind, product_id, intent)."""
    return {"intent": intent, "confidence": confidence, "reason": reason, "draft_answer": draft,
            "items": [dict(zip(("product_id", "size", "qty", "not_in_list", "unclear_text"), i)) for i in items],
            "learn": [dict(zip(("text", "kind", "product_id", "intent"), x)) for x in learn]}


@pytest.fixture
def ai(shop, db):  # noqa: F811
    """The shop + a fake AI provider (SHADOW mode, the default). Yields the fake."""
    y_shop(db)
    run_import(xlsx(GOOD_GIRL), {2: "new"})
    fake = FakeProvider()
    providers.use(fake)
    service._not_needed.clear()  # ids restart in every test
    yield fake
    providers.use(None)


def mode(value: str, **extra) -> None:
    with SessionLocal.begin() as s:
        ai_settings.save(s, {"mode": value, **extra}, None)


def calls(db) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text("SELECT message_id, decision, ok, error FROM ai_calls ORDER BY id")))


def worker_step() -> None:
    """What the parser worker does after parsing: the AI step, then auto mode."""
    service.run_once()
    auto.run_once()


def ysl_answer(db, confidence=0.95) -> dict:
    y = pid(db, "Y Eau de Parfum")
    return answer("buy", [(y, "10ml", 1, None, None)], [("ysl edp", "nickname", y, None)], confidence,
                  "ysl edp = Y EDP; 10ml; ယူပါမယ် = buy")


# ---------- F1 checker ----------

def catalog(db) -> prompt.Catalog:
    with SessionLocal() as s:
        return prompt.load_catalog(s)


def test_f1_checker_rejects_bad_answers(ai, shop, db):
    cat, y, sauvage = catalog(db), pid(db, "Y Eau de Parfum"), pid(db, "Sauvage Eau de Parfum")
    msg = privacy.mask(YSL)

    def problems(data: dict) -> list[str]:
        result, found = checker.parse(data)
        return found if result is None else checker.check(result, cat, msg)

    assert problems(ysl_answer(db)) == []
    assert "unknown or inactive product id 999" in problems(answer(items=[(999, "5ml", 1, None, None)]))[0]
    assert "size 2ml not sold" in problems(answer(items=[(sauvage, "2ml", 1, None, None)]))[0]  # no 2ml price
    assert problems(answer(items=[(y, "5ml", 1, "ysl edp", None)])) == ["item 1: not_in_list with a product id"]
    assert problems(answer(items=[(y, "5ml", 0, None, None)])) == ["item 1: quantity 0 outside 1-20"]
    assert problems(answer(items=[(y, "5ml", 21, None, None)])) == ["item 1: quantity 21 outside 1-20"]
    assert problems(answer(learn=[("yves saint", "nickname", y, None)])) == ["learn 1: text not in the message"]
    assert problems(answer(learn=[("ysl edp", "nickname", None, None)])) == ["learn 1: nickname without a known product"]
    assert problems(answer(learn=[("ရောယူပါမယ်", "intent_phrase", None, "question")])) == \
        ["learn 1: phrase without a learnable intent"]
    assert problems({"intent": "buy"})[0].startswith("invalid JSON")
    assert problems(answer(confidence=1.5)) == ["confidence outside 0-1"]


@pytest.mark.parametrize("bad", [
    "unknown product", "size not sold", "not_in_list with id", "learn text", "invalid JSON"])
def test_f1_rejected_answer_goes_to_needs_you(ai, shop, db, bad):
    client, _ = shop
    y, sauvage = pid(db, "Y Eau de Parfum"), pid(db, "Sauvage Eau de Parfum")
    ai.answer = {
        "unknown product": answer(items=[(999, "10ml", 1, None, None)]),
        "size not sold": answer(items=[(sauvage, "2ml", 1, None, None)]),
        "not_in_list with id": answer(items=[(y, "10ml", 1, "ysl edp", None)]),
        "learn text": answer(items=[(y, "10ml", 1, None, None)], learn=[("ysl eau de parfum", "nickname", y, None)]),
        "invalid JSON": "{not json",
    }[bad]
    mode("auto")
    auto_on(db)
    mid = say(db, 1, YSL)
    worker_step()
    [(message_id, decision, ok, error)] = calls(db)
    assert (message_id, decision, ok) == (mid, "rejected", False) and error
    assert outbox(db) == []  # nothing sent
    page = card_page(client, mid)
    assert "“ysl edp” ဆိုတာ ဘယ်ပစ္စည်းလဲ?" in page and "AI suggests" not in page  # the rules' card, no 🧠
    assert "📘 သင်ပေးမယ်" in client.get("/").text  # Needs you
    assert scalar(db, "SELECT method FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "rules"


# ---------- F2 privacy ----------

def test_f2_mask_unit():
    m = privacy.mask
    assert m("ဖုန်း ၀၉၇၇၇၁၂၃၄၅၆ ပါ") == "ဖုန်း [PHONE] ပါ"
    assert m("+95 9 777 123 456") == "[PHONE]"
    assert "[ADDRESS]" in m("ရန်ကင်း သုခလမ်း အမှတ်၁၂") and "သုခ" not in m("ရန်ကင်း သုခလမ်း အမှတ်၁၂") \
        and "12" not in m("ရန်ကင်း သုခလမ်း အမှတ်၁၂")
    assert m("No. 45, Pyay Road, Kamayut") == "[ADDRESS], [ADDRESS], kamayut"
    assert m("kpay transaction 0123456789012345") == "kpay transaction [NUMBER]"
    assert m("good girl 5ml ၂ခု 18000") == "good girl 5ml 2ခု 18000"  # sizes, quantities, prices stay


def test_f2_request_is_masked(ai, shop, db):
    add(990, "KPay 09000000001 · ငွေလွှဲ id 9988776655443322", direction="out", customer="91",
        when=START - timedelta(minutes=30))
    ai.answer = answer("buy", [(None, "10ml", 1, "hawas for him", None)], confidence=0.95)
    say(db, 1, "hawas for him 10ml ယူမယ် ဖုန်း 09777123456 ရန်ကင်း သုခလမ်း အမှတ်၁၂")
    service.run_once()
    [(instructions, user_input)] = ai.requests
    sent = instructions + user_input
    for secret in ("09777123456", "777123456", "သုခ", "အမှတ်12", "09000000001", "9988776655443322", "User 91"):
        assert secret not in sent, secret
    assert "[PHONE]" in user_input and "[ADDRESS]" in user_input and "[NUMBER]" in user_input
    assert "hawas for him 10ml" in user_input
    # static part first (same for every message, so it is cached), the message last
    assert instructions.startswith("You help a small perfume DECANT shop") and "Y Eau de Parfum" in instructions
    assert user_input.rstrip().endswith(">>>")


def test_f2_photos_and_payment_replies_never_sent(ai, shop, db):
    add(980, "", kind="photo", customer="91", when=START - timedelta(minutes=30))
    with SessionLocal.begin() as s:  # a payment-info reply in the chat history
        s.execute(text("INSERT INTO outbox (customer_id, text, reply_kind, status, idempotency_key) "
                       "SELECT id, 'x', 'payment_info', 'sent', 'k1' FROM customers WHERE external_user_id = '91'"))
    add(981, "KPay - Daw Aye 123 · total 34,000", direction="out", customer="91",
        when=START - timedelta(minutes=20))
    with db.begin() as c:
        c.execute(text("UPDATE outbox SET sent_message_id = (SELECT id FROM messages WHERE external_message_id = '981')"))
    ai.answer = answer("other")
    say(db, 1, "ကျေးဇူးပါ")
    service.run_once()
    user_input = ai.requests[0][1]
    assert "C: [photo]" in user_input and "S: [contact / payment details]" in user_input
    assert "Daw Aye" not in user_input


# ---------- F3 cap / budget ----------

def test_f3_daily_cap_then_next_day(ai, shop, db):
    client, _ = shop
    mode("shadow", daily_cap=1)
    ai.answer = answer("buy", [(None, "10ml", 1, "hawas for him", None)])
    first = say(db, 1, HAWAS)
    second = say(db, 2, "liquid brun 10ml ယူမယ်", customer="92")
    service.run_once()
    assert len(ai.requests) == 1
    assert [(m, d) for m, d, _, _ in calls(db)] == [(first, "shadow"), (second, "cap")]
    page = client.get("/").text
    assert "daily limit of 1 calls reached" in page and "📘 သင်ပေးမယ်" in page  # still in Needs you
    # next day (Yangon time): the counter starts again
    with db.begin() as c:
        c.execute(text("UPDATE ai_calls SET created_at = created_at - interval '1 day'"))
    assert "daily limit" not in client.get("/").text
    third = say(db, 3, "eros flame 10ml ယူမယ်", customer="93")
    service.run_once()
    assert len(ai.requests) == 2 and calls(db)[-1][:2] == (third, "shadow")


def test_f3_monthly_budget(ai, shop, db):
    client, _ = shop
    mode("shadow", monthly_budget_usd=0.0)
    ai.answer = answer("other")
    say(db, 1, "ကျေးဇူးပါ")
    service.run_once()
    assert ai.requests == [] and calls(db)[0][1] == "budget"
    assert "monthly budget of $0.00 used up" in client.get("/").text


# ---------- F4 errors ----------

@pytest.mark.parametrize("kind,notice", [
    ("timeout", None), ("network", None), ("auth", "the API key was refused"),
    ("rate_limit", None), ("quota", "no credit left: add credit in OpenAI Billing")])
def test_f4_errors_never_crash(ai, shop, db, kind, notice):
    client, _ = shop
    mode("auto")
    auto_on(db)
    ai.answer = AIError(kind)
    mid = say(db, 1, YSL)
    worker_step()
    assert calls(db) == [(mid, "error", False, kind)]
    assert outbox(db) == []
    page = client.get("/").text
    assert "📘 သင်ပေးမယ်" in page
    if notice:
        assert notice in page
    # the auto engine did not wait forever: the rules' result was decided (not automatic: fuzzy)
    assert scalar(db, "SELECT reason FROM auto_runs WHERE message_id = :m", m=mid) == "product not named exactly"


def test_f4_many_errors_notice(ai, shop, db):
    client, _ = shop
    ai.answer = AIError("server")
    for n, customer in enumerate(("91", "92", "93", "94", "95"), start=1):
        say(db, n, HAWAS, customer=customer)
    service.run_once()
    assert "5 of the last 5 calls failed" in client.get("/").text


def _status_error(cls, status: int, code: str):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
    return cls("error", response=response, body={"error": {"code": code, "type": code}})


def test_f4_openai_errors_are_classified(monkeypatch):
    provider = providers.OpenAIProvider("sk-test-not-a-key", 8)
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    attempts = []

    def run(exc) -> str:
        attempts.clear()

        def create(**kwargs):
            attempts.append(kwargs)
            raise exc

        monkeypatch.setattr(provider._client.responses, "create", create)
        with pytest.raises(AIError) as info:
            provider.understand("i", {}, "u", "gpt-6-luna", "low")
        return info.value.kind

    assert run(openai.APITimeoutError(request=request)) == "timeout" and len(attempts) == 1
    assert run(openai.APIConnectionError(request=request)) == "network" and len(attempts) == 2  # 1 retry
    assert run(_status_error(openai.AuthenticationError, 401, "invalid_api_key")) == "auth"
    assert run(_status_error(openai.RateLimitError, 429, "insufficient_quota")) == "quota"
    assert run(_status_error(openai.RateLimitError, 429, "rate_limit_exceeded")) == "rate_limit"
    assert run(_status_error(openai.PermissionDeniedError, 403, "unsupported_country_region_territory")) == "country"
    assert len(attempts) == 1
    kwargs = run(openai.APITimeoutError(request=request)) and attempts[0]
    assert kwargs["store"] is False and kwargs["text"]["format"]["strict"] is True  # never stored at OpenAI


# ---------- F5 SHADOW ----------

def test_f5_shadow_card_prefilled_then_accepted(ai, shop, db):
    client, token = shop
    ai.answer = ysl_answer(db)
    mid = say(db, 1, YSL)
    service.run_once()
    assert calls(db) == [(mid, "shadow", True, None)]
    page = card_page(client, mid)
    y = pid(db, "Y Eau de Parfum")
    assert "🧠 <b>AI suggests</b> · ysl edp = Y EDP; 10ml; ယူပါမယ် = buy" in html.unescape(page)
    assert f'name="p0" value="{y}" checked' in page and 'name="nick0" value="ysl edp"' in page
    shown = preview(client, token, mid, p0=str(y), nick0="ysl edp", ai_call=str(calls_id(db)),
                    ai_hint=hint_json(page))
    assert "Y Eau de Parfum 10ml ကို ခြင်းထဲထည့်ပြီး စာရင်းပို့မယ်။" in shown
    confirm(client, token, shown)
    assert deliver(db) == ["မင်္ဂလာပါ။\n" + Y_LIST]
    assert learned(db) == [("nickname", "ysl edp", "pending", "Y Eau de Parfum", 0, 0)]
    assert scalar(db, "SELECT via_ai FROM learned_patterns") is True
    assert calls(db)[0][1] == "accepted"
    assert "🧠 AI + owner" in client.get("/learning").text  # taught by "AI + <user>"


def calls_id(db) -> int:
    return scalar(db, "SELECT id FROM ai_calls ORDER BY id DESC LIMIT 1")


def hint_json(page: str) -> str:
    return html.unescape(re.search(r'name="ai_hint" value="([^"]*)"', page).group(1))


def test_f5b_shadow_corrected_and_ai_product_added_to_options(ai, shop, db):
    client, token = shop
    sauvage, gg = pid(db, "Sauvage Eau de Parfum"), pid(db, "Good Girl")
    ai.answer = answer("buy", [(sauvage, "10ml", 1, None, None)], confidence=0.8, reason="mystery = sauvage?")
    mid = say(db, 1, "mystery scent 10ml ယူမယ်")
    service.run_once()
    page = card_page(client, mid)
    assert f'name="p0" value="{sauvage}" checked' in page  # the AI's product, even if the rules didn't list it
    shown = preview(client, token, mid, p0=str(gg), nick0="mystery scent", ai_call=str(calls_id(db)),
                    ai_hint=hint_json(page))
    confirm(client, token, shown)
    assert items(db) == [("Good Girl", 10, False, 1, 28000)]
    assert calls(db)[0][1] == "corrected"


# ---------- F6 AUTO ----------

def test_f6_auto_confident_acts_by_itself(ai, shop, db):
    client, _ = shop
    mode("auto")
    auto_on(db)
    ai.answer = ysl_answer(db, confidence=0.93)
    mid = say(db, 1, YSL)
    auto.run_once()  # before the AI step: auto mode waits for the AI
    assert scalar(db, "SELECT count(*) FROM auto_runs") == 0
    worker_step()
    assert deliver(db) == ["မင်္ဂလာပါ။\n" + Y_LIST]
    assert calls(db)[0][1] == "auto"
    assert scalar(db, "SELECT method FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "ai"
    assert learned(db) == [("nickname", "ysl edp", "pending", "Y Eau de Parfum", 0, 0)]  # pending, not approved
    assert scalar(db, "SELECT via_ai AND taught_by IS NULL FROM learned_patterns") is True
    chat = client.get(f"/chats/{scalar(db, 'SELECT customer_id FROM messages WHERE id = :m', m=mid)}").text
    assert 'class="ai-mark" title="ysl edp = Y EDP; 10ml; ယူပါမယ် = buy (auto)">🧠' in html.unescape(chat)
    assert reparse_all()["ai"] == 1  # re-parsing keeps the AI's result
    assert scalar(db, "SELECT method FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "ai"


def test_f6_auto_low_confidence_is_shadow(ai, shop, db):
    client, _ = shop
    mode("auto")
    auto_on(db)
    ai.answer = ysl_answer(db, confidence=0.6)
    mid = say(db, 1, YSL)
    worker_step()
    assert outbox(db) == [] and calls(db)[0][1] == "shadow"
    assert scalar(db, "SELECT method FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "rules"
    page = card_page(client, mid)
    assert "AI suggests" in page and f'name="p0" value="{pid(db, "Y Eau de Parfum")}" checked' in page
    assert learned(db) == []  # SHADOW: patterns only when a person confirms the card


def test_f6_auto_off_switch_keeps_ai_results_from_acting(ai, shop, db):
    mode("shadow")
    auto_on(db)
    ai.answer = ysl_answer(db, confidence=0.99)
    say(db, 1, YSL)
    worker_step()
    assert outbox(db) == [] and calls(db)[0][1] == "shadow"  # SHADOW never acts, however sure


# ---------- F7 not in our list ----------

def test_f7_not_in_list_auto_reply(ai, shop, db):
    mode("auto")
    auto_on(db)
    ai.answer = answer("buy", [(None, "10ml", 1, "hawas for him", None)], [("hawas for him", "not_stocked", None, None)],
                       0.95, "hawas for him is not Hawas Ice")
    say(db, 1, HAWAS)
    worker_step()
    assert deliver(db) == ["မင်္ဂလာပါ။\nhawas for him ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။"]
    assert learned(db) == [("not_stocked", "hawas for him", "pending", None, 0, 0)]
    assert scalar(db, "SELECT resolution FROM unknown_requests") == "not_stocked"  # Wanted report


def test_f7_not_in_list_shadow_preselects_not_stocked(ai, shop, db):
    client, token = shop
    ai.answer = answer("buy", [(None, "10ml", 1, "hawas for him", None)], [("hawas for him", "not_stocked", None, None)],
                       0.95)
    mid = say(db, 1, HAWAS)
    service.run_once()
    page = card_page(client, mid)
    assert 'value="not_stocked" checked' in page
    shown = preview(client, token, mid, p0="not_stocked", nick0="hawas for him", ai_call=str(calls_id(db)),
                    ai_hint=hint_json(page))
    assert "မရှိဘူးလို့ ပြန်ပြောမယ်။" in shown
    confirm(client, token, shown)
    assert deliver(db) == ["မင်္ဂလာပါ။\nhawas for him ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။"]
    assert calls(db)[0][1] == "accepted"


def test_f7_not_in_list_unsure_not_preselected(ai, shop, db):
    client, _ = shop
    ai.answer = answer("buy", [(None, "10ml", 1, "hawas for him", None)], confidence=0.7)
    mid = say(db, 1, HAWAS)
    service.run_once()
    assert 'value="not_stocked" checked' not in card_page(client, mid)


# ---------- F8 questions ----------

def test_f8_question_never_automatic_admin_sends_draft(ai, shop, db):
    client, token = shop
    mode("auto")
    auto_on(db)
    ai.answer = answer("question", confidence=0.97, reason="asks about the scent", draft=DRAFT)
    mid = say(db, 1, QUESTION)
    worker_step()
    assert outbox(db) == []  # never sent automatically, in any mode
    page = card_page(client, mid)
    assert 'name="intent" value="question" checked' in page
    assert f'<textarea name="draft" rows="3" maxlength="1000">{DRAFT}</textarea>' in page
    assert "📘 သင်ပေးမယ်" in client.get("/").text  # shown in Needs you at once (the AI knows what it is)
    edited = DRAFT + " ညနေဘက်အတွက် Sauvage ကိုလည်း ကြည့်ပါဦး။"
    shown = preview(client, token, mid, intent="question", draft=edited, ai_call=str(calls_id(db)),
                    ai_hint=hint_json(page), learn=None)
    assert "ဒီအဖြေကို ဖောက်သည်ဆီ ပို့မယ်။" in shown and html.escape(edited) in shown
    confirm(client, token, shown)
    assert deliver(db) == [edited]
    assert calls(db)[0][1] == "corrected"  # the draft was edited
    assert "📘 သင်ပေးမယ်" not in card_page(client, mid)


def test_f8_question_draft_unchanged_is_accepted(ai, shop, db):
    client, token = shop
    ai.answer = answer("question", confidence=0.97, draft=DRAFT)
    mid = say(db, 1, QUESTION)
    service.run_once()
    page = card_page(client, mid)
    confirm(client, token, preview(client, token, mid, intent="question", draft=DRAFT, ai_call=str(calls_id(db)),
                                   ai_hint=hint_json(page), learn=None))
    assert deliver(db) == [DRAFT] and calls(db)[0][1] == "accepted"


# ---------- F9 / F10 no call when the rules are sure ----------

def test_f9_rules_certain_never_calls_ai(ai, shop, db):
    mode("auto")
    auto_on(db)
    ai.answer = answer("other")
    for n, body in enumerate(("stw intensely 5ml ယူမယ်", "good girl 10ml ဘယ်လောက်လဲ", "မင်္ဂလာပါ", "ok",
                              "ရန်ကင်း ကိုပို့ပေးပါ 09777123456"), start=1):
        say(db, n, body)
        worker_step()
    assert ai.requests == [] and calls(db) == []


def test_f10_approved_pattern_no_ai_call(ai, shop, db):
    with SessionLocal.begin() as s:
        assert patterns.teach(s, "nickname", "ysl edp", None, product_id=pid(db, "Y Eau de Parfum"),
                              approved=True).status == "saved"
    mode("auto")
    auto_on(db)
    say(db, 1, "ysl edp 5ml ယူမယ်")
    worker_step()
    assert ai.requests == [] and calls(db) == []
    assert deliver(db)[0].startswith("မင်္ဂလာပါ။\n• Y Eau de Parfum 5ml – 18,000 ကျပ်")


def test_ai_off_never_calls(ai, shop, db):
    mode("off")
    say(db, 1, YSL)
    worker_step()
    assert ai.requests == [] and calls(db) == []


# ---------- F11 cost ----------

def test_f11_cost_from_usage_and_prices(ai, shop, db):
    client, _ = shop
    ai.input_tokens, ai.cached_tokens, ai.output_tokens = 2000, 1500, 120
    ai.answer = ysl_answer(db)
    say(db, 1, YSL)
    service.run_once()
    # 500 new input x $0.10 + 1500 cached x $0.01 + 120 output x $0.50, per 1M tokens
    assert float(scalar(db, "SELECT cost_usd FROM ai_calls")) == pytest.approx(0.000125)
    assert scalar(db, "SELECT input_tokens || '/' || cached_tokens || '/' || output_tokens FROM ai_calls") == \
        "2000/1500/120"
    assert providers.cost_usd(1_000_000, 0, 0) == pytest.approx(0.10)
    assert providers.cost_usd(1_000_000, 1_000_000, 1_000_000) == pytest.approx(0.51)
    page = client.get("/ai").text
    assert "$0.0001" in page and "<th>AI calls</th><td>1</td><td>1</td>" in page


# ---------- AI page ----------

def test_ai_page_mode_settings_and_owner_only(ai, shop, db):
    client, token = shop
    ai.answer = ysl_answer(db)
    say(db, 1, YSL)
    service.run_once()
    page = client.get("/ai").text
    assert "SHADOW: suggests on teaching cards" in page and "Last 50 AI calls" in page
    assert "buy 0.95: Y Eau de Parfum 10ml" in page
    client.post("/ai/mode", data={"csrf": token, "mode": "auto"})
    with SessionLocal() as s:
        assert ai_settings.mode(s) == "auto"
    r = client.post("/ai/settings", data={"csrf": token, "daily_cap": "50", "monthly_budget_usd": "2.5",
                                          "threshold": "0.9", "model": "gpt-6-luna", "reasoning": "medium"},
                    follow_redirects=True)
    assert "Saved." in r.text
    with SessionLocal() as s:
        cfg = ai_settings.load(s)
    assert (cfg["daily_cap"], cfg["monthly_budget_usd"], cfg["threshold"], cfg["reasoning"]) == (50, 2.5, 0.9, "medium")
    r = client.post("/ai/settings", data={"csrf": token, "daily_cap": "50", "monthly_budget_usd": "2.5",
                                          "threshold": "0.2", "model": "gpt-6-luna", "reasoning": "low"},
                    follow_redirects=True)
    assert "Not saved: threshold must be 0.5-1.0." in r.text
    assert scalar(db, "SELECT count(*) FROM audit_log WHERE action LIKE 'ai.%'") == 2
    # staff can't open it
    from tests.test_v4_i18n import burmese_client

    staff, _ = burmese_client(db, "staffai", "staff")
    assert staff.get("/ai").status_code == 403


def test_run_evaluation_button(ai, shop, db, monkeypatch, tmp_path):
    client, token = shop
    from app.ai import report
    from app.web import ai as ai_page

    started = []
    monkeypatch.setattr(report, "EXPORTS", tmp_path)
    monkeypatch.setattr(report, "EVAL_RUNNING", tmp_path / "running")
    monkeypatch.setattr(report, "EVAL_LOG", tmp_path / "log")
    monkeypatch.setattr(ai_page.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    r = client.post("/ai/evaluate", data={"csrf": token}, follow_redirects=True)
    assert "Evaluation started" in r.text and "Running…" in r.text
    assert len(started) == 1 and "-m scripts.ai_eval" in started[0][-1]
    r = client.post("/ai/evaluate", data={"csrf": token}, follow_redirects=True)
    assert "already running" in r.text and len(started) == 1  # never twice at once


def test_eval_scoring_is_strict():
    from app.ai.service import Understood
    from scripts.ai_eval import score

    ids = {"good girl": 10, "y eau de parfum": 3}
    row = {"expect_intent": "buy", "expect_items": "Good Girl@5ml;!liquid brun@10ml", "allowed": ""}

    def got(*items) -> Understood:
        return Understood(AIResult.from_json(answer("buy", items)))

    s = score(row, got((10, "5ml", 1, None, None), (None, "10ml", 1, "liquid brun", None)), ids)
    assert s.intent and s.products and not s.wrong_product
    s = score(row, got((10, "5ml", 1, None, None), (3, "10ml", 1, None, None)), ids)  # not-in-list mapped
    assert not s.products and s.wrong_product and s.nil_mapped
    s = score(row, got((10, "5ml", 1, None, None), (None, "10ml", 1, None, "liquid brun")), ids)  # unclear, not nil
    assert not s.products and not s.wrong_product
    unclear = {"expect_intent": "buy", "expect_items": "?ysl@5ml", "allowed": ""}
    assert score(unclear, got((3, "5ml", 1, None, None)), ids).wrong_product
    any_size = {"expect_intent": "remove", "expect_items": "Y Eau de Parfum@any", "allowed": ""}
    assert score(any_size, got((3, "5ml", 1, None, None)), ids).sizes
