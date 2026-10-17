"""docs/SPEC-v4.md 4.5 acceptance tests E1-E4: Burmese dashboard, help, practice mode.

E1 renders every page (owner and staff, lang=my, with data on every page) and scans the
visible text (incl. title / placeholder / aria-label / alt) for English UI words. Product
names, brands, customer texts and shop data (FAQ, payment methods) are removed first;
<code> and <pre> are technical / customer text."""
import glob
import html
import re

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models import User
from app.models.messages import REVIEW_STATUSES
from app.models.orders import CHECK_DECISIONS, ORDER_STATUSES
from app.models.parsing import INTENTS
from app.replies.templates import TEMPLATES
from app.web import help as help_page, i18n, practice
from app.web.auth import hash_password
from app.web.i18n_my import CODES, MY
from tests.test_cart import deliver, say, shop  # noqa: F401  (fixture)
from tests.test_messaging import scalar
from tests.test_payments import downloaded, photo, waiting_for_payment
from tests.test_prices import xlsx
from tests.test_v4_teaching import teach
from tests.test_web import PASSWORD, client, csrf  # noqa: F401  (fixture)

# whole words; English UI words must not be left on a Burmese page
UI_WORDS = (
    "Inbox", "Payments", "Orders", "Chats", "Products", "Prices", "Sales", "Reports", "Learning", "Settings", "Users",
    "Health", "Help", "Practice", "Log", "Needs", "Search", "Filter", "Reset", "Save", "save", "Cancel", "cancel",
    "Delete", "delete", "Undo", "Done", "done", "Ignore", "ignore", "Back", "Add", "Edit", "Send", "Sent", "sent",
    "Approve", "approve", "Reject", "Status", "Customer", "Note", "Name", "Brand", "Password", "Username", "Language",
    "Quantity", "Qty", "Size", "Total", "Revenue", "Profit", "Cost", "Nothing", "Newer", "Older", "Mark", "Remove",
    "remove", "Open", "open", "Show", "Apply", "Next", "Price", "Product", "Message", "Waiting", "waiting", "review",
    "parsed", "unanswered", "resolve", "Today", "Activity", "When", "Who", "What", "Details", "Role", "Active",
    "active", "inactive", "Phone", "Address", "Cart", "cart", "confirmed", "Confirm", "Check", "Download", "Upload",
    "Keywords", "Answer", "Title", "Account", "Method", "Amount", "Approved", "pending", "Several", "photo", "Photo",
    "Loading", "bottle", "stock", "Aliases", "alias", "Order", "order", "Payment", "payment", "price", "product",
    "sending", "queued", "failed", "Try", "Dismiss", "Custom", "Ask", "Score", "Start", "Right", "wrong", "learned",
    "the", "and", "you", "your", "for", "with", "this", "is", "to", "of", "not", "yes", "or", "by", "from", "auto",
)
SHOP_DATA = ("Emporio Armani", "Stronger With You Intensely", "Dior", "Sauvage Eau de Parfum", "Yves Saint Laurent",
             "Y Eau de Parfum", "Test Shop", "KPay", "Liquid Brun", "Decant Inbox")


def visible(page: str, data: list[str]) -> str:
    page = re.sub(r"<(script|style|code|pre|samp|textarea)\b.*?</\1>", " ", page, flags=re.S)
    attrs = " ".join(html.unescape(v) for v in re.findall(r'\b(?:title|placeholder|aria-label|alt)="([^"]*)"', page))
    body = html.unescape(re.sub(r"<[^>]+>", " ", page)) + " " + attrs
    for value in sorted(data, key=len, reverse=True):
        body = body.replace(value, " ")
    return body


def english_words(page: str, data: list[str]) -> list[str]:
    body = visible(page, data)
    return sorted({w for w in UI_WORDS if re.search(rf"(?<![\w.]){re.escape(w)}(?![\w.])", body)})


def shop_data(db) -> list[str]:
    with db.connect() as c:
        rows = [*c.execute(text("SELECT raw_text FROM messages")), *c.execute(text("SELECT name FROM products")),
                *c.execute(text("SELECT brand FROM products")), *c.execute(text("SELECT display_name FROM customers")),
                *c.execute(text("SELECT title FROM faq_entries")), *c.execute(text("SELECT answer FROM faq_entries")),
                *c.execute(text("SELECT keywords FROM faq_entries")), *c.execute(text("SELECT text FROM outbox")),
                *c.execute(text("SELECT text FROM learned_patterns")), *c.execute(text("SELECT username FROM users")),
                *c.execute(text("SELECT alias_text FROM product_aliases"))]
    with SessionLocal() as s:  # practice messages are shop data too
        practice_texts = [e.text for e in practice.exercises(s)]
    return [r[0] for r in rows if r[0]] + practice_texts + list(SHOP_DATA)


