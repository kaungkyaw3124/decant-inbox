"""docs/SPEC-v4.7-graduation.md acceptance tests G1-G5: SHADOW -> AUTO graduation, the safety
brake, manual switches, and the weekly aggregate summary (+ how it is committed and pushed)."""
import re
import subprocess
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.ai import graduation, service
from app.ai import settings as ai_settings
from app.core.db import SessionLocal
from tests.test_cart import shop  # noqa: F401  (fixture)
from tests.test_messaging import add, scalar
from tests.test_v46_ai import HAWAS, YSL, ai, answer, calls, mode, worker_step, ysl_answer  # noqa: F401
from tests.test_v4_teaching import auto_on, pid
from tests.test_web import client, log_in  # noqa: F401  (fixture)

YANGON = ZoneInfo("Asia/Yangon")
_ten = datetime.now(YANGON).replace(hour=10, minute=0, second=0, microsecond=0)
NOW = (_ten if _ten <= datetime.now(YANGON) else _ten - timedelta(days=1)).astimezone(UTC)  # past, after 09:00


@pytest.fixture
def grad(ai):  # noqa: F811
    graduation._seen.clear()
    yield ai


def settings(**values) -> None:
    with SessionLocal.begin() as s:
        ai_settings.save(s, {k: v.isoformat() if isinstance(v, datetime) else v for k, v in values.items()}, None)


def cfg() -> dict:
    with SessionLocal() as s:
        return ai_settings.load(s)


def seed(db, n: int, decision: str = "accepted", ago: timedelta = timedelta(days=1), wrong: bool = False,
         at: datetime | None = None, tag: str = "") -> None:
    """n AI calls (each with its own message) decided / made `ago` before NOW."""
    if n == 0:
        return
    when = at or NOW - ago
    with db.begin() as c:
        cid = c.execute(text("SELECT id FROM customers WHERE external_user_id = '77'")).scalar()
        if cid is None:
            cid = c.execute(text("INSERT INTO customers (channel, external_user_id, display_name) "
                                 "VALUES ('telegram', '77', 'Seed') RETURNING id")).scalar()
        ids = c.execute(text(
            "INSERT INTO messages (channel, external_chat_id, external_message_id, customer_id, raw_text, received_at) "
            "SELECT 'telegram', '77', :tag || '-' || g || '-' || gen_random_uuid(), :cid, 'seed', :t "
            "FROM generate_series(1, :n) g RETURNING id"), {"tag": tag or decision, "cid": cid, "t": when, "n": n})
        for (mid,) in ids:
            c.execute(text(
                "INSERT INTO ai_calls (message_id, model, mode, ok, decision, decided_at, created_at, wrong_product) "
                "VALUES (:m, 'gpt-6-luna', 'shadow', :ok, :d, :at, :at, :w)"),
                {"m": mid, "ok": decision not in ("error", "rejected"), "d": decision,
                 "at": when, "w": wrong})


def tick(now=NOW) -> list[str]:
    graduation._seen.clear()
    return graduation.tick(now, publish_fn=lambda repo, rel: "not published (test)")


def ready_shop(db) -> None:
    """Everything a graduation needs: 8 days of SHADOW, 58 accepted + 2 corrected (97%), few errors."""
    settings(mode="shadow", auto_graduate=True, shadow_since=NOW - timedelta(days=8))
    seed(db, 58, "accepted")
    seed(db, 2, "corrected")
    seed(db, 2, "error")


def audit(db, action: str) -> list[dict]:
    with db.connect() as c:
        return [r[0] for r in c.execute(text("SELECT details FROM audit_log WHERE action = :a ORDER BY id"),
                                        {"a": action})]


# ---------- G1 graduation ----------

