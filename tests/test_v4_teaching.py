"""docs/SPEC-v4.md 4.2 acceptance tests B1-B8: teaching cards turn a message the app can't
handle into simple questions; the answers finish THIS customer's request and teach the app
(learned_patterns: pending -> one-tap "📘" -> approved -> automatic). Customer messages in ->
exact replies out (fake Telegram client), DB state checked."""
import html
import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models import User
from app.orders import auto, reports
from app.web.auth import hash_password
from tests.test_auto import switch_on
from tests.test_cart import button, deliver, items, say, shop, tap  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_prices import run_import, xlsx
from tests.test_web import PASSWORD, client, csrf, log_in  # noqa: F401  (fixture)

Y_IN_STOCK = ["Yves Saint Laurent", "Y Eau de Parfum", 100, 380000, 8000, 18000, 34000, "yes"]
GREETING = "မင်္ဂလာပါ။ ဘာကူညီပေးရမလဲ။"


def auto_on(db) -> None:
    switch_on(db, since=datetime.now(UTC) - timedelta(hours=3))


def card_page(client, mid: int) -> str:
    return client.get(f"/messages/{mid}").text


def preview(client, token, mid: int, **answers) -> str:
    data = {"csrf": token, "back": "/", "learn": "1", **answers}
    if data["learn"] is None:
        del data["learn"]
    r = client.post(f"/messages/{mid}/teach/preview", data=data)
    assert r.status_code == 200, r.text
    return r.text