def burmese_client(db, username: str, role: str) -> tuple[TestClient, str]:
    from app.web.main import app

    with SessionLocal.begin() as s:
        user = s.query(User).filter_by(username=username).one_or_none()
        if user is None:
            s.add(User(username=username, password_hash=hash_password(PASSWORD), role=role, language="my"))
        else:
            user.language = "my"
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/login", data={"username": username, "password": PASSWORD, "csrf": csrf(c), "next": "/"},
               follow_redirects=False)
    assert r.status_code == 303
    return c, csrf(c, "/")


def busy_shop(owner, token, db, tmp_path, monkeypatch) -> dict:
    """Data on every page: a card, a one-tap button, a cart, a payment to check, a paid order,
    a learned pattern, an unanswered question, a price preview."""
    ids = {}
    ids["card"] = say(db, 1, "ysl edp 10 ml ရောယူပါမယ်", customer="81")  # fuzzy name -> teaching card
    ids["quick"] = say(db, 2, "stw intensely 5ml ဘယ်လောက်လဲ", customer="82")  # one-tap price
    ids["question"] = say(db, 3, "ဒီအနံ့က ဘယ်လိုမျိုးလဲ", customer="83")
    teach(owner, token, say(db, 4, "liquid brun 5ml ရှိလား", customer="84"), p0="not_stocked", nick0="liquid brun")
    waiting_for_payment(owner, token, db, customer="85")
    photo(1, customer="85")
    paid = scalar(db, "SELECT max(id) FROM payment_checks")
    owner.get(f"/payments/{paid}")
    downloaded(db, tmp_path, monkeypatch, paid)
    owner.post(f"/payments/{paid}/approve", data={"csrf": token, "transaction_id": "TX1", "amount": "18000",
                                                   "method": "KPay"})
    waiting_for_payment(owner, token, db, customer="86")
    photo(2, customer="86")
    ids["check"] = scalar(db, "SELECT max(id) FROM payment_checks")
    ids["chat"] = scalar(db, "SELECT id FROM customers WHERE external_user_id = '86'")
    ids["product"] = scalar(db, "SELECT id FROM products WHERE name = 'Stronger With You Intensely'")
    deliver(db)
    return ids


def pages(ids: dict) -> list[str]:
    return ["/", "/?intent=all&status=all", f"/messages/{ids['card']}", f"/messages/{ids['quick']}",
            f"/messages/{ids['question']}", "/chats", f"/chats/{ids['chat']}", f"/chats/{ids['chat']}?tab=cart",
            f"/chats/{ids['chat']}?compose=price&make=1", f"/chats/{ids['chat']}?compose=cart",
            "/payments", f"/payments/{ids['check']}", "/orders", "/orders?tab=all", "/products",
            f"/products/{ids['product']}", "/sales", "/sales?range=month", "/reports/wanted", "/health", "/help",
            "/practice", "/practice/1"]


def test_e1_every_page_burmese(shop, db, tmp_path, monkeypatch):
    owner, token = shop
    ids = busy_shop(owner, token, db, tmp_path, monkeypatch)
    me, my_token = burmese_client(db, "owner", "owner")  # the shop fixture's owner, now in Burmese
    staff, staff_token = burmese_client(db, "staffmy", "staff")
    data = shop_data(db)
    owner_only = ["/prices", "/settings", "/learning", "/users", "/activity", "/ai"]
    found = {}
    for who, c in (("owner", me), ("staff", staff)):
        for path in pages(ids) + (owner_only if who == "owner" else []):
            r = c.get(path)
            assert r.status_code == 200, (who, path)
            assert 'lang="my"' in r.text
            if words := english_words(r.text, data):
                found[f"{who} {path}"] = words
    # pages reached by a POST: card preview, practice result, price preview, error page, login
    r = me.post(f"/messages/{ids['card']}/teach/preview",
                data={"csrf": my_token, "p0": str(scalar(db, "SELECT id FROM products WHERE name = 'Y Eau de Parfum'")),
                      "learn": "1", "nick0": "ysl edp", "back": "/"})
    posted = {"card preview": r.text}
    staff.post("/practice/reset", data={"csrf": staff_token})
    page = staff.get("/practice/1").text
    choice = "tap" if 'value="tap"' in page else "card"
    posted["practice result"] = staff.post("/practice/1", data={"csrf": staff_token, "choice": choice}).text
    posted["price preview"] = me.post("/prices/import", data={"csrf": my_token}, files={"file": ("p.xlsx", xlsx(
        ["Dior", "Sauvage Eau de Parfum", 100, 420000, None, 21000, 38000, "yes"]))}).text
    error = staff.get("/settings")
    assert error.status_code == 403
    posted["error"] = error.text
    staff.post("/logout", data={"csrf": staff_token})
    posted["login"] = staff.get("/login").text  # after logout: still the user's language
    posted["login fresh"] = TestClient(staff.app, base_url="https://testserver").get("/login").text
    for name, page in posted.items():
        assert 'lang="my"' in page, name
        if words := english_words(page, data):
            found[name] = words
    assert not found, "\n".join(f"{page}: {words}" for page, words in found.items())


