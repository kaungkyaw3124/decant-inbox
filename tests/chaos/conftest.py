"""Fixtures of the chaos / stress tests (docs/SPEC-v5.9). Scratch database + fake Telegram only."""
import pytest

from tests.chaos.harness import open_shop


@pytest.fixture
def chaos(db, monkeypatch):
    env = open_shop(monkeypatch)
    try:
        yield env
    finally:
        env.close()
