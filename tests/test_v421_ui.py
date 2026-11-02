"""docs/SPEC-v4.21-ios-messenger-ui.md: Messenger workspace (chat list | conversation | customer panel).
The look, the phone widths and the 3-tap owner flows (U1/U3/U4) are checked in a real browser by
scripts/ui_check.py (tests/test_ui_check.py); here: what the pages contain."""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.parser.worker import run_batch

from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import add, customer_id, scalar
from tests.test_payments import waiting_for_payment
from tests.test_web import client, log_in  # noqa: F401  (fixture)


def sent_by(db, customer: str, ext: int, body: str, kind: str, user: bool) -> None:
    """An outgoing message our outbox sent: by the bot (no user) or by a person."""
    add(ext, body, direction="out", customer=customer)
    mid = scalar(db, "SELECT id FROM messages WHERE external_message_id = :e AND customer_id = :c", e=str(ext),
                 c=customer_id(db, customer))
    with db.begin() as c:
        c.execute(text("INSERT INTO outbox (customer_id, text, reply_kind, status, idempotency_key, created_by, "
                       "sent_message_id) VALUES (:c, :t, :k, 'sent', :i, :u, :m)"),
                  {"c": customer_id(db, customer), "t": body, "k": kind, "i": f"t-{ext}", "m": mid,
                   "u": scalar(db, "SELECT id FROM users ORDER BY id LIMIT 1") if user else None})


def rows(page: str) -> list[str]:
    """The chat list's customer links, top to bottom."""
    return re.findall(r'class="chatrow[^"]*" href="/chats/(\d+)"', page)


def test_list_needs_first_with_dot_auto_prefix_and_segments(shop, db):  # noqa: F811
    client, token = shop
    now = datetime.now(UTC)
    add(1, "hello", customer="501", when=now - timedelta(minutes=30))
    sent_by(db, "501", 2, "18,000 ကျပ်ပါ", "custom", user=False)  # the bot answered: "Auto: …"
    cid = waiting_for_payment(client, token, db, customer="502")  # payment info sent, nothing needs a person
    add(3, "liquid brun 5ml ယူမယ်", customer="503", when=now - timedelta(minutes=5))  # unknown product: a card
    run_batch()
    with db.begin() as c:
        c.execute(text("UPDATE messages SET received_at = now() - interval '2 hours' "
                       "WHERE customer_id = :c"), {"c": cid})
    page = client.get("/chats").text
    needs = customer_id(db, "503")
    assert rows(page)[0] == str(needs)  # needs-you first
    row = page[page.index(f'href="/chats/{needs}"'):].split("</a>")[0]
    assert 'class="dot"' in row and "unread" in page
    auto_row = page[page.index(f'href="/chats/{customer_id(db, "501")}"'):].split("</a>")[0]
    assert "Auto: 18,000 ကျပ်ပါ" in auto_row and 'class="dot"' not in auto_row
    assert "Needs me 1" in page
    assert rows(client.get("/chats?seg=needs").text) == [str(needs)]
    assert rows(client.get("/chats?seg=orders").text) == [str(cid)]
    phone = scalar(db, "SELECT phone FROM customer_phones WHERE customer_id = :c LIMIT 1", c=cid)
    assert rows(client.get(f"/chats?q={phone[-6:]}").text) == [str(cid)]  # search by phone
    assert rows(client.get("/chats?q=nobody-like-this").text) == []


def test_conversation_bubbles_say_who_sent_them(shop, db):  # noqa: F811
    client, _ = shop
    add(1, "eros 10ml ဈေး", customer="511", when=datetime.now(UTC) - timedelta(minutes=9))
    sent_by(db, "511", 2, "Eros 10ml – 25,000 ကျပ်", "price", user=False)
    sent_by(db, "511", 3, "ခဏစောင့်ပေးပါနော်", "holding", user=False)
    sent_by(db, "511", 4, "ok I check", "custom", user=True)
    add(5, "typed in Telegram", direction="out", customer="511")
    page = client.get(f"/chats/{customer_id(db, '511')}").text
    thread = page[page.index('id="thread"'):]
    bubble = {b: thread[thread.index(b):][:900] for b in ("Eros 10ml – 25,000", "ခဏစောင့်ပေးပါနော်", "ok I check", "typed in")}
    assert "Auto-reply · Delivered" in bubble["Eros 10ml – 25,000"]
    assert "Auto · please wait" in bubble["ခဏစောင့်ပေးပါနော်"]
    assert '<span class="by">owner</span>' in bubble["ok I check"]
    assert '<span class="by">You</span>' in bubble["typed in"]
    assert page.count('class="bubble out by-auto"') == 1 and 'class="bubble out by-hold"' in page
    # the workspace: list + conversation + panel, this customer highlighted, Pause auto-reply in the header
    assert 'id="ws" class="ws ws-chat"' in page and 'aria-current="page">' in page
    assert f'href="/chats/{customer_id(db, "511")}" aria-current="page"' in page
    assert "Pause auto-reply" in page and 'id="cart-sheet"' in page


