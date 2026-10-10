"""Worker + reparse_all against the test database."""
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.db import SessionLocal
from app.listener.save import IncomingMessage, save_message
from app.parser import rules
from app.parser.worker import run_batch
from scripts.reparse_all import reparse_all
from scripts.seed_catalog import seed
from tests.test_seed_catalog import write_csvs

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def add_message(msg_id: int, body: str) -> None:
    with SessionLocal.begin() as s:
        save_message(s, IncomingMessage("42", str(msg_id), "42", None, "Ko", body, NOW))


def results(engine) -> list[tuple]:
    with engine.connect() as c:
        return list(c.execute(text(
            "SELECT r.message_id, r.intent, p.name, r.size_ml, r.method, r.parser_version, r.is_current "
            "FROM parse_results r LEFT JOIN products p ON p.id = r.product_id ORDER BY r.id"
        )))


def test_worker_parses_new_messages_once(db, tmp_path):
    seed(write_csvs(tmp_path))
    add_message(1, "stw intensely ၅ ml ဝယ်ချင်လို့ပါ")
    add_message(2, "5ml stronger with you intensely ရှိလား")
    assert run_batch() == 2
    assert run_batch() == 0  # nothing left
    assert [r[:4] for r in results(db)] == [
        (1, "buy", "Stronger With You Intensely", 5),
        (2, "ask_stock", "Stronger With You Intensely", 5),
    ]
    assert all(r[4:] == ("rules", rules.PARSER_VERSION, True) for r in results(db))


def test_reparse_keeps_history_and_only_adds_changes(db, tmp_path, monkeypatch):
    seed(write_csvs(tmp_path))
    add_message(1, "stw intensely ၅ ml ဝယ်ချင်လို့ပါ")
    add_message(2, "aventus 10ml ရှိလား")  # not in the catalog yet
    run_batch()
    assert reparse_all()["unchanged"] == 2

    with db.begin() as c:  # owner adds an alias in the dashboard
        c.execute(text(
            "INSERT INTO product_aliases (product_id, alias_text, normalized_alias, source) "
            "SELECT id, 'aventus', 'aventus', 'learned' FROM products WHERE brand = 'Dior'"
        ))
    stats = reparse_all()
    assert (stats["changed"], stats["unchanged"]) == (1, 1)
    rows = [r for r in results(db) if r[0] == 2]
    assert [(r[2], r[6]) for r in rows] == [(None, False), ("Sauvage Eau de Parfum", True)]

    monkeypatch.setattr("app.parser.service.PARSER_VERSION", "rules-test")
    assert reparse_all()["changed"] == 2  # new version -> new rows, old ones kept
    assert len(results(db)) == 5


def test_reparse_never_replaces_human_result(db, tmp_path):
    seed(write_csvs(tmp_path))
    add_message(1, "stw intensely 5ml")
    run_batch()
    with db.begin() as c:
        c.execute(text("UPDATE parse_results SET is_current = false"))
        c.execute(text(
            "INSERT INTO parse_results (message_id, intent, size_ml, confidence, method, parser_version, is_current) "
            "VALUES (1, 'buy', 5, 1.0, 'human', 'human', true)"
        ))
    assert reparse_all()["human"] == 1
    assert [r[4] for r in results(db) if r[6]] == ["human"]


def test_reparse_dry_run_writes_nothing(db, tmp_path):
    seed(write_csvs(tmp_path))
    add_message(1, "stw intensely 5ml ရှိလား")
    assert reparse_all(dry_run=True)["new"] == 1
    assert results(db) == []