def test_e1b_every_template_key_is_translated():
    keys = set()
    for path in glob.glob("app/web/templates/*.html"):
        source = open(path, encoding="utf-8").read()
        keys |= {m.group(2) for m in re.finditer(r"""\bt\(\s*(["'])(.+?)\1""", source)}
        keys |= set(re.findall(r'ui\.help\(\s*"(.+?)"\)', source))
    assert len(keys) > 400
    assert sorted(k for k in keys if k not in MY) == []
    # enum values and labels made in Python
    for value in (*INTENTS, *REVIEW_STATUSES, *ORDER_STATUSES, *CHECK_DECISIONS, "owner", "staff"):
        assert value in CODES, value
    from app.orders.payments import REASON_LABELS
    from app.orders.sales import RANGES
    from app.web.learning import KIND_TITLES
    from app.web.orders import STATUS_LABELS, TABS
    labels = [*REASON_LABELS.values(), *RANGES.values(), *KIND_TITLES.values(), *STATUS_LABELS.values(),
              *(label for label, _, _ in TABS.values()), *(t.label for t in TEMPLATES)]
    assert [label for label in labels if i18n.translate(label, "my") == label] == []


def test_e1c_python_texts_translated_by_pattern():
    t = lambda s: i18n.translate(s, "my")  # noqa: E731
    assert t("Order #1001: 📦 Packed. Undo for 60 s.") == "အော်ဒါ #1001: 📦 ထုပ်ပြီး။ ၆၀ စက္ကန့်အတွင်း ပြန်ဖျက်လို့ရ။"
    assert t("🛒 Add 2 known items + send list") == "🛒 သိတဲ့ပစ္စည်း 2 ခု ထည့်ပြီး စာရင်းပို့မယ်"
    assert t("Marked done.") == "“ပြီးပြီ” လို့ မှတ်ပြီး။"
    assert t("Cancels the waiting_payment order (18,000 ကျပ်).") == "ငွေစောင့်နေ အော်ဒါ (18,000 ကျပ်) ကို ပယ်မယ်။"
    assert t("customer text nobody knows") == "customer text nobody knows"  # unknown text is left alone
    assert i18n.translate("Marked done.", "en") == "Marked done."
    tl, tr, code = i18n.for_lang("my")
    assert str(tl("Sending in {n} s", n=5)) == "5 စက္ကန့်အတွင်း ပို့မယ်" and code("ask_price") == "ဈေးမေး"
    assert str(tl("{what} sent", what="<b>")) == "&lt;b&gt; ပို့ပြီး"  # values are escaped