def test_g1_graduates_when_everything_is_met(grad, shop, db):
    client, _ = shop
    ready_shop(db)
    with SessionLocal() as s:
        p = graduation.progress(s, NOW)
    assert p.ready and (p.decisions, p.wrong_products) == (60, 0) and round(p.accuracy, 3) == 0.967
    assert tick() == ["🧠 AI switched to AUTO: accuracy 97% on 60 decisions, 0 wrong products"]
    assert cfg()["mode"] == "auto" and cfg()["auto_graduate"] is True
    [details] = audit(db, "ai.graduated")
    assert details["actor"] == "auto-graduation" and details["decisions"] == 60
    assert "🧠 AI switched to AUTO: accuracy 97% on 60 decisions, 0 wrong products" in client.get("/").text
    assert tick(NOW + timedelta(hours=1)) == []  # once a day


def test_g1_only_at_nine_yangon(grad, shop, db):
    ready_shop(db)
    early = NOW.astimezone(YANGON).replace(hour=8, minute=59).astimezone(UTC)
    assert tick(early) == [] and cfg()["mode"] == "shadow"
    assert tick(early + timedelta(minutes=2))[0].startswith("🧠 AI switched to AUTO")


# ---------- G2 a condition missing ----------

@pytest.mark.parametrize("missing", ["6 days", "40 decisions", "94%", "1 wrong product", "12% errors"])
def test_g2_stays_shadow_and_shows_what_is_missing(grad, shop, db, missing):
    client, _ = shop
    settings(mode="shadow", auto_graduate=True,
             shadow_since=NOW - timedelta(days=6 if missing == "6 days" else 8))
    if missing == "40 decisions":
        seed(db, 40)
    elif missing == "94%":
        seed(db, 47)
        seed(db, 3, "corrected")
    elif missing == "1 wrong product":
        seed(db, 59)
        seed(db, 1, "corrected", wrong=True)
    elif missing == "12% errors":
        seed(db, 66)
        seed(db, 9, "error")  # 9 / 75 calls
    else:
        seed(db, 60)
    assert tick() == [] and cfg()["mode"] == "shadow"
    with SessionLocal() as s:
        p = graduation.progress(s, NOW)
    bad = [c.key for c in p.conditions if c.status != "ok"]
    assert bad == [{"6 days": "days", "40 decisions": "decisions", "94%": "accuracy", "1 wrong product": "wrong",
                    "12% errors": "errors"}[missing]]
    page = client.get("/ai").text
    expected = {"6 days": "1 more days", "40 decisions": "10 more checked suggestions",
                "94%": "accuracy must reach 95%", "1 wrong product": "no wrong product allowed in 14 days",
                "12% errors": "errors must be under 10%"}[missing]
    assert "Graduation progress" in page and expected in page
    assert page.count("✅") >= 4 and ("⏳" in page or "❌" in page)


def test_g2_old_decisions_outside_14_days_do_not_count(grad, shop, db):
    settings(mode="shadow", auto_graduate=True, shadow_since=NOW - timedelta(days=30))
    seed(db, 60, ago=timedelta(days=15))
    seed(db, 10)
    with SessionLocal() as s:
        assert graduation.progress(s, NOW).decisions == 10


# ---------- G3 safety brake ----------

def auto_handled(db, ai) -> int:  # noqa: F811
    """An AUTO-handled AI message ("ysl edp 10 ml" -> Y EDP 10ml), with AI mode AUTO."""
    settings(mode="auto", auto_graduate=True, shadow_since=NOW - timedelta(days=9),
             auto_since=datetime.now(UTC) - timedelta(hours=1))
    auto_on(db)
    ai.answer = ysl_answer(db, confidence=0.95)
    from tests.test_cart import say

    mid = say(db, 1, YSL)
    worker_step()
    assert calls(db)[0][1] == "auto"
    return mid


