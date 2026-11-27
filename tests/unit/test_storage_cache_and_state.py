"""Unit and integration tests for Workstream 1: SQLite cache, migrations, and state (C16)."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from focuslist.clock import FakeClock
from focuslist.errors import (
    ConfirmationExpiredError,
    ConfirmationInvalidError,
    InvalidArgumentsError,
)
from focuslist.platform.storage import (
    MAX_CACHE_TTL_SECONDS,
    TTL_CATEGORY_SECONDS,
    TTL_CHANNEL_SECONDS,
    TTL_USER_SECONDS,
    TTL_VIDEO_SECONDS,
    FocusListStorage,
)


def test_migrations_from_empty_db_and_repeat_run_are_idempotent(tmp_path: Path) -> None:
    """Running migrations twice on the same DB is safe and enables WAL + foreign keys."""
    db_path = tmp_path / "focuslist.db"
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))

    storage = FocusListStorage(db_path, clock=clock)
    assert storage.schema_version() == 1
    assert storage.journal_mode() == "wal"
    assert storage.foreign_keys_enabled() is True

    # Repeat migration call on the exact same DB
    applied_again = storage.run_migrations()
    assert applied_again == []
    assert storage.schema_version() == 1

    # Second storage instance opening existing DB also runs repeat migrations safely
    storage_reopen = FocusListStorage(db_path, clock=clock)
    assert storage_reopen.schema_version() == 1


def test_cache_ttl_buckets_max_cap_and_invalid_values(tmp_path: Path) -> None:
    """Verify 24h video/channel, 6h user, 7d category TTLs, 30d hard cap, and validation."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    storage = FocusListStorage(tmp_path / "cache.db", clock=clock)

    storage.set_cache("get_video_details", {"id": "v1"}, "video", {"title": "V1"})
    storage.set_cache("get_channel_details", {"id": "c1"}, "channel", {"title": "C1"})
    storage.set_cache("get_user_likes", {"p": 1}, "user", {"items": ["v1"]}, account_id="acc_a")
    storage.set_cache("get_categories", {"region": "US"}, "category", [{"id": "27"}])

    # Invalid TTLs (>30 days, <=0, bool) and invalid account scoping rejected
    with pytest.raises(InvalidArgumentsError):
        storage.set_cache("get_video_details", {"id": "v2"}, "video", {}, ttl_seconds=MAX_CACHE_TTL_SECONDS + 1)
    with pytest.raises(InvalidArgumentsError):
        storage.set_cache("get_video_details", {"id": "v2"}, "video", {}, ttl_seconds=0)
    with pytest.raises(InvalidArgumentsError):
        storage.set_cache("get_user_likes", {}, "user", {}, account_id="")
    with pytest.raises(InvalidArgumentsError):
        storage.set_cache("get_video_details", {}, "video", {}, account_id="acc_a")

    # Advance 6 hours -> user cache expires, video/channel/category remain valid
    clock.advance(TTL_USER_SECONDS)
    assert storage.get_cache("get_user_likes", {"p": 1}, account_id="acc_a") is None
    assert storage.get_cache("get_video_details", {"id": "v1"}) == {"title": "V1"}
    assert storage.get_cache("get_channel_details", {"id": "c1"}) == {"title": "C1"}
    assert storage.get_cache("get_categories", {"region": "US"}) == [{"id": "27"}]

    # Advance remaining 18 hours (total 24h) -> video & channel expire, category stays
    clock.advance(TTL_VIDEO_SECONDS - TTL_USER_SECONDS)
    assert storage.get_cache("get_video_details", {"id": "v1"}) is None
    assert storage.get_cache("get_channel_details", {"id": "c1"}) is None
    assert storage.get_cache("get_categories", {"region": "US"}) == [{"id": "27"}]

    # Advance to 7 days -> category expires
    clock.advance(TTL_CATEGORY_SECONDS - TTL_CHANNEL_SECONDS)
    assert storage.get_cache("get_categories", {"region": "US"}) is None