def test_needs_you_panel_in_the_conversation_only_this_customer(shop, db):  # noqa: F811
    client, token = shop
    add(1, "liquid brun 5ml ယူမယ်", customer="521", when=datetime.now(UTC) - timedelta(minutes=5))
    add(2, "ombre nomade 5ml ယူမယ်", customer="522", when=datetime.now(UTC) - timedelta(minutes=5))
    run_batch()
    page = client.get(f"/chats/{customer_id(db, '521')}").text
    panel = page[page.index('class="needs-panel"'):page.index('id="reply"')]
    assert "liquid brun" in panel and "ombre" not in panel
    assert 'class="teach stack"' in panel and "✅ ပို့မယ်" in panel  # the suggested reply + Send, right there
    quiet = waiting_for_payment(client, token, db, customer="523")
    with db.begin() as c:
        c.execute(text("UPDATE messages SET received_at = now() - interval '2 hours' WHERE customer_id = :c"),
                  {"c": quiet})
    assert 'class="needs-panel"' not in client.get(f"/chats/{quiet}").text


def test_panel_payment_and_order_buttons(shop, db):  # noqa: F811
    client, token = shop
    cid = waiting_for_payment(client, token, db, customer="531")
    add(9, "", customer="531", kind="photo")
    from app.parser.worker import scan_payments

    scan_payments()
    check = scalar(db, "SELECT id FROM payment_checks WHERE order_id IN (SELECT id FROM orders WHERE customer_id = :c)",
                   c=cid)
    page = client.get(f"/chats/{cid}").text
    assert f'href="/payments/{check}"' in page.split('class="group-label">Payment')[1][:1500]  # panel: Payment first
    assert 'class="button primary check-pay"' in page  # "Check payment" under the photo bubble
    with db.begin() as c:
        c.execute(text("UPDATE orders SET status = 'paid', paid_at = now(), order_no = nextval('order_no_seq') "
                       "WHERE customer_id = :c"), {"c": cid})
        c.execute(text("UPDATE payment_checks SET decision = 'approved' WHERE id = :k"), {"k": check})
    page = client.get(f"/chats/{cid}").text
    order = scalar(db, "SELECT id FROM orders WHERE customer_id = :c", c=cid)
    assert f'action="/orders/{order}/status"' in page and 'value="packed"' in page  # next-status button
    assert f'name="back" value="/chats/{cid}"' in page
    r = client.post(f"/orders/{order}/status", data={"csrf": token, "to": "packed", "back": f"/chats/{cid}"},
                    follow_redirects=False)
    assert r.headers["location"].startswith(f"/chats/{cid}")
    assert "Past orders" in client.get(f"/chats/{cid}").text


def test_orders_unpaid_and_check_tabs(shop, db):  # noqa: F811
    client, token = shop
    cid = waiting_for_payment(client, token, db, customer="541")
    order = scalar(db, "SELECT id FROM orders WHERE customer_id = :c", c=cid)
    page = client.get("/orders?tab=unpaid").text
    assert f'id="order-{order}"' in page and f'action="/orders/{order}/remind"' in page
    assert f'id="order-{order}"' not in client.get("/orders?tab=to_pack").text
    add(9, "", customer="541", kind="photo")
    from app.parser.worker import scan_payments

    scan_payments()
    assert f'id="order-{order}"' in client.get("/orders?tab=check").text


def test_menu_sidebar_and_phone_tabs(shop, db):  # noqa: F811
    client, _ = shop
    page = client.get("/orders").text
    side = page[page.index('class="sidebar"'):page.index('class="tabbar"')]
    for label in ("Chats", "Orders", "Payments", "Products &amp; prices", "Sales", "Auto-reply", "Settings"):
        assert label in side, label
    assert 'role="switch"' in side
    tabbar = page[page.index('class="tabbar"'):page.index('id="more"')]
    assert [re.sub(r"<[^>]+>", "", s) for s in re.findall(r"<span>(.*?)</span>", tabbar)] == [
        "Chats", "Orders", "Payments", "More"]