def test_g3_product_correction_on_auto_message_brakes(grad, shop, db):
    client, token = shop
    mid = auto_handled(db, grad)
    page = client.get(f"/messages/{mid}").text
    assert "🧠 AI was wrong" in page
    sauvage = pid(db, "Sauvage Eau de Parfum")
    r = client.post(f"/messages/{mid}/ai-wrong", data={"csrf": token, "p0": str(sauvage), "size0": "10",
                                                       "qty0": "1", "intent": "buy"}, follow_redirects=True)
    assert "Saved as an AI mistake" in r.text and "The AI is back in SHADOW" in r.text
    assert cfg()["mode"] == "shadow" and cfg()["auto_graduate"] is True  # may graduate again later
    assert scalar(db, "SELECT decision || '/' || wrong_product FROM ai_calls") == "corrected/true"
    assert scalar(db, "SELECT method FROM parse_results WHERE message_id = :m AND is_current", m=mid) == "human"
    assert scalar(db, "SELECT corrections FROM learned_patterns WHERE text = 'ysl edp'") == 1  # AI's pattern
    notice = "🧠 AI switched back to SHADOW: an admin changed the product of an AUTO-handled message"
    assert notice in client.get("/").text
    # the window restarts at the brake: no graduation the next morning, even with good old numbers
    seed(db, 60, ago=timedelta(days=2))
    with SessionLocal() as s:
        p = graduation.progress(s, NOW + timedelta(days=1))
    assert p.since > datetime.now(UTC) - timedelta(minutes=5) and p.decisions == 0
    assert not tick(NOW + timedelta(days=1)) and cfg()["mode"] == "shadow"


def test_g3_size_only_correction_does_not_brake(grad, shop, db):
    client, token = shop
    mid = auto_handled(db, grad)
    y = pid(db, "Y Eau de Parfum")
    client.post(f"/messages/{mid}/ai-wrong", data={"csrf": token, "p0": str(y), "size0": "5", "qty0": "1",
                                                   "intent": "buy"})
    assert scalar(db, "SELECT decision || '/' || wrong_product FROM ai_calls") == "corrected/false"
    assert cfg()["mode"] == "auto"


def test_g3_edit_form_correction_counts_too(grad, shop, db):
    client, token = shop
    mid = auto_handled(db, grad)
    client.post(f"/messages/{mid}/parse", data={"csrf": token, "intent": "buy",
                                                "product_id": str(pid(db, "Good Girl")), "size_ml": "10"})
    assert scalar(db, "SELECT decision || '/' || wrong_product FROM ai_calls") == "corrected/true"
    assert cfg()["mode"] == "shadow"


@pytest.mark.parametrize("right,braked", [(26, True), (27, False)])  # 87% brakes, 90% does not
def test_g3_accuracy_on_last_30_brakes(grad, shop, db, right, braked):
    client, _ = shop
    settings(mode="auto", auto_graduate=True, shadow_since=NOW - timedelta(days=20),
             auto_since=NOW - timedelta(days=5))
    seed(db, 40, "accepted", ago=timedelta(days=6))  # older: not among the last 30
    seed(db, right - 10, "auto", ago=timedelta(hours=5))
    seed(db, 10, "accepted", ago=timedelta(hours=4))
    seed(db, 30 - right, "corrected", ago=timedelta(hours=3))
    with SessionLocal.begin() as s:
        reason = graduation.check_brake(s, NOW)
    if braked:
        assert reason == "accuracy 87% on the last 30 decided AI results" and cfg()["mode"] == "shadow"
        assert "🧠 AI switched back to SHADOW: accuracy 87% on the last 30 decided AI results" in client.get("/").text
    else:
        assert reason is None and cfg()["mode"] == "auto"


def test_g3_errors_on_last_20_calls_brake(grad, shop, db):
    settings(mode="auto", auto_graduate=True, shadow_since=NOW - timedelta(days=20), auto_since=NOW - timedelta(days=5))
    seed(db, 10, "auto", ago=timedelta(hours=2))
    seed(db, 10, "error", ago=timedelta(hours=1))
    with SessionLocal.begin() as s:
        assert graduation.check_brake(s, NOW) == "50% of the last 20 AI calls failed"
    assert cfg()["mode"] == "shadow"