def confirm(client, token, page: str) -> None:
    """Press ✅ on the preview page (sends exactly its hidden fields)."""
    form = page[page.index(f'action="/messages/'):]
    fields = [(html.unescape(k), html.unescape(v)) for k, v in
              re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', form)]
    mid = re.search(r'action="/messages/(\d+)/teach"', page).group(1)
    r = client.post(f"/messages/{mid}/teach", data={"csrf": token, **dict(fields)}, follow_redirects=False)
    assert r.status_code == 303, r.text


def teach(client, token, mid: int, **answers) -> str:
    page = preview(client, token, mid, **answers)
    confirm(client, token, page)
    return page


def learned(db) -> list[tuple]:
    with db.connect() as c:
        return list(c.execute(text(
            "SELECT l.kind, l.text, l.status, coalesce(p.name, l.intent), l.confirmed_uses, l.corrections "
            "FROM learned_patterns l LEFT JOIN products p ON p.id = l.product_id ORDER BY l.id")))


def pid(db, name: str) -> int:
    return scalar(db, "SELECT id FROM products WHERE name = :n", n=name)


def outbox(db) -> list[str]:
    with db.connect() as c:
        return list(c.execute(text("SELECT text FROM outbox WHERE status != 'cancelled' ORDER BY id")).scalars())


def y_shop(db) -> None:
    run_import(xlsx(Y_IN_STOCK))


def approve(client, token, pattern_text: str, db) -> None:
    p = scalar(db, "SELECT id FROM learned_patterns WHERE text = :t", t=pattern_text)
    r = client.post(f"/learning/{p}/decide", data={"csrf": token, "status": "approved"}, follow_redirects=False)
    assert r.status_code == 303


# ---------- B1 fuzzy name -> card -> item added + nickname learned ----------

def test_b1_fuzzy_name_card_teaches_nickname(shop, db):
    client, token = shop
    y_shop(db)
    auto_on(db)
    mid = say(db, 1, "ysl edp 10 ml ရောယူပါမယ်")
    auto.run_once()
    assert outbox(db) == []  # fuzzy: never automatic
    page = card_page(client, mid)
    assert "“ysl edp” ဆိုတာ ဘယ်ပစ္စည်းလဲ?" in page
    assert f'name="p0" value="{pid(db, "Y Eau de Parfum")}" checked' in page  # Y EDP first
    assert 'name="phrase"' not in page  # buy is known: no Q-intent
    assert 'name="nick0"' not in page and 'name="learn"' not in page  # 4.11 L5: no teaching box on the card
    assert "👀 စစ်ပြီး ဖြေမယ်" in client.get("/").text  # also in Needs you

    shown = preview(client, token, mid, p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp")
    assert "Y Eau de Parfum 10ml ကို ခြင်းထဲထည့်ပြီး စာရင်းပို့မယ်။" in shown
    assert "📘 “ysl edp” = Y Eau de Parfum" in shown
    assert scalar(db, "SELECT count(*) FROM learned_patterns") == 0  # the preview saved nothing
    confirm(client, token, shown)
    assert deliver(db) == ["မင်္ဂလာပါ။\n• Y Eau de Parfum 10ml – 34,000 ကျပ်\nစုစုပေါင်း 34,000 ကျပ်ပါ။\n"
                           "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"]
    assert items(db) == [("Y Eau de Parfum", 10, False, 1, 34000)]
    assert learned(db) == [("nickname", "ysl edp", "pending", "Y Eau de Parfum", 0, 0)]  # "ရောယူပါမယ်" = buy, known
    assert scalar(db, "SELECT method FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "human"
    assert "👀 စစ်ပြီး ဖြေမယ်" not in card_page(client, mid)  # answered


def test_b1b_new_intent_phrase_is_learned(shop, db):
    client, token = shop
    y_shop(db)
    mid = say(db, 1, "ysl edp 10ml လေးထည့်ထားပေး")
    page = card_page(client, mid)
    assert "ဖောက်သည်က ဘာလုပ်ချင်တာလဲ?" in page and 'name="phrase"' not in page  # 4.11 L5: no teaching box
    teach(client, token, mid, p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp", intent="buy",
          phrase="လေးထည့်ထားပေး")
    assert len(deliver(db)) == 1
    assert learned(db) == [("nickname", "ysl edp", "pending", "Y Eau de Parfum", 0, 0),
                           ("intent_phrase", "လေးထည့်ထားပေး", "pending", "buy", 0, 0)]
    # the phrase is understood next time (one-tap 📘 only while pending)
    other = say(db, 2, "stw intensely 5ml လေးထည့်ထားပေး", customer="92")
    assert scalar(db, "SELECT intent FROM parse_results WHERE message_id = :m AND is_current", m=other) == "buy"
    assert button(client, other)[0].startswith("📘 🛒")


# ---------- B2 pending -> one-tap 📘 -> 3 accepted uses -> approved -> auto ----------

def test_b2_three_accepted_uses_then_auto(shop, db):
    client, token = shop
    y_shop(db)
    auto_on(db)
    teach(client, token, say(db, 1, "ysl edp 10 ml ရောယူပါမယ်"), p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp")
    deliver(db)
    for n, customer in enumerate(("92", "93", "94"), start=2):
        mid = say(db, n, "ysl edp 5ml ယူမယ်", customer=customer)
        auto.run_once()
        assert deliver(db) == []  # not automatic while pending
        assert scalar(db, "SELECT reason FROM auto_runs WHERE message_id = :m", m=mid) == \
            "learned pattern waiting for approval"
        label, tooltip, _ = button(client, mid)
        assert label == "📘 🛒 Add to cart + send list" and "📘 learned (waiting approval): “ysl edp” = Y Eau de Parfum" in tooltip
        tap(client, token, mid)
        assert deliver(db)[0].startswith("မင်္ဂလာပါ။\n• Y Eau de Parfum 5ml – 18,000 ကျပ်")
        assert learned(db)[0][4] == n - 1  # confirmed_uses
    assert learned(db)[0][2] == "approved"  # 3 uses, no corrections (auto_approve_after = 3)
    mid = say(db, 5, "ysl edp 5ml ယူမယ်", customer="95")
    assert scalar(db, "SELECT i.match FROM parse_items i JOIN parse_results r ON r.id = i.parse_result_id "
                      "WHERE r.message_id = :m AND r.is_current", m=mid) == "learned"
    auto.run_once()
    assert deliver(db) == ["မင်္ဂလာပါ။\n• Y Eau de Parfum 5ml – 18,000 ကျပ်\nစုစုပေါင်း 18,000 ကျပ်ပါ။\n"
                           "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"]
    page = client.get("/learning").text
    assert "Handled by learned patterns this week</span><b>4</b>" in page  # 3 taps + 1 auto


def test_b2b_correction_blocks_auto_approval(shop, db):
    client, token = shop
    y_shop(db)
    teach(client, token, say(db, 1, "ysl edp 10 ml ရောယူပါမယ်"), p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp")
    deliver(db)
    wrong = say(db, 2, "ysl edp 5ml ယူမယ်", customer="92")
    client.post(f"/messages/{wrong}/parse", data={"csrf": token, "intent": "buy",
                                                  "product_id": str(pid(db, "Sauvage Eau de Parfum")), "size_ml": "5"})
    assert learned(db)[0][5] == 1  # corrections
    for n, customer in enumerate(("93", "94", "95"), start=3):
        tap(client, token, say(db, n, "ysl edp 5ml ယူမယ်", customer=customer))
        deliver(db)
    assert learned(db)[0][2:6] == ("pending", "Y Eau de Parfum", 3, 1)  # the owner must decide


# ---------- B3 owner approves -> next message automatic ----------

def test_b3_owner_approves_then_auto(shop, db):
    client, token = shop
    y_shop(db)
    auto_on(db)
    teach(client, token, say(db, 1, "ysl edp 10 ml ရောယူပါမယ်"), p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp")
    deliver(db)
    page = client.get("/learning").text
    assert "Nicknames" in page and "“<b>ysl edp</b>” → Y Eau de Parfum" in page and "✅ Approve" in page
    assert "📘 1 pattern to approve" in client.get("/").text
    approve(client, token, "ysl edp", db)
    assert learned(db)[0][2] == "approved"
    say(db, 2, "ysl edp 5ml ယူမယ်", customer="92")
    auto.run_once()
    assert len(deliver(db)) == 1


def test_b3b_rejected_pattern_is_ignored(shop, db):
    client, token = shop
    y_shop(db)
    teach(client, token, say(db, 1, "ysl edp 10 ml ရောယူပါမယ်"), p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp")
    p = scalar(db, "SELECT id FROM learned_patterns")
    client.post(f"/learning/{p}/decide", data={"csrf": token, "status": "rejected"})
    mid = say(db, 2, "ysl edp 5ml ယူမယ်", customer="92")
    assert scalar(db, "SELECT i.match FROM parse_items i JOIN parse_results r ON r.id = i.parse_result_id "
                      "WHERE r.message_id = :m AND r.is_current", m=mid) == "fuzzy"  # back to the rules


# ---------- B4 not stocked ----------

def test_b4_not_stocked_memory(shop, db):
    client, token = shop
    auto_on(db)
    mid = say(db, 1, "liquid brun 5ml ရှိလား")
    auto.run_once()
    assert outbox(db) == []
    shown = preview(client, token, mid, p0="not_stocked", nick0="liquid brun")
    assert "မရှိဘူးလို့ ပြန်ပြောမယ်။" in shown and "📘 “liquid brun” = မရှိဘူး" in shown
    confirm(client, token, shown)
    assert deliver(db) == ["မင်္ဂလာပါ။\nliquid brun ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။"]
    assert learned(db) == [("not_stocked", "liquid brun", "pending", None, 0, 0)]
    # pending: the next customer gets a one-tap 📘 suggestion, not an auto reply
    pending = say(db, 2, "liquid brun ရှိလား", customer="92")
    auto.run_once()
    assert deliver(db) == [] and button(client, pending)[0] == "📘 💬 Reply: we don't have it"
    approve(client, token, "liquid brun", db)
    say(db, 3, "liquid brun ရှိလား", customer="93")
    auto.run_once()
    assert deliver(db) == ["မင်္ဂလာပါ။\nliquid brun ကတော့ လောလောဆယ် မရှိသေးပါဘူးနော်။"]
    with SessionLocal() as s:
        wanted = {w.name: (w.times, w.customers) for w in reports.wanted(s)}
    assert wanted["liquid brun"] == (2, 2)
    assert "liquid brun" in client.get("/reports/wanted").text


def test_b4b_auto_not_stocked_off(shop, db):
    client, token = shop
    auto_on(db)
    teach(client, token, say(db, 1, "liquid brun 5ml ရှိလား"), p0="not_stocked", nick0="liquid brun")
    deliver(db)
    approve(client, token, "liquid brun", db)
    client.post("/settings/learning", data={"csrf": token, "auto_approve_after": "3", "greeting": "1"})
    mid = say(db, 2, "liquid brun ရှိလား", customer="92")
    auto.run_once()
    assert deliver(db) == [] and button(client, mid)[0] == "📘 💬 Reply: we don't have it"


# ---------- B5 greetings ----------

def test_b5_greeting(shop, db):
    client, _ = shop
    auto_on(db)
    with db.begin() as c:
        c.execute(text("INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) "
                       "SELECT id, 'swy', 'swy', 'seed' FROM products WHERE name = 'Stronger With You Intensely'"))
    say(db, 1, "hi")
    auto.run_once()
    assert deliver(db) == [GREETING]
    say(db, 2, "hi")  # we messaged them less than 6 h ago
    auto.run_once()
    assert deliver(db) == []
    say(db, 3, "hi swy 5ml ဘယ်လောက်လဲ")  # not only a greeting: the normal answer, no greeting again
    auto.run_once()
    assert deliver(db) == ["Stronger With You Intensely 5ml က 18,000 ကျပ်ပါ။ မှာယူချင်ရင် ပြောပေးပါနော်။"]
    say(db, 4, "မင်္ဂလာပါ ရှင့်", customer="92")
    auto.run_once()
    assert deliver(db) == [GREETING]


def test_b5b_greeting_switch_off(shop, db):
    client, token = shop
    auto_on(db)
    client.post("/settings/learning", data={"csrf": token, "auto_approve_after": "3", "auto_not_stocked": "1"})
    mid = say(db, 1, "hello")
    auto.run_once()
    assert deliver(db) == [] and button(client, mid) is None


# ---------- B6 undo ----------

def test_b6_card_undo(shop, db):
    client, token = shop
    y_shop(db)
    mid = say(db, 1, "ysl edp 10 ml ရောယူပါမယ်")
    before = scalar(db, "SELECT id FROM parse_results WHERE message_id = :m AND is_current", m=mid)
    teach(client, token, mid, p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp")
    assert len(learned(db)) == 1 and len(outbox(db)) == 1
    aid = scalar(db, "SELECT id FROM quick_actions WHERE message_id = :m", m=mid)
    client.post(f"/quick/{aid}/undo", data={"csrf": token})
    assert deliver(db) == [] and learned(db) == [] and items(db) == []
    assert scalar(db, "SELECT id FROM parse_results WHERE message_id = :m AND is_current", m=mid) == before
    assert "ဆိုတာ ဘယ်ပစ္စည်းလဲ?" in card_page(client, mid)  # the card is back


def test_b6b_ignore_and_question(shop, db):
    client, token = shop
    mid = say(db, 1, "ကျေးဇူးပါ အစ်မ")
    page = card_page(client, mid)
    assert "ဖောက်သည်က ဘာလုပ်ချင်တာလဲ?" in page and "ဘာမှမလုပ်နဲ့" in page
    shown = preview(client, token, mid, intent="ignore")
    assert "ဘာမှ မပို့ပါ" in shown
    confirm(client, token, shown)
    assert outbox(db) == [] and learned(db) == []
    assert scalar(db, "SELECT status FROM message_reviews WHERE message_id = :m", m=mid) == "done"
    other = say(db, 2, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", customer="92")
    r = client.post(f"/messages/{other}/teach", data={"csrf": token, "intent": "question"}, follow_redirects=False)
    assert r.headers["location"].endswith("#reply") and "/chats/" in r.headers["location"]


# ---------- B7 staff adds a new product: the owner prices it, then the list goes out ----------

def staff_client(db) -> tuple[TestClient, str]:
    from app.web.main import app

    with SessionLocal.begin() as s:
        s.add(User(username="staff1", password_hash=hash_password(PASSWORD), role="staff"))
    staff = TestClient(app, base_url="https://testserver")
    r = staff.post("/login", data={"username": "staff1", "password": PASSWORD, "csrf": csrf(staff), "next": "/"},
                   follow_redirects=False)
    assert r.status_code == 303
    return staff, csrf(staff, "/")


def test_b7_staff_new_product_waits_for_price(shop, db):
    owner, owner_token = shop
    auto_on(db)
    staff, token = staff_client(db)
    mid = say(db, 1, "liquid brun 5ml ယူမယ်")
    page = card_page(staff, mid)
    assert "➕ ပစ္စည်းအသစ်" in page and 'name="price0"' not in page  # staff: no price
    shown = preview(staff, token, mid, p0="new", brand0="French Avenue", name0="Liquid Brun", nick0="liquid brun")
    assert "ပိုင်ရှင်ကို ဈေးမေးမယ်" in shown
    confirm(staff, token, shown)
    auto.run_once()
    assert outbox(db) == [] and button(owner, mid) is None  # the item waits
    home = owner.get("/").text
    assert "💲 Liquid Brun" in home and "Save + send list" in home
    assert "Save + send list" not in staff.get("/").text  # only the owner prices
    row = scalar(db, "SELECT id FROM unknown_requests WHERE resolution = 'new_product'")
    owner.post(f"/learning/price/{row}", data={"csrf": owner_token, "price": "15,000", "full_size_ml": "100"})
    assert deliver(db) == ["မင်္ဂလာပါ။\n• Liquid Brun 5ml – 15,000 ကျပ်\nစုစုပေါင်း 15,000 ကျပ်ပါ။\n"
                           "ဝယ်ယူမယ်ဆိုရင် ဖုန်းနံပါတ် ပို့ပေးပါနော်။"]
    assert "💲 Liquid Brun" not in owner.get("/").text
    assert learned(db) == []  # "liquid brun" is the new product's own name: nothing more to learn


def test_b7b_owner_new_product_with_price(shop, db):
    client, token = shop
    mid = say(db, 1, "liquid brun 5ml ယူမယ်")
    assert 'name="price0"' in card_page(client, mid)
    teach(client, token, mid, p0="new", brand0="French Avenue", name0="Liquid Brun", price0="15000", nick0="liquid brun")
    assert deliver(db)[0].startswith("မင်္ဂလာပါ။\n• Liquid Brun 5ml – 15,000 ကျပ်")


# ---------- B8 conflicting nickname ----------

def test_b8_conflicting_nickname_asks_owner(shop, db):
    client, token = shop
    y_shop(db)
    mid = say(db, 1, "ysl edp 10 ml ရောယူပါမယ်")
    # "dior sauvage" is already a nickname of Sauvage: not saved, the owner decides
    shown = teach(client, token, mid, p0=str(pid(db, "Y Eau de Parfum")), nick0="dior sauvage")
    assert "already a nickname of Sauvage Eau de Parfum" in shown
    assert learned(db) == [] and len(deliver(db)) == 1  # the customer still got the answer
    home = client.get("/").text
    assert "⚠️ “dior sauvage”" in home
    page = client.get("/learning").text
    assert "Needs your decision" in page and "Keep it as it is" in page
    conflict = scalar(db, "SELECT id FROM audit_log WHERE action = 'learning.conflict'")
    client.post(f"/learning/conflicts/{conflict}", data={"csrf": token, "use_new": "0"})
    assert "Needs your decision" not in client.get("/learning").text
    assert scalar(db, "SELECT count(*) FROM product_aliases WHERE normalized_alias = 'dior sauvage'") == 1


def test_b8b_conflict_use_new_moves_nickname(shop, db):
    client, token = shop
    y_shop(db)
    teach(client, token, say(db, 1, "ysl edp 10 ml ရောယူပါမယ်"), p0=str(pid(db, "Y Eau de Parfum")), nick0="ysl edp")
    approve(client, token, "ysl edp", db)
    deliver(db)
    # someone teaches "ysl edp" as another product -> conflict with the approved one
    mid = say(db, 2, "sauvage noir 5ml ယူမယ်", customer="92")
    teach(client, token, mid, p0=str(pid(db, "Sauvage Eau de Parfum")), nick0="ysl edp")
    assert [r[:4] for r in learned(db)] == [("nickname", "ysl edp", "approved", "Y Eau de Parfum")]
    conflict = scalar(db, "SELECT id FROM audit_log WHERE action = 'learning.conflict'")
    client.post(f"/learning/conflicts/{conflict}", data={"csrf": token, "use_new": "1"})
    assert [r[:4] for r in learned(db)] == [("nickname", "ysl edp", "rejected", "Y Eau de Parfum"),
                                            ("nickname", "ysl edp", "approved", "Sauvage Eau de Parfum")]


def test_learning_settings_validation(shop, db):
    client, token = shop
    r = client.post("/settings/learning", data={"csrf": token, "auto_approve_after": "99", "greeting": "1"})
    assert "0-20 uses" in r.text and "Learning settings saved" not in r.text


def test_size_question_and_learn_off(shop, db):
    client, token = shop
    y_shop(db)
    mid = say(db, 1, "ysl edp ယူမယ်")  # no size
    page = card_page(client, mid)
    assert "ဘယ် size လဲ?" in page
    assert all(f'name="size0" value="{v}"' in page for v in ("2", "5", "10", "full"))
    teach(client, token, mid, p0=str(pid(db, "Y Eau de Parfum")), size0="5", learn=None)
    assert deliver(db)[0].startswith("မင်္ဂလာပါ။\n• Y Eau de Parfum 5ml – 18,000 ကျပ်")
    assert learned(db) == []  # learn box unchecked: nothing taught
    with db.connect() as c:
        audit = c.execute(text("SELECT details->>'intent' FROM audit_log WHERE action = 'learning.card_confirm'")).all()
    assert audit == [("buy",)]


def test_card_needs_an_answer(shop, db):
    client, token = shop
    mid = say(db, 1, "ကျေးဇူးပါ အစ်မ")
    r = client.post(f"/messages/{mid}/teach/preview", data={"csrf": token, "back": "/"})
    assert "ဘာလုပ်ချင်တာလဲ — တစ်ခု ရွေးပါ" in r.text  # redirected back to the card with the reason
