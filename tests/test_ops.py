"""Phase 5: heartbeats, health checks, backup retention."""
import os
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from app.core.heartbeat import beat
from scripts.backup_db import list_backups, prune, run_backup


def test_prune_keeps_newest(tmp_path):
    now = time.time()
    for day in range(20):
        f = tmp_path / f"product_requests_2026-10-{day + 1:02d}T0300Z.dump"
        f.write_bytes(b"x")
        os.utime(f, (now - (20 - day) * 86400, now - (20 - day) * 86400))
    (tmp_path / "product_requests_crashed.dump.partial").write_bytes(b"x")
    (tmp_path / "unrelated.txt").write_bytes(b"x")
    assert prune(14, tmp_path) == 6
    kept = list_backups(tmp_path)
    assert len(kept) == 14 and kept[0].name.startswith("product_requests_2026-10-20")
    assert not list(tmp_path.glob("*.partial")) and (tmp_path / "unrelated.txt").exists()


@pytest.mark.skipif(shutil.which("pg_dump") is None, reason="postgresql-client not installed")
def test_real_backup_of_test_db(db, tmp_path):
    path = run_backup(keep=2, backup_dir=tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert oct(tmp_path.stat().st_mode)[-3:] == "700" and oct(path.stat().st_mode)[-3:] == "600"


@pytest.fixture
def web(db, monkeypatch, tmp_path):
    from app.web import health
    from app.web.main import app

    monkeypatch.setattr(health, "list_backups", lambda: list_backups(tmp_path))
    return TestClient(app, base_url="https://testserver"), tmp_path


def test_healthz_reports_each_part(web):
    client, backups = web
    r = client.get("/healthz")
    assert r.status_code == 503
    assert "database: ok" in r.text and "listener: FAIL" in r.text and "backup: FAIL" in r.text

    beat("listener", "connected")
    beat("parser", "rules-1")
    (backups / "product_requests_2026-10-11T0300Z.dump").write_bytes(b"x")
    r = client.get("/healthz")
    assert r.status_code == 200, r.text
    assert set(r.text.split()) >= {"listener:", "parser:", "backup:", "ok"}


def test_health_page_needs_login(web):
    client, _ = web
    assert client.get("/health", follow_redirects=False).status_code == 303