def test_g3_brake_runs_after_the_ai_step(grad, shop, db):
    from app.ai.providers import AIError
    from tests.test_cart import say

    settings(mode="auto", auto_graduate=True, shadow_since=NOW - timedelta(days=20), auto_since=NOW - timedelta(days=5))
    seed(db, 10, "auto", ago=timedelta(hours=2))
    seed(db, 9, "error", ago=timedelta(hours=1))
    grad.answer = AIError("server")
    say(db, 1, HAWAS)
    assert service.run_once().get("brake") == 1 and cfg()["mode"] == "shadow"


# ---------- G4 manual switch ----------

def test_g4_manual_switch_turns_auto_graduate_off(grad, shop, db):
    client, token = shop
    ready_shop(db)
    r = client.post("/ai/mode", data={"csrf": token, "mode": "shadow"}, follow_redirects=True)
    assert "Auto-graduation is OFF now" in r.text
    assert cfg()["auto_graduate"] is False
    settings(shadow_since=NOW - timedelta(days=8))  # all numbers good again: only the switch blocks it
    assert tick() == [] and cfg()["mode"] == "shadow"  # the owner decides now
    # the owner turns it on again in the settings (window restarted at the manual switch)
    client.post("/ai/settings", data={"csrf": token, "daily_cap": "300", "monthly_budget_usd": "5",
                                      "threshold": "0.85", "model": "gpt-6-luna", "reasoning": "low",
                                      "auto_graduate": "1", "min_days": "7", "min_decisions": "50",
                                      "min_accuracy": "95"})
    assert cfg()["auto_graduate"] is True
    settings(shadow_since=NOW - timedelta(days=8))
    assert tick(NOW + timedelta(days=1))[0].startswith("🧠 AI switched to AUTO")
    client.post("/ai/mode", data={"csrf": token, "mode": "auto"})
    assert cfg()["mode"] == "auto" and cfg()["auto_graduate"] is False
    assert audit(db, "ai.mode")[-1]["after"] == {"mode": "auto", "auto_graduate": False}


# ---------- G5 weekly summary ----------

SECRETS = ("Daw Secret Name", "secretperfume", "secretnick", "09777123456", "777123456", "ရန်ကင်း သုခလမ်း")


def test_g5_weekly_summary_is_aggregate_only_and_for_the_right_week(grad, shop, db, tmp_path, monkeypatch):
    monkeypatch.setattr(graduation, "BASE_DIR", tmp_path)
    published = []
    monday = datetime(2026, 10, 19, 9, 30, tzinfo=YANGON).astimezone(UTC)
    in_week = datetime(2026, 10, 14, 12, 0, tzinfo=YANGON)
    # customer data that must never appear: a name, a phone, an address, message texts, AI result texts
    add(5001, "secretperfume 10ml ယူမယ် 09777123456 ရန်ကင်း သုခလမ်း", customer="55", when=in_week)
    with db.begin() as c:
        c.execute(text("UPDATE customers SET display_name = 'Daw Secret Name', username = 'dawsecret' "
                       "WHERE external_user_id = '55'"))
        c.execute(text(
            "INSERT INTO ai_calls (message_id, model, mode, ok, decision, decided_at, created_at, cost_usd, "
            "latency_ms, result_json) SELECT id, 'gpt-6-luna', 'shadow', true, 'corrected', :t, :t, 0.0002, 2000, "
            "CAST(:j AS jsonb) FROM messages WHERE external_message_id = '5001'"),
            {"t": in_week, "j": '{"reason": "secretperfume not in list, phone 09777123456", '
                                 '"items": [{"not_in_list": "secretperfume"}]}'})
        c.execute(text("INSERT INTO learned_patterns (kind, text, normalized_text, status, via_ai) "
                       "VALUES ('not_stocked', 'secretnick', 'secretnick', 'pending', true)"))
    seed(db, 3, "accepted", at=in_week, tag="w")
    seed(db, 1, "error", at=in_week, tag="we")
    seed(db, 5, "accepted", at=datetime(2026, 10, 11, 12, 0, tzinfo=YANGON), tag="before")  # week before
    seed(db, 7, "accepted", at=datetime(2026, 10, 19, 8, 0, tzinfo=YANGON), tag="after")  # this week
    settings(mode="shadow", auto_graduate=True, shadow_since=in_week - timedelta(days=2))
    with SessionLocal.begin() as s:
        graduation._save_state(s, {"last_weekly": "2026-10-05", "last_daily": "2026-10-19"})
    graduation._seen.clear()
    done = graduation.tick(monday, publish_fn=lambda repo, rel: published.append((repo, rel)) or "pushed")
    assert done == ["weekly summary 2026-10-12: pushed"]
    assert published == [(tmp_path, graduation.SUMMARY)]
    body = (tmp_path / "reports" / "ai-weekly.md").read_text(encoding="utf-8")
    assert "Week: 2026-W42 (2026-10-12 to 2026-10-18, Asia/Yangon)" in body
    assert "| AI calls | 5 |" in body  # 1 + 3 + 1 error; not the week before / after
    assert "| Accepted unchanged | 3 |" in body and "| Corrected | 1 |" in body and "| Accuracy | 75% |" in body
    assert "| Errors / refused by the checker | 1 / 0 |" in body and "| Cost (USD) | 0.0002 |" in body
    assert "approved / pending (total) | 0 / 1 |" in body
    for secret in SECRETS + ("dawsecret", "seed", "Seed"):
        assert secret not in body, secret
    assert not re.search(r"(?:\+?95|0)9[\d\s-]{7,}", body)  # no phone numbers at all
    assert not re.search(r"[က-႟]", body)  # no Burmese text (= no message text)
    # same week again: not rewritten; next Monday before 09:00: still the old week
    graduation._seen.clear()
    assert graduation.tick(monday + timedelta(days=1), publish_fn=lambda *a: "x") == []
    graduation._seen.clear()
    assert graduation.tick(monday + timedelta(days=7, minutes=-31), publish_fn=lambda *a: "x") == []
    graduation._seen.clear()
    assert graduation.tick(monday + timedelta(days=7), publish_fn=lambda *a: "pushed") == \
        ["weekly summary 2026-10-19: pushed"]


