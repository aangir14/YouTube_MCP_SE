"""Integration tests verifying the VideoProvider boundary and implementations."""

from focuslist.config import Settings
from focuslist.errors import QuotaExhaustedError
from focuslist.platform import FaultInjectionProvider, FixtureVideoProvider, create_provider


def test_fixture_provider_data_loading(fixture_provider: FixtureVideoProvider) -> None:
    """Verify FixtureVideoProvider loads synthetic dataset without external network calls."""
    videos = fixture_provider.get_video_details(["syn_vid_0001", "syn_vid_0002"])
    assert len(videos) == 2
    assert videos[0].video_id == "syn_vid_0001"
    assert "Recursion" in videos[0].title
    assert fixture_provider.call_counts["get_video_details"] == 1


def test_fixture_provider_search(fixture_provider: FixtureVideoProvider) -> None:
    """Verify search_candidates searches synthetic videos."""
    results = fixture_provider.search_candidates("recursion", max_results=10)
    assert len(results) >= 1
    assert any("recursion" in v.title.lower() for v in results)
    assert fixture_provider.call_counts["search_candidates"] == 1


def test_fixture_provider_playlist_lifecycle(fixture_provider: FixtureVideoProvider) -> None:
    """Verify playlist creation, item insertion, and deletion in fixture provider."""
    pid = fixture_provider.create_playlist("Test Playlist", "Description", privacy="private")
    assert pid.startswith("PL_syn_")

    item_id = fixture_provider.insert_playlist_item(pid, "syn_vid_0001")
    assert item_id.startswith("PLI_syn_")

    deleted = fixture_provider.delete_playlist(pid)
    assert deleted is True

    # Deleting already deleted playlist returns False
    assert fixture_provider.delete_playlist(pid) is False


def test_fault_injection_provider(fixture_provider: FixtureVideoProvider) -> None:
    """Verify FaultInjectionProvider raises configured errors deterministically."""
    fault_provider = FaultInjectionProvider(target_provider=fixture_provider)

    # Inject quota exhausted on search
    fault_provider.inject_fault("search_candidates", QuotaExhaustedError("Daily quota exhausted."))

    import pytest

    with pytest.raises(QuotaExhaustedError):
        fault_provider.search_candidates("test")

    # Fault count was 1, next call should succeed against target provider
    results = fault_provider.search_candidates("recursion")
    assert len(results) >= 1


def test_create_provider_factory() -> None:
    """Verify create_provider factory respects settings mode."""
    cfg = Settings(provider="fixture")
    p = create_provider(settings=cfg)
    assert isinstance(p, FixtureVideoProvider)

    cfg_fault = Settings(provider="fault")
    pf = create_provider(settings=cfg_fault)
    assert isinstance(pf, FaultInjectionProvider)