def test_e2_practice_writes_nothing(shop, db):
    owner, token = shop
    staff, staff_token = burmese_client(db, "learner", "staff")

    def counts() -> dict[str, int]:
        with db.connect() as c:
            tables = [r[0] for r in c.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"))]
            return {t: c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in tables}

    before = counts()
    assert "လေ့ကျင့်ခန်း" in staff.get("/practice").text
    staff.post("/practice/reset", data={"csrf": staff_token})
    steps = {}
    n = 1
    while (r := staff.get(f"/practice/{n}")).status_code == 200:
        steps[n] = r.text
        n += 1
    assert len(steps) >= 5
    tap = next(k for k, page in steps.items() if 'name="choice" value="tap"' in page)
    card = next(k for k, page in steps.items() if 'name="intent"' in page and f'action="/practice/{k}"' in page)
    wrong = staff.post(f"/practice/{tap}", data={"csrf": staff_token, "choice": "wrong"}).text
    assert "❌ မမှန်ဘူး" in wrong  # the app was right: tapping was the right answer
    right = staff.post(f"/practice/{tap}", data={"csrf": staff_token, "choice": "tap"}).text
    assert "✅ မှန်တယ်!" in right and "ဖောက်သည် ရမယ့်စာ" in right and "<b>1 / 1</b>" in right
    answered = staff.post(f"/practice/{card}", data={"csrf": staff_token, "intent": "buy", "learn": "1",
                                                     "phrase": "လေးထည့်ထားပေး"}).text
    assert "✅ မှန်တယ်!" in answered and "<b>2 / 2</b>" in answered
    # a card question without an answer shows the card again (nothing saved either)
    assert "တစ်ခု ရွေးပါ" in staff.post(f"/practice/{card}", data={"csrf": staff_token}).text
    assert counts() == before
    assert deliver(db) == []
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM customers WHERE channel = 'practice'")).scalar() == 0


def test_e2b_practice_exercises_follow_the_catalog(shop, db):
    with SessionLocal() as s:
        items = practice.exercises(s)
    assert {e.product for e in items} <= {None, practice.NOT_STOCKED, "Stronger With You Intensely",
                                          "Sauvage Eau de Parfum", "Y Eau de Parfum"}
    assert any(e.key.startswith("s") for e in items) and any(e.key.startswith("v") for e in items)
    exercise = next(e for e in items if e.key == "v3")  # liquid brun: we don't sell it
    assert practice.right(exercise, practice.Answer("ask_stock", practice.NOT_STOCKED, 5))
    assert not practice.right(exercise, practice.Answer("ask_stock", "Y Eau de Parfum", 5))


def test_e3_help_page_renders_the_guide(shop, db):
    owner, _ = shop
    page = owner.get("/help").text
    assert "ဝန်ထမ်း လမ်းညွှန်" in page and '<h2 id="s1">' in page
    for section in ("စာတစ်စောင် ဝင်လာရင် ဘာလုပ်ရမလဲ", "👀 စစ်ပြီး ဖြေမယ် ကတ်",  # 4.11 L5 "💳 ငွေလွှဲ စစ်နည်း", "KPay app",
                    "❗ မလုပ်ရမယ့်အရာများ", "🙋 မသိရင် ဘယ်သူ့ကို မေးမလဲ", "📦 ထုပ် → 🚚 ပို့ → ✅ ရောက်"):
        assert section in page, section
    staff, _ = burmese_client(db, "helpme", "staff")
    assert staff.get("/help").status_code == 200
    anonymous = TestClient(owner.app, base_url="https://testserver")
    assert anonymous.get("/help", follow_redirects=False).status_code == 303
    body, toc = help_page.render("# T\n\n## A <b>\n- **x** `y`\n1. one\n\ntext <script>")
    assert "<h2 id=\"s1\">A &lt;b&gt;</h2>" in body and "<li><b>x</b> <code>y</code></li>" in body
    assert "<ol>" in body and "&lt;script&gt;" in body and toc == [("s1", "A <b>")]
    # the "?" next to sections: one sentence each
    assert owner.get("/").text.count('<details class="help">') >= 2


def test_e4_language_switch_persists_per_user(shop, db):
    owner, token = shop
    staff, staff_token = burmese_client(db, "switcher", "staff")
    assert ">စာဝင်<" in staff.get("/").text
    r = staff.post("/language", data={"csrf": staff_token, "language": "en", "back": "/orders"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/orders"
    assert scalar(db, "SELECT language FROM users WHERE username = 'switcher'") == "en"
    assert ">Inbox<" in staff.get("/").text
    assert scalar(db, "SELECT language FROM users WHERE username = 'owner'") == "en"  # the owner keeps theirs
    again = TestClient(staff.app, base_url="https://testserver")
    again.post("/login", data={"username": "switcher", "password": PASSWORD, "csrf": csrf(again), "next": "/"})
    assert ">Inbox<" in again.get("/").text  # a new session: still English
    again.post("/language", data={"csrf": csrf(again, "/"), "language": "my"})
    assert ">စာဝင်<" in again.get("/").text and ">စာဝင်<" in staff.get("/").text
    assert staff.post("/language", data={"csrf": staff_token, "language": "fr"}).status_code == 400
    with db.connect() as c:
        audit = [tuple(r) for r in c.execute(text(
            "SELECT u.username, a.action FROM audit_log a JOIN users u ON u.id = a.user_id"))]
    assert ("switcher", "user.language") in audit
    assert ">Inbox<" in owner.get("/").text
