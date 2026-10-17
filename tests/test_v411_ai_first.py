"""docs/SPEC-v4.11-ai-first.md acceptance tests M1-M8 (fake AI provider, AUTO mode): several actions in one
message, the customer chooses, the simple admin card, automatic learning, the brake, "form expired",
and the Older section. Customer messages in -> exact replies out -> DB state checked."""
import html
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.ai import service
from app.ai import settings as ai_settings
from app.ai.providers import AIError
from app.core.db import SessionLocal
from app.learning import patterns
from app.orders import auto, cart
from app.parser.worker import run_batch
from scripts.ai_auto_now import switch
from tests.test_cart import PAYMENT_FOOTER, deliver, shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_payments import photo, waiting_for_payment
from tests.test_prices import run_import, xlsx
from tests.test_v46_ai import YSL, Y_LIST, ai, calls, mode, ysl_answer  # noqa: F401  (fixture)
from tests.test_v4_teaching import auto_on, learned, pid
from tests.test_web import client, log_in  # noqa: F401  (fixture)

LIBRE = ["Yves Saint Laurent", "Libre", 90, 360000, 8000, 17000, 32000, "yes"]
LIVE = "Y edp မယူတော့ဘူး ဗျ liquid brun 10 ml ယူပါမယ်"
NOT_STOCKED = "liquid brun ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။"
CART_EMPTY = "ခြင်းထဲမှာ ဘာမှ မကျန်တော့ပါဘူး။ တခြား ဘာယူချင်လဲ။"
ASK_PHONE = "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"
_n = {"next": 0}


def full(intent="buy", items=(), learn=(), confidence=0.95, reason="test reason", draft=None) -> dict:
    """An AI answer with the v4.11 fields. items: (product_id, size, qty, not_in_list, unclear_text, action,
    candidates); learn: (text, kind, product_id, intent)."""
    keys = ("product_id", "size", "qty", "not_in_list", "unclear_text", "action", "candidates")
    return {"intent": intent, "confidence": confidence, "reason": reason, "draft_answer": draft,
            "items": [dict(zip(keys, (*i, *(None, [])[len(i) - 5:]))) for i in items],
            "learn": [dict(zip(("text", "kind", "product_id", "intent"), x)) for x in learn]}


@pytest.fixture
def auto_ai(ai, db):  # noqa: F811
    """AUTO AI mode + auto-reply ON (the 4.11 deploy state)."""
    _n["next"] = 0
    with SessionLocal.begin() as s:
        switch(s)
    auto_on(db)
    return ai


def now_msg(db, body: str, customer: str = "91", seconds: float = 0) -> int:
    """A customer message right now (after everything before it), then the worker: parse, AI, auto."""
    _n["next"] += 1
    ext = 7100 + _n["next"]
    when = datetime.now(UTC) + timedelta(seconds=seconds, milliseconds=_n["next"])
    add(ext, body, customer=customer, when=when)
    run_batch()
    service.run_once(when + timedelta(seconds=5))
    auto.run_once(when + timedelta(seconds=5))
    return scalar(db, "SELECT id FROM messages WHERE external_message_id = :e", e=str(ext))


def ungreet(text_: str) -> str:
    return text_.removeprefix("မင်္ဂလာပါ။\n")


def cart_with(client, token, db, customer: str, product: str, size: str) -> int:
    """A cart made from the chat (no message sent to the customer)."""
    add(7000 + int(customer), "hi", customer=customer, when=datetime.now(UTC) - timedelta(hours=4))  # before auto ON
    cid = customer_id(db, customer)
    client.post(f"/chats/{cid}/cart/add", data={"csrf": token, "product_id": str(pid(db, product)), "size": size})
    return cid


def open_items(db, customer="91") -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text(
            "SELECT p.name, i.size_ml FROM order_items i JOIN orders o ON o.id = i.order_id JOIN customers c "
            "ON c.id = o.customer_id LEFT JOIN products p ON p.id = i.product_id WHERE c.external_user_id = :e "
            "AND i.removed_at IS NULL AND o.status IN ('cart', 'confirmed', 'waiting_payment', 'photo_received') "
            "ORDER BY i.id"), {"e": customer}))