def test_account_scoped_separation_and_purge(tmp_path: Path) -> None:
    """Purging one account deletes its user/derived cache without touching public or other accounts."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    storage = FocusListStorage(tmp_path / "purge.db", clock=clock)

    storage.set_cache("get_video_details", {"id": "pub1"}, "video", {"title": "Public"})
    storage.set_cache("get_user_likes", {}, "user", ["v1"], account_id="acc_alpha")
    storage.set_cache("profile", {}, "derived_profile", {"topics": ["algo"]}, account_id="acc_alpha")
    storage.set_cache("get_user_likes", {}, "user", ["v2"], account_id="acc_beta")

    # Account isolation on reads
    assert storage.get_cache("get_user_likes", {}, account_id="acc_alpha") == ["v1"]
    assert storage.get_cache("get_user_likes", {}, account_id="acc_beta") == ["v2"]

    counts = storage.purge_account_data("acc_alpha")
    assert counts["cache_entries"] == 2
    assert storage.get_cache("get_user_likes", {}, account_id="acc_alpha") is None
    assert storage.get_cache("profile", {}, account_id="acc_alpha") is None
    # Account beta and public cache stay intact
    assert storage.get_cache("get_user_likes", {}, account_id="acc_beta") == ["v2"]
    assert storage.get_cache("get_video_details", {"id": "pub1"}) == {"title": "Public"}


def test_proposal_retention_and_action_history_immutability(tmp_path: Path) -> None:
    """Verify proposal expiry+7d retention, append-only action history, and 30-day cleanup."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    storage = FocusListStorage(tmp_path / "retention.db", clock=clock)

    expires_at = clock.now() + timedelta(minutes=30)
    storage.save_proposal(
        proposal_id="prop_ret_1",
        action_kind="create",
        owner_account_id="acc_1",
        title="Algorithms",
        privacy_status="private",
        ordered_video_ids=["v1", "v2"],
        canonical_payload={"proposal_id": "prop_ret_1"},
        canonical_hash="hash_1",
        expires_at=expires_at,
    )
    row_id = storage.append_action_history(
        proposal_id="prop_ret_1",
        proposal_hash="hash_1",
        action_kind="create",
        account_id="acc_1",
        target_playlist_id="PL_001",
        inserted_count=2,
        outcome="created",
    )
    assert row_id >= 1
    assert storage.is_playlist_undo_eligible("PL_001", "acc_1") is True

    # Verify append-only trigger forbids SQL UPDATE on action_history
    raw_conn = sqlite3.connect(storage.db_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw_conn.execute("UPDATE action_history SET outcome = 'tampered' WHERE id = ?", (row_id,))
    finally:
        raw_conn.close()

    # Advance 31 minutes -> proposal expired for claim, but still retained until +7d
    clock.advance(timedelta(minutes=31))
    with pytest.raises(ConfirmationExpiredError):
        storage.claim_proposal(
            "prop_ret_1",
            owner_account_id="acc_1",
            expected_action_kind="create",
            expected_hash="hash_1",
        )
    assert storage.get_proposal("prop_ret_1") is not None

    # Advance +7 days -> proposal purged, action_history still retained for 30 days
    clock.advance(timedelta(days=7))
    cleaned = storage.cleanup_expired()
    assert cleaned["proposals"] == 1
    assert storage.get_proposal("prop_ret_1") is None
    assert len(storage.list_action_history(account_id="acc_1")) == 1

    # Advance past 30 days -> action_history purged
    clock.advance(timedelta(days=24))
    cleaned_30 = storage.cleanup_expired()
    assert cleaned_30["action_history"] == 1
    assert storage.list_action_history(account_id="acc_1") == []


def test_concurrent_proposal_claims_allow_only_one_winner(tmp_path: Path) -> None:
    """Concurrent claims against the same proposal must permit strictly one winner."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    db_path = tmp_path / "concurrent.db"
    storage = FocusListStorage(db_path, clock=clock)
    storage.save_proposal(
        proposal_id="prop_race_1",
        action_kind="create",
        owner_account_id="acc_1",
        title="Concurrency",
        privacy_status="private",
        ordered_video_ids=["v1"],
        canonical_payload={"proposal_id": "prop_race_1"},
        canonical_hash="hash_race",
        expires_at=clock.now() + timedelta(minutes=30),
    )

    def _try_claim(_: int) -> str:
        worker_storage = FocusListStorage(db_path, clock=clock, auto_migrate=False, run_startup_cleanup=False)
        try:
            res = worker_storage.claim_proposal(
                "prop_race_1",
                owner_account_id="acc_1",
                expected_action_kind="create",
                expected_hash="hash_race",
            )
            return res.status
        except ConfirmationInvalidError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(_try_claim, range(6)))

    assert outcomes.count("claimed") == 1
    assert outcomes.count("rejected") == 5
    final = storage.get_proposal("prop_race_1")
    assert final is not None and final.state == "confirmed"