def test_g5_first_run_writes_nothing_for_the_past(grad, shop, db, tmp_path, monkeypatch):
    monkeypatch.setattr(graduation, "BASE_DIR", tmp_path)
    assert not any("weekly" in x for x in tick())
    assert not (tmp_path / "reports").exists()


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def test_g5_publish_commits_only_the_summary(tmp_path):
    remote, repo = tmp_path / "remote.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    for k, v in (("user.name", "test"), ("user.email", "t@example.com")):
        git(repo, "config", k, v)
    git(repo, "checkout", "-q", "-b", "main")
    (repo / "app.py").write_text("v1")
    git(repo, "add", "app.py")
    git(repo, "commit", "-q", "-m", "start")
    git(repo, "push", "-q", "-u", "origin", "main")
    (repo / "reports").mkdir()
    (repo / "reports" / "ai-weekly.md").write_text("# AI weekly summary\n")
    (repo / "app.py").write_text("work in progress")
    git(repo, "add", "app.py")  # someone's staged work must stay out of the commit
    assert graduation.publish(repo, graduation.SUMMARY) == "pushed"
    assert git(remote, "log", "-1", "--format=%s") == "AI weekly summary\n"
    assert git(remote, "show", "--name-only", "--format=", "HEAD").split() == ["reports/ai-weekly.md"]
    assert "app.py" in git(repo, "diff", "--cached", "--name-only")  # still staged, not committed
    assert graduation.publish(repo, graduation.SUMMARY) == "unchanged"
    # local work not pushed yet: never pushed along with the summary
    git(repo, "commit", "-q", "-m", "local work")
    (repo / "reports" / "ai-weekly.md").write_text("# AI weekly summary\nnew week\n")
    assert graduation.publish(repo, graduation.SUMMARY).startswith("skipped")
    assert git(remote, "log", "-1", "--format=%s") == "AI weekly summary\n"
    # push failure: logged, no exception
    git(repo, "push", "-q")
    git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    assert graduation.publish(repo, graduation.SUMMARY).startswith("push failed")