def card_form(page: str, mid: int) -> dict[str, str]:
    """What the browser sends when ✅ is pressed on the card: hidden fields + checked radios + the draft."""
    form = re.search(rf'<form [^>]*id="card-{mid}">(.*?)</form>', page, re.S).group(1)
    fields = {html.unescape(k): html.unescape(v) for k, v in
              re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', form)}
    for k, v in re.findall(r'<input type="radio" name="([^"]+)" value="([^"]*)" checked>', form):
        fields[html.unescape(k)] = html.unescape(v)
    if m := re.search(r'<textarea name="draft"[^>]*>(.*?)</textarea>', form, re.S):
        fields["draft"] = html.unescape(m.group(1))
    return fields


# ---------- L1 ----------

def test_l1_switch_to_auto_now_keeps_the_brake(ai, shop, db):  # noqa: F811
    client, _ = shop
    with SessionLocal.begin() as s:
        assert switch(s) is True
        assert switch(s) is False  # safe to run again
        cfg = ai_settings.load(s)
    assert (cfg["mode"], cfg["auto_graduate"], cfg["skipped_shadow"]) == ("auto", False, True)
    page = html.unescape(client.get("/ai").text)
    assert "AUTO since" in page and "(owner skipped shadow); safety brake ON" in page


# ---------- M1 the live case ----------

def test_m1_live_case_remove_and_not_stocked_one_reply(auto_ai, shop, db):
    client, token = shop
    y = pid(db, "Y Eau de Parfum")
    cart_with(client, token, db, "91", "Y Eau de Parfum", "10")
    auto_ai.answer = full("modify_cart", [(y, None, 1, None, None, "remove"),
                                          (None, "10ml", 1, "liquid brun", None, "add")],
                          [("liquid brun", "not_stocked", None, None)], 0.95, "remove Y EDP; liquid brun not sold")
    mid = now_msg(db, LIVE)
    [reply] = deliver(db)
    assert ungreet(reply) == f"Y Eau de Parfum ကို ဖြုတ်လိုက်ပါပြီ။\n{NOT_STOCKED}\n{CART_EMPTY}"
    assert open_items(db) == []  # cart empty
    assert calls(db)[0][:2] == (mid, "auto")
    assert scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "modify_cart"
    assert scalar(db, "SELECT kind FROM quick_actions WHERE message_id = :m", m=mid) == "cart_change"
    assert scalar(db, "SELECT resolution FROM unknown_requests WHERE message_id = :m", m=mid) == "not_stocked"


def test_m1_remove_only_for_cart_items(auto_ai, shop, db):
    """The checker drops a remove of a product that is not in the cart and lowers the confidence:
    nothing automatic, the admin decides."""
    client, token = shop
    y, sauvage = pid(db, "Y Eau de Parfum"), pid(db, "Sauvage Eau de Parfum")
    cart_with(client, token, db, "91", "Y Eau de Parfum", "10")
    auto_ai.answer = full("modify_cart", [(sauvage, None, 1, None, None, "remove"),
                                          (y, "5ml", 1, None, None, "add")], (), 0.9)
    mid = now_msg(db, "sauvage မယူတော့ဘူး y 5ml ယူမယ်")
    assert deliver(db) == []
    assert calls(db)[0][:2] == (mid, "shadow")
    assert "remove of a product that is not in the cart" in calls(db)[0][3]
    assert open_items(db) == [("Y Eau de Parfum", 10)]


# ---------- M2 remove + add known in one message ----------

def test_m2_rules_remove_and_add_one_reply_no_ai(auto_ai, shop, db):
    client, token = shop
    cart_with(client, token, db, "91", "Stronger With You Intensely", "5")
    mid = now_msg(db, "stw intensely မယူတော့ဘူး ဗျ sauvage edp 10ml ယူမယ်")
    assert auto_ai.requests == []  # every clause certain: the rules handle it
    [reply] = deliver(db)
    assert ungreet(reply) == ("Stronger With You Intensely ကို ဖြုတ်လိုက်ပါပြီ။\n• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်\n"
                              f"စုစုပေါင်း 38,000 ကျပ်ပါ။\n{ASK_PHONE}")
    assert open_items(db) == [("Sauvage Eau de Parfum", 10)]
    assert scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "modify_cart"


def test_m2_waiting_for_payment_sends_payment_info_with_the_new_total(auto_ai, shop, db):
    client, token = shop
    waiting_for_payment(client, token, db)  # STW Intensely 5ml, 18,000, payment info sent
    now_msg(db, "stw intensely မယူတော့ဘူး sauvage edp 10ml ယူမယ်")
    [reply] = deliver(db)
    assert reply == ("Stronger With You Intensely ကို ဖြုတ်လိုက်ပါပြီ။\n• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်\n"
                     f"စုစုပေါင်း အသစ် 38,000 ကျပ်ပါ။\n{PAYMENT_FOOTER}")
    assert scalar(db, "SELECT status || ' ' || total_mmk FROM orders") == "waiting_payment 38000"


def test_m2_ai_remove_and_add_known(auto_ai, shop, db):
    client, token = shop
    y, sauvage = pid(db, "Y Eau de Parfum"), pid(db, "Sauvage Eau de Parfum")
    cart_with(client, token, db, "91", "Y Eau de Parfum", "10")
    auto_ai.answer = full("modify_cart", [(y, "10ml", 1, None, None, "remove"),
                                          (sauvage, "10ml", 1, None, None, "add")], (), 0.93)
    now_msg(db, "Y edp မယူတော့ဘူး ဗျ savage 10 ml ယူပါမယ်")
    [reply] = deliver(db)
    assert ungreet(reply) == ("Y Eau de Parfum 10ml ကို ဖြုတ်လိုက်ပါပြီ။\n• Sauvage Eau de Parfum 10ml – 38,000 ကျပ်\n"
                              f"စုစုပေါင်း 38,000 ကျပ်ပါ။\n{ASK_PHONE}")


# ---------- M3 ask the customer to choose ----------

def test_m3_customer_chooses_by_number(auto_ai, shop, db):
    run_import(xlsx(LIBRE), {2: "new"})
    y, libre = pid(db, "Y Eau de Parfum"), pid(db, "Libre")
    auto_ai.answer = full("buy", [(None, "10ml", 1, None, "ysl", None, [y, libre])], (), 0.9, "ysl = Y or Libre")
    now_msg(db, "ysl 10ml ယူမယ်")
    [reply] = deliver(db)
    assert ungreet(reply) == "ysl 10ml ထဲက ဘယ်ဟာလဲ –\n1. Y Eau de Parfum 10ml\n2. Libre 10ml\nနံပါတ်လေး ပြောပေးပါနော်။"
    assert scalar(db, "SELECT kind || ' ' || action FROM choice_prompts") == "product add"
    n = len(auto_ai.requests)
    now_msg(db, "၂", seconds=1)
    assert len(auto_ai.requests) == n  # the answer is understood without the AI
    [reply] = deliver(db)
    assert reply == f"• Libre 10ml – 32,000 ကျပ်\nစုစုပေါင်း 32,000 ကျပ်ပါ။\n{ASK_PHONE}"
    assert open_items(db) == [("Libre", 10)]


def test_m3_customer_chooses_by_name_and_price_question(auto_ai, shop, db):
    run_import(xlsx(LIBRE), {2: "new"})
    y, libre = pid(db, "Y Eau de Parfum"), pid(db, "Libre")
    auto_ai.answer = full("ask_price", [(None, "5ml", 1, None, "ysl", None, [y, libre])], (), 0.9)
    now_msg(db, "ysl 5ml ဘယ်လောက်လဲ")
    assert "1. Y Eau de Parfum 5ml\n2. Libre 5ml" in deliver(db)[0]
    now_msg(db, "libre ပါ", seconds=1)
    [reply] = deliver(db)
    assert reply.startswith("Libre 5ml က 17,000 ကျပ်ပါ။")
    assert open_items(db) == []  # a price question adds nothing


def test_m3_expired_prompt_is_not_a_choice(auto_ai, shop, db):
    run_import(xlsx(LIBRE), {2: "new"})
    y, libre = pid(db, "Y Eau de Parfum"), pid(db, "Libre")
    auto_ai.answer = full("buy", [(None, "10ml", 1, None, "ysl", None, [y, libre])], (), 0.9)
    now_msg(db, "ysl 10ml ယူမယ်")
    deliver(db)
    with db.begin() as c:  # sent 25 h ago
        c.execute(text("UPDATE choice_prompts SET created_at = created_at - interval '25 hours', "
                       "expires_at = expires_at - interval '25 hours'"))
    auto_ai.answer = full("other", (), (), 0.4)
    mid = now_msg(db, "2", seconds=1)
    assert scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "other"
    assert deliver(db) == [] and open_items(db) == []


def test_m3_more_than_three_candidates_goes_to_a_person(auto_ai, shop, db):
    run_import(xlsx(LIBRE), {2: "new"})
    ids = [pid(db, n) for n in ("Y Eau de Parfum", "Libre", "Sauvage Eau de Parfum", "Stronger With You Intensely")]
    auto_ai.answer = full("buy", [(None, "10ml", 1, None, "something", None, ids)], (), 0.9)
    mid = now_msg(db, "something 10ml ယူမယ်")
    assert deliver(db) == []
    assert calls(db)[0][:2] == (mid, "shadow")


# ---------- M4 the simple admin card ----------

@pytest.mark.parametrize("why", ["low confidence", "error", "cap"])
def test_m4_simple_card_preselected_and_send(auto_ai, shop, db, why):
    client, token = shop
    if why == "low confidence":
        auto_ai.answer = ysl_answer(db, confidence=0.6)
    elif why == "error":
        auto_ai.answer = AIError("timeout")
    else:
        mode("auto", daily_cap=0)
    mid = now_msg(db, YSL)
    assert deliver(db) == []
    page = client.get("/").text
    card = page[page.index(f'id="card-{mid}"'):]
    card = card[:card.index("</form>")]
    assert f'name="p0" value="{pid(db, "Y Eau de Parfum")}" checked' in card  # the answer is pre-selected
    assert "➕ Y Eau de Parfum 10ml" in card and html.escape(Y_LIST) in card.replace("&#39;", "'")  # reply preview
    assert "✅ ပို့မယ်" in card and "✏️ ပြင်မယ်" in card and "🙅 ဘာမှမလုပ်နဲ့" in card
    assert 'name="learn"' not in card and 'name="nick0"' not in card and "သင်ပေး" not in card  # no teaching
    assert ("🧠 <b>AI suggests</b>" in card) == (why == "low confidence")
    r = client.post(f"/messages/{mid}/teach", data={**card_form(page, mid), "csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    assert [ungreet(t) for t in deliver(db)] == [Y_LIST]  # exactly the previewed reply
    if why == "low confidence":
        assert calls(db)[0][1] == "accepted"


def test_m4_changed_answer_shows_the_new_reply_first(auto_ai, shop, db):
    client, token = shop
    auto_ai.answer = ysl_answer(db, confidence=0.6)
    mid = now_msg(db, YSL)
    page = client.get("/").text
    form = {**card_form(page, mid), "csrf": token, "p0": str(pid(db, "Sauvage Eau de Parfum"))}  # ✏️ changed
    r = client.post(f"/messages/{mid}/teach", data=form)
    assert r.status_code == 200 and "ပြင်လိုက်တဲ့အတွက် ပို့မယ့်စာ ပြောင်းသွားပါတယ်" in r.text  # nothing sent yet
    assert deliver(db) == [] and scalar(db, "SELECT count(*) FROM quick_actions") == 0


def test_m4_nothing_button(auto_ai, shop, db):
    client, token = shop
    auto_ai.answer = ysl_answer(db, confidence=0.6)
    mid = now_msg(db, YSL)
    form = {**card_form(client.get("/").text, mid), "csrf": token, "nothing": "1"}
    assert client.post(f"/messages/{mid}/teach", data=form, follow_redirects=False).status_code == 303
    assert deliver(db) == []
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=mid) == "done"


def test_m4_question_draft_in_editable_box_never_automatic(auto_ai, shop, db):
    client, token = shop
    auto_ai.answer = full("question", (), (), 0.95, "a question", "ညနေဘက်လည်း သုံးလို့ရပါတယ်ရှင့်။")
    mid = now_msg(db, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ ညနေဘက်သုံးလို့ရလား")
    assert deliver(db) == []  # never automatic
    page = client.get("/").text
    assert '<textarea name="draft"' in page
    form = card_form(page, mid)
    assert form["intent"] == "question" and form["draft"].startswith("ညနေဘက်လည်း")
    client.post(f"/messages/{mid}/teach", data={**form, "csrf": token}, follow_redirects=False)
    assert deliver(db) == ["ညနေဘက်လည်း သုံးလို့ရပါတယ်ရှင့်။"]


# ---------- M5 automatic learning ----------

def test_m5_three_same_readings_then_learned_no_ai_call(auto_ai, shop, db):
    auto_ai.answer = ysl_answer(db)
    for n, customer in enumerate(("71", "72", "73")):
        now_msg(db, YSL, customer=customer, seconds=n)
        assert len(deliver(db)) == 1
    assert learned(db) == [("nickname", "ysl edp", "approved", "Y Eau de Parfum", 3, 0)]
    assert scalar(db, "SELECT auto_learned FROM learned_patterns") is True
    assert scalar(db, "SELECT details->>'actor' FROM audit_log WHERE action = 'learning.auto_learned'") == "🧠 auto-learn"
    n = len(auto_ai.requests)
    mid = now_msg(db, YSL, customer="74", seconds=4)
    assert len(auto_ai.requests) == n  # the 4th: no AI call, the rules know it now
    assert scalar(db, "SELECT method FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "rules"
    assert [ungreet(t) for t in deliver(db)] == [Y_LIST]


def test_m5_correction_in_between_never_learned(auto_ai, shop, db):
    client, token = shop
    auto_ai.answer = ysl_answer(db)
    now_msg(db, YSL, customer="71")
    mid = now_msg(db, YSL, customer="72", seconds=1)
    deliver(db)
    client.post(f"/messages/{mid}/ai-wrong", data={"csrf": token, "p0": str(pid(db, "Y Eau de Parfum")), "size0": "5",
                                                    "qty0": "1", "intent": "buy"})  # size corrected: no brake
    for n, customer in enumerate(("73", "74")):
        now_msg(db, YSL, customer=customer, seconds=2 + n)
    status, uses, corrections = learned(db)[0][2], learned(db)[0][4], learned(db)[0][5]
    assert status == "pending" and corrections >= 1 and uses >= 3


def test_m5_whole_sentences_never_proposed(auto_ai, shop, db):
    with SessionLocal() as s:
        y = pid(db, "Y Eau de Parfum")
        assert patterns.reusable(s, "nickname", "ysl edp", YSL, y)
        assert not patterns.reusable(s, "nickname", "ysl edp 10 ml", YSL, y)  # a size
        assert not patterns.reusable(s, "nickname", "ysl edp ရောယူပါမယ်", YSL, y)  # an action word
        assert not patterns.reusable(s, "intent_phrase", "ဒီ နှစ်ခု ကို ထည့်ထား ပေး", "ဒီ နှစ်ခု ကို ထည့်ထား ပေး", None)
        assert not patterns.reusable(s, "intent_phrase", "နော်", "ok နော်", None)  # particles only
        assert patterns.reusable(s, "intent_phrase", "လေးထည့်ထားပေး", "stw intensely 5ml လေးထည့်ထားပေး", None)
    sentence = "ဒီဟာ လေး ထည့် ထားပေး ပါဦး"
    auto_ai.answer = full("buy", [(pid(db, "Y Eau de Parfum"), "10ml", 1, None, None)],
                          [(sentence, "intent_phrase", None, "buy")], 0.95)
    now_msg(db, f"y eau de parfum 10ml {sentence}")
    assert learned(db) == []


# ---------- M6 the brake in AUTO ----------

def test_m6_brake_still_works_in_auto(auto_ai, shop, db):
    client, token = shop
    auto_ai.answer = ysl_answer(db)
    mid = now_msg(db, YSL)
    deliver(db)
    assert calls(db)[0][1] == "auto"
    r = client.post(f"/messages/{mid}/ai-wrong", data={"csrf": token, "p0": str(pid(db, "Sauvage Eau de Parfum")),
                                                       "size0": "10", "qty0": "1", "intent": "buy"},
                    follow_redirects=True)
    assert "The AI is back in SHADOW" in r.text
    with SessionLocal() as s:
        assert ai_settings.mode(s) == "shadow"
    assert "🧠 AI switched back to SHADOW" in client.get("/").text


# ---------- M7 form expired ----------

def test_m7_form_expired_keeps_the_answers_and_does_nothing(auto_ai, shop, db):
    client, token = shop
    auto_ai.answer = ysl_answer(db, confidence=0.6)
    mid = now_msg(db, YSL)
    sauvage = str(pid(db, "Sauvage Eau de Parfum"))
    form = {**card_form(client.get("/").text, mid), "csrf": "old-token", "p0": sauvage}
    r = client.post(f"/messages/{mid}/teach", data=form, follow_redirects=False)
    assert r.status_code == 303
    target = r.headers["location"]
    assert target.startswith("/?restore=") and target.endswith(f"#card-{mid}")
    assert scalar(db, "SELECT count(*) FROM quick_actions") == 0 and scalar(db, "SELECT count(*) FROM outbox") == 0
    page = client.get(target).text
    assert "ဒီစာမျက်နှာ သက်တမ်းကုန်သွားလို့ ပြန်ဖွင့်ပေးထားပါတယ်။ ထပ်နှိပ်ပေးပါ။" in page
    card = page[page.index(f'id="card-{mid}"'):]
    assert f'name="p0" value="{sauvage}" checked' in card
    assert f'name="p0" value="{pid(db, "Y Eau de Parfum")}" checked' not in card[:card.index("</form>")]
    assert 'details class="card-edit" open' in card  # the changed answers are visible
    # htmx: reload the page
    r = client.post(f"/messages/{mid}/teach", data=form, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.headers.get("HX-Refresh") == "true"
    assert scalar(db, "SELECT count(*) FROM outbox") == 0
    # a missing token is still refused
    assert client.post(f"/messages/{mid}/teach", data={"p0": sauvage}).status_code == 403


# ---------- M8 Older ----------

def test_m8_older_section_dismiss_and_undo_payments_never_older(shop, db):
    client, token = shop
    old = datetime.now(UTC) - timedelta(hours=30)
    add(7201, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", customer="81", when=old)  # unanswered question, 30 h ago
    add(7202, "ကျေးဇူးပါ", customer="81", when=datetime.now(UTC) - timedelta(hours=1))  # wrote again since
    add(7203, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", customer="82", when=old)  # 30 h, but nothing since: stays current
    run_batch()
    with db.begin() as c:  # the later "thanks" was answered
        cid = c.execute(text("SELECT id FROM customers WHERE external_user_id = '81'")).scalar()
        mid = c.execute(text("SELECT id FROM messages WHERE external_message_id = '7202'")).scalar()
        c.execute(text("INSERT INTO message_reviews (message_id, status) VALUES (:m, 'done')"), {"m": mid})
    waiting_for_payment(client, token, db, customer="83")
    with db.begin() as c:
        c.execute(text("UPDATE orders SET payment_info_sent_at = now() - interval '41 hours'"))
    photo(1, customer="83", seconds_ago=40 * 3600)  # payment photo 40 h ago
    add(7204, "hello?", customer="83", when=datetime.now(UTC) - timedelta(minutes=30))
    run_batch()
    from app.web import auto as auto_pages

    with SessionLocal() as s:
        needs = auto_pages.needs_you(s)
        older_ids = needs["older_ids"]
        assert scalar(db, "SELECT id FROM messages WHERE external_message_id = '7201'") in older_ids
        assert scalar(db, "SELECT id FROM messages WHERE external_message_id = '7203'") not in older_ids
        assert len(needs["payments"]) == 1  # payments never move to Older
        current = needs["count"]
    page = client.get("/").text
    assert "Older (1)" in page and "Dismiss all older" in page
    assert f"Needs you ({current})" in html.unescape(page)  # the badge counts current items only
    form = {"csrf": token, "message_id": [str(i) for i in older_ids]}
    assert client.post("/needs-you/dismiss-older", data=form, follow_redirects=False).status_code == 303
    page = client.get("/").text
    assert "Older (" not in page and "Undo dismiss" in page
    m7201 = scalar(db, "SELECT id FROM messages WHERE external_message_id = '7201'")
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=m7201) == "done"
    dismiss = scalar(db, "SELECT max(id) FROM audit_log WHERE action = 'needs_you.dismiss_older'")
    client.post(f"/needs-you/dismiss-older/{dismiss}/undo", data={"csrf": token})
    assert scalar(db, "SELECT count(*) FROM message_reviews WHERE message_id = :m", m=m7201) == 0  # back
    assert "Older (1)" in client.get("/").text
    # after 60 s: too late
    client.post("/needs-you/dismiss-older", data=form)
    dismiss = scalar(db, "SELECT max(id) FROM audit_log WHERE action = 'needs_you.dismiss_older'")
    with db.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = now() - interval '2 minutes' WHERE id = :i"), {"i": dismiss})
    r = client.post(f"/needs-you/dismiss-older/{dismiss}/undo", data={"csrf": token}, follow_redirects=True)
    assert "Too late to undo." in r.text
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=m7201) == "done"


# ---------- M9 the evaluation (scoring only; the real API run is scripts/ai_eval.py) ----------

def test_m9_eval_scoring_actions_candidates_and_cart_removes():
    from app.ai.service import Understood
    from app.ai.types import AIResult
    from scripts.ai_eval import FIXTURE, score

    ids = {"y eau de parfum": 3, "libre": 28, "good girl": 10, "sauvage eau de parfum": 1}

    def got(intent, *items) -> Understood:
        return Understood(AIResult.from_json(full(intent, items)))

    live = {"expect_intent": "modify_cart", "expect_items": "Y Eau de Parfum@any>remove;!liquid brun@10ml>add",
            "allowed": "", "cart": "Y Eau de Parfum 10ml x1"}
    s = score(live, got("modify_cart", (3, "10ml", 1, None, None, "remove"),
                        (None, "10ml", 1, "liquid brun", None, "add")), ids)
    assert s.intent and s.products and not s.remove_not_in_cart
    s = score(live, got("modify_cart", (3, "10ml", 1, None, None, "add"),
                        (None, "10ml", 1, "liquid brun", None, "add")), ids)
    assert not s.products  # wrong action
    s = score({**live, "cart": "Good Girl 5ml x1"}, got("modify_cart", (3, "10ml", 1, None, None, "remove"),
                                                        (None, "10ml", 1, "liquid brun", None, "add")), ids)
    assert s.remove_not_in_cart
    choose = {"expect_intent": "buy", "expect_items": "?ysl@10ml{Y Eau de Parfum|Libre}", "allowed": "", "cart": ""}
    assert score(choose, got("buy", (None, "10ml", 1, None, "ysl", None, [3, 28])), ids).products
    assert not score(choose, got("buy", (None, "10ml", 1, None, "ysl", None, [3, 10])), ids).products
    assert not score(choose, got("buy", (None, "10ml", 1, None, "ysl", None, [])), ids).products
    assert score(choose, got("buy", (3, "10ml", 1, None, None)), ids).wrong_product
    import csv

    rows = list(csv.DictReader(FIXTURE.open(encoding="utf-8")))
    new = [r for r in rows if r["id"].startswith("m")]
    assert len(new) >= 10 and any(r["message"] == LIVE for r in new)  # incl. the live sentence
