"""Integration tests verifying the VideoProvider boundary, recording, and fault mapping."""

from __future__ import annotations

import pytest

from focuslist.config import Settings
from focuslist.errors import ErrorCode, FocusListError, QuotaExhaustedError
from focuslist.platform import FaultInjectionProvider, FixtureVideoProvider, create_provider


def test_fixture_provider_data_loading_and_determinism(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """Verify FixtureVideoProvider loads synthetic dataset deterministically with call recording."""
    videos_1 = fixture_provider.get_video_details(["syn_vid_0001", "syn_vid_0002"])
    videos_2 = fixture_provider.get_video_details(["syn_vid_0001", "syn_vid_0002"])
    assert videos_1 == videos_2
    assert len(videos_1) == 2
    assert videos_1[0].video_id == "syn_vid_0001"
    assert "Recursion" in videos_1[0].title
    assert fixture_provider.call_counts["get_video_details"] == 2
    assert fixture_provider.requests == 2
    assert fixture_provider.network_attempts == 2
    assert fixture_provider.writes == 0
    assert len(fixture_provider.call_log) == 2


def test_fixture_provider_search_deterministic_order(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """Verify search_candidates returns deterministic ordering and records attempts."""
    results_1 = fixture_provider.search_candidates("recursion", max_results=10)
    results_2 = fixture_provider.search_candidates("recursion", max_results=10)
    assert [v.video_id for v in results_1] == [v.video_id for v in results_2]
    assert len(results_1) >= 1
    assert any("recursion" in v.title.lower() for v in results_1)
    assert fixture_provider.call_counts["search_candidates"] == 2
    assert fixture_provider.writes == 0


def test_fixture_provider_playlist_lifecycle_and_write_counts(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """Verify playlist creation, item insertion, deletion, and separate write counter."""
    fixture_provider.reset_counters()

    pid = fixture_provider.create_playlist("Test Playlist", "Description", privacy="private")
    assert pid.startswith("PL_syn_")

    item_id = fixture_provider.insert_playlist_item(pid, "syn_vid_0001")
    assert item_id.startswith("PLI_syn_")

    playlists = fixture_provider.get_user_playlists("acc_1")
    assert any(p["playlist_id"] == pid and p["item_count"] == 1 for p in playlists)

    deleted = fixture_provider.delete_playlist(pid)
    assert deleted is True
    assert fixture_provider.delete_playlist(pid) is False

    # 1 read (get_user_playlists) + 4 writes (create, insert, 2x delete)
    assert fixture_provider.requests == 5
    assert fixture_provider.writes == 4


def test_fault_injection_provider(fixture_provider: FixtureVideoProvider) -> None:
    """Verify FaultInjectionProvider raises configured errors deterministically."""
    fault_provider = FaultInjectionProvider(target_provider=fixture_provider)
    fault_provider.inject_fault("search_candidates", QuotaExhaustedError("Daily quota exhausted."))

    with pytest.raises(QuotaExhaustedError):
        fault_provider.search_candidates("test")

    # Fault count was 1, next call should succeed against target provider
    results = fault_provider.search_candidates("recursion")
    assert len(results) >= 1
    assert fault_provider.requests == 2
    assert fault_provider.faulted_calls == 1
    assert fault_provider.writes == 0


@pytest.mark.parametrize(
    ("fault_kind", "expected_code", "expected_retryable"),
    [
        ("quota", ErrorCode.QUOTA_EXHAUSTED, False),
        ("quota_budget", ErrorCode.QUOTA_BUDGET_EXCEEDED, False),
        ("rate", ErrorCode.RATE_LIMITED, True),
        ("unavailable", ErrorCode.VIDEO_UNAVAILABLE, False),
        ("channel_unavailable", ErrorCode.CHANNEL_UNAVAILABLE, False),
        ("timeout", ErrorCode.NETWORK_TIMEOUT, True),
        ("no_channel", ErrorCode.NO_YOUTUBE_CHANNEL, False),
        ("auth_required", ErrorCode.AUTH_REQUIRED, False),
        ("auth_expired", ErrorCode.AUTH_EXPIRED, False),
        ("auth_cancelled", ErrorCode.AUTH_CANCELLED, False),
        ("upstream_500", ErrorCode.UPSTREAM_FAILURE, True),
        ("upstream_503", ErrorCode.UPSTREAM_UNAVAILABLE, True),
    ],
)
def test_fault_injection_normalized_categories(
    fixture_provider: FixtureVideoProvider,
    fault_kind: str,
    expected_code: ErrorCode,
    expected_retryable: bool,
) -> None:
    """Verify all SRS fault categories map cleanly to ErrorCode and retryability."""
    fixture_provider.reset_counters()
    fault_provider = FaultInjectionProvider(target_provider=fixture_provider)
    fault_provider.inject_normalized_fault("create_playlist", fault_kind, count=1)

    with pytest.raises(FocusListError) as exc_info:
        fault_provider.create_playlist("Fault Test", "Desc")

    assert exc_info.value.code == expected_code
    assert exc_info.value.retryable is expected_retryable
    assert fault_provider.writes == 0
    assert fixture_provider.writes == 0
    assert fault_provider.faulted_calls == 1


def test_fault_injection_preflight_vs_network_attempts(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """Verify preflight faults count as requests without counting as outbound network attempts."""
    fault_provider = FaultInjectionProvider(target_provider=fixture_provider)
    fault_provider.inject_normalized_fault("search_candidates", "auth_required", count=1)

    with pytest.raises(FocusListError) as exc_info:
        fault_provider.search_candidates("recursion")

    assert exc_info.value.code == ErrorCode.AUTH_REQUIRED
    assert fault_provider.requests == 1
    assert fault_provider.network_attempts == 0
    assert fixture_provider.network_attempts == 0


def test_create_provider_factory() -> None:
    """Verify create_provider factory respects settings mode."""
    cfg = Settings(provider="fixture")
    p = create_provider(settings=cfg)
    assert isinstance(p, FixtureVideoProvider)

    cfg_fault = Settings(provider="fault")
    pf = create_provider(settings=cfg_fault)
    assert isinstance(pf, FaultInjectionProvider)
