"""Pytest shared test fixtures for FocusList."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from focuslist.clock import FakeClock
from focuslist.config import Settings
from focuslist.context import RequestContext
from focuslist.platform.fixture_provider import FixtureVideoProvider


@pytest.fixture(autouse=True)
def _isolate_storage_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate SQLite DB and credential storage per test so repo root stays clean."""
    monkeypatch.setenv("FOCUSLIST_DB_PATH", str(tmp_path / "isolated_focuslist.db"))
    monkeypatch.setenv("FOCUSLIST_AUTH_STORE_DIR", str(tmp_path / "isolated_auth"))
    from focuslist.config import get_settings

    get_settings(reset=True)


@pytest.fixture
def fake_clock() -> FakeClock:
    """Fixture providing a deterministic clock anchored at 2026-11-23 12:00:00 UTC."""
    return FakeClock(datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC))


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Fixture providing isolated test settings in fixture mode."""
    return Settings(
        provider="fixture",
        db_path=tmp_path / "test_focuslist.db",
        fixture_dir=Path("tests/fixtures"),
        daily_general_quota=10000,
        daily_search_quota=100,
        quota_safety_margin=0.05,
        request_unit_cap=2600,
        request_timeout_seconds=15.0,
        max_retries=3,
    )


@pytest.fixture
def fixture_provider() -> FixtureVideoProvider:
    """Fixture providing an offline fixture provider loaded from synthetic test data."""
    return FixtureVideoProvider(fixture_dir=Path("tests/fixtures"))


@pytest.fixture
def request_context(test_settings: Settings, fake_clock: FakeClock) -> RequestContext:
    """Fixture providing a populated RequestContext."""
    return RequestContext(
        settings=test_settings,
        clock=fake_clock,
        account_id="test_account_001",
        request_id="req_test_001",
    )
