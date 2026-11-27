"""Unit and integration tests for C17: FR-2 similar_channels, FR-3 recommend_videos, FR-4 analyse_engagement."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from focuslist.clock import FakeClock
from focuslist.config import Settings
from focuslist.context import RequestContext
from focuslist.discovery.channels import CHANNEL_WEIGHTS, ChannelDiscovery
from focuslist.discovery.engagement import PUBLICATION_FALLBACK_WARNING, EngagementService
from focuslist.discovery.recommendations import (
    RECOMMENDATION_WEIGHTS,
    WATCH_HISTORY_DISCLOSURE,
    RecommendationService,
)
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.storage import FocusListStorage


def _vid(n: int) -> str:
    return f"c17v{n:07d}"


def _cid(n: int) -> str:
    return f"UC{'c' * 15}{n:07d}"


def _video_dict(n: int, **overrides: Any) -> dict[str, Any]:
    return {
        "video_id": _vid(n),
        "canonical_url": f"https://www.youtube.com/watch?v={_vid(n)}",
        "title": f"Algorithms Lesson {n}",
        "channel_id": _cid(1),
        "channel_title": "Channel One",
        "description": "Dynamic programming and graph algorithms walkthrough.",
        "published_at": "2026-10-15T12:00:00Z",
        "duration_seconds": 600,
        "duration_iso": "PT10M",
        "tags": ["algorithms", "python"],
        "category_id": "28",
        "language": "en",
        "visibility": "public",
        "is_live": False,
        "is_upcoming": False,
        "is_age_restricted": False,
        "untrusted": True,
        **overrides,
    }


def _channel_dict(n: int, **overrides: Any) -> dict[str, Any]:
    return {
        "channel_id": _cid(n),
        "canonical_url": f"https://www.youtube.com/channel/{_cid(n)}",
        "title": f"Algo Channel {n}",
        "handle": f"@algo_chan_{n}",
        "description": "Computer science and algorithms tutorials.",
        "keywords": ["algorithms", "cs"],
        "language": "en",
        "topic_categories": ["https://en.wikipedia.org/wiki/Computer_science"],
        "subscriber_count": 50_000,
        "video_count": 50,
        "hidden_subscriber_count": False,
        "untrusted": True,
        **overrides,
    }


def _setup_gateway(
    tmp_path: Path,
    *,
    now: datetime | None = None,
    account_id: str | None = "learner_a",
    has_read_consent: bool | None = True,
) -> tuple[FixtureVideoProvider, ProviderGateway, FocusListStorage, RequestContext]:
    clock = FakeClock(now or datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC))
    settings = Settings(provider="fixture", db_path=tmp_path / "focuslist.db")
    storage = FocusListStorage(settings.db_path, clock=clock)
    raw = FixtureVideoProvider(tmp_path)
    gateway = ProviderGateway(raw, storage=storage, settings=settings, clock=clock)
    ctx = RequestContext(
        settings=settings,
        clock=clock,
        account_id=account_id,
        has_read_consent=has_read_consent,
    )
    return raw, gateway, storage, ctx


def test_fr2_similar_channels_two_pass_hidden_counts_and_legacy_url(tmp_path: Path) -> None:
    channels = [
        _channel_dict(0, title="Seed CS Academy", handle="@seed_cs"),
        _channel_dict(1, title="Seed CS Algorithms", subscriber_count=48_000),
        _channel_dict(
            2,
            title="Hidden Subs Channel",
            subscriber_count=0,
            hidden_subscriber_count=True,
            keywords=None,
            language=None,
        ),
        _channel_dict(3, title="Ineligible Empty Channel", video_count=0, recent_upload_ids=[]),
    ]
    videos = [
        _video_dict(0, channel_id=_cid(0), title="Seed Graph Theory"),
        _video_dict(1, channel_id=_cid(1), title="Graph Theory Deep Dive"),
        _video_dict(2, channel_id=_cid(2), title="Graph Theory Basics", language="en"),
    ]
    (tmp_path / "sample_channels.json").write_text(json.dumps(channels), encoding="utf-8")
    (tmp_path / "sample_videos.json").write_text(json.dumps(videos), encoding="utf-8")

    raw, gateway, _, ctx = _setup_gateway(tmp_path)
    svc = ChannelDiscovery(gateway, ctx)

    # Negative inputs: legacy /c/ URL and invalid limit make 0 provider calls
    legacy_resp = svc.tool_response(lambda: svc.similar("https://www.youtube.com/c/oldname"))
    assert legacy_resp["error"]["code"] == "INVALID_CHANNEL_ID"
    assert "/c/" in legacy_resp["error"]["message"]
    assert raw.requests == 0

    bad_limit = svc.tool_response(lambda: svc.similar("@seed_cs", limit=26))
    assert bad_limit["error"]["code"] == "INVALID_ARGUMENTS"
    assert raw.requests == 0

    # Happy path via @handle
    resp = svc.tool_response(lambda: svc.similar("@seed_cs", limit=10))
    assert "result" in resp
    res = resp["result"]
    assert res["seed"] == _cid(0)
    returned_ids = [c["channel_id"] for c in res["channels"]]
    assert _cid(0) not in returned_ids
    assert _cid(3) not in returned_ids
    assert set(returned_ids) == {_cid(1), _cid(2)}

    hidden_row = next(c for c in res["channels"] if c["channel_id"] == _cid(2))
    assert hidden_row["hidden_subscriber_count"] is True
    assert hidden_row["subscriber_count"] is None
    assert "subscriber_count" in hidden_row["missing_fields"]
    assert "keywords" in hidden_row["missing_fields"]
    assert hidden_row["language_provenance"] == "public_uploads"
    assert hidden_row["language"] == "en"

    for item in res["channels"]:
        assert item["components"] == CHANNEL_WEIGHTS
        assert abs(sum(f["contribution"] for f in item["feature_trace"].values()) - item["score"]) <= 1e-6
        assert len(item["reason"]) <= 200
        assert item["untrusted_metadata"] is True

    assert raw.writes == 0
    assert resp["meta"]["quota_used"] <= 25
    assert resp["meta"]["search_calls"] <= 3


def test_fr3_recommendations_consent_empty_profile_exclusions_and_purge(tmp_path: Path) -> None:
    channels = [_channel_dict(1, title="Algo Channel 1")]
    videos = [
        _video_dict(1, title="Liked Dynamic Programming", tags=["dp", "algorithms"]),
        _video_dict(2, title="Saved Tree Algorithms", tags=["trees", "algorithms"]),
        _video_dict(3, title="Unseen Dynamic Programming Guide", tags=["dp", "algorithms"]),
        _video_dict(4, title="Unseen Graph Algorithms", tags=["graphs", "algorithms"]),
    ]
    likes = [{"item_id": _vid(1), "activity_type": "like", "account_id": "learner_a", "channel_id": _cid(1)}]
    playlists = [{"playlist_id": "PL_user_0001", "title": "Study", "item_count": 1, "privacy": "private"}]
    pl_items = {
        "PL_user_0001": [
            {
                "item_id": _vid(2),
                "activity_type": "playlist_entry",
                "account_id": "learner_a",
                "playlist_id": "PL_user_0001",
                "playlist_item_id": "PLI_1",
            }
        ]
    }
    (tmp_path / "sample_channels.json").write_text(json.dumps(channels), encoding="utf-8")
    (tmp_path / "sample_videos.json").write_text(json.dumps(videos), encoding="utf-8")
    (tmp_path / "sample_likes.json").write_text(json.dumps(likes), encoding="utf-8")
    (tmp_path / "sample_playlists.json").write_text(json.dumps(playlists), encoding="utf-8")
    (tmp_path / "sample_playlist_items.json").write_text(json.dumps(pl_items), encoding="utf-8")

    # 1. Missing consent -> AUTH_REQUIRED, 0 provider calls
    raw_no, gw_no, _, ctx_no = _setup_gateway(tmp_path, has_read_consent=False)
    svc_no = RecommendationService(gw_no, ctx_no, storage=gw_no.storage)
    no_consent = svc_no.tool_response(lambda: svc_no.recommend(["likes"]))
    assert no_consent["error"]["code"] == "AUTH_REQUIRED"
    assert raw_no.requests == 0

    # 2. Invalid arguments -> INVALID_ARGUMENTS, 0 provider calls
    bad_src = svc_no.tool_response(lambda: svc_no.recommend([]))
    assert bad_src["error"]["code"] == "INVALID_ARGUMENTS"
    assert raw_no.requests == 0

    # 3. Happy path with reconciled weights & exclusions
    raw, gw, storage, ctx = _setup_gateway(tmp_path, account_id="learner_a", has_read_consent=True)
    svc = RecommendationService(gw, ctx, storage=storage)
    resp = svc.tool_response(
        lambda: svc.recommend(["likes", "subscriptions", "playlists"], topic="algorithms", limit=10)
    )
    assert "result" in resp
    res = resp["result"]
    assert WATCH_HISTORY_DISCLOSURE in res["watch_history_disclosure"]
    rec_ids = [r["video_id"] for r in res["recommendations"]]
    assert _vid(1) not in rec_ids
    assert _vid(2) not in rec_ids
    assert set(rec_ids) == {_vid(3), _vid(4)}

    for item in res["recommendations"]:
        assert item["components"] == RECOMMENDATION_WEIGHTS
        assert abs(sum(f["contribution"] for f in item["feature_trace"].values()) - item["score"]) <= 1e-6
        assert len(item["contributing_items"]) <= 3
        assert len(item["reason"]) <= 200
    assert raw.writes == 0
    assert resp["meta"]["quota_used"] <= 40
    assert resp["meta"]["search_calls"] <= 3

    # 4. Derived profile cache isolation & purge
    storage.set_cache("derived_profile", {"k": "b"}, "derived_profile", {"x": 1}, account_id="learner_b")
    purged = storage.purge_account_data("learner_a")
    assert purged["cache_entries"] >= 1
    assert storage.get_cache("derived_profile", {"k": "b"}, category="derived_profile", account_id="learner_b") == {"x": 1}

    # 5. Empty authorised profile -> NO_PROFILE_DATA, 0 discovery searches
    (tmp_path / "sample_likes.json").write_text("[]", encoding="utf-8")
    raw_empty, gw_empty, storage_empty, ctx_empty = _setup_gateway(tmp_path, account_id="empty_user")
    svc_empty = RecommendationService(gw_empty, ctx_empty, storage=storage_empty)
    empty_resp = svc_empty.tool_response(lambda: svc_empty.recommend(["likes"]))
    assert empty_resp["error"]["code"] == "NO_PROFILE_DATA"
    assert raw_empty.call_counts["search_video_ids"] == 0
    assert raw_empty.writes == 0


def test_fr4_engagement_comparison_bins_provenance_and_bounds(tmp_path: Path) -> None:
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
    channels = [_channel_dict(1, title="Chan One"), _channel_dict(2, title="Chan Two")]
    # Current window: 2026-11-01 to 2026-11-15 -> 3 from chan 1, 1 from chan 2 (3/4 = 75%)
    # Baseline window: 2026-10-01 to 2026-10-15 -> 2 from chan 1, 2 from chan 2 (2/4 = 50%)
    videos = [
        _video_dict(1, channel_id=_cid(1), duration_seconds=200, category_id="28"),   # lt_5m
        _video_dict(2, channel_id=_cid(1), duration_seconds=400, category_id="28"),   # 5_to_10m
        _video_dict(3, channel_id=_cid(1), duration_seconds=900, category_id="27"),   # 10_to_20m
        _video_dict(4, channel_id=_cid(2), duration_seconds=1500, category_id="28"),  # 20_to_40m
        _video_dict(5, channel_id=_cid(1), duration_seconds=2700, category_id="28"),  # 40_to_60m
        _video_dict(6, channel_id=_cid(1), duration_seconds=4000, category_id="28"),  # gte_60m
        _video_dict(7, channel_id=_cid(2), duration_seconds=600, category_id="27"),
        _video_dict(8, channel_id=_cid(2), duration_seconds=600, category_id="27", published_at="2026-10-05T10:00:00Z"),
    ]
    likes = [
        {"item_id": _vid(1), "activity_type": "like", "account_id": "learner_a", "timestamp": "2026-11-02T10:00:00Z", "timestamp_provenance": "genuine"},
        {"item_id": _vid(2), "activity_type": "like", "account_id": "learner_a", "timestamp": "2026-11-03T10:00:00Z", "timestamp_provenance": "genuine"},
        {"item_id": _vid(3), "activity_type": "like", "account_id": "learner_a", "timestamp": "2026-11-09T10:00:00Z", "timestamp_provenance": "genuine"},
        {"item_id": _vid(4), "activity_type": "like", "account_id": "learner_a", "timestamp": "2026-11-10T10:00:00Z", "timestamp_provenance": "genuine"},
        {"item_id": _vid(5), "activity_type": "like", "account_id": "learner_a", "timestamp": "2026-10-02T10:00:00Z", "timestamp_provenance": "genuine"},
        {"item_id": _vid(6), "activity_type": "like", "account_id": "learner_a", "timestamp": "2026-10-03T10:00:00Z", "timestamp_provenance": "genuine"},
        {"item_id": _vid(7), "activity_type": "like", "account_id": "learner_a", "timestamp": "2026-10-04T10:00:00Z", "timestamp_provenance": "genuine"},
        # Fallback publication date (no genuine timestamp)
        {"item_id": _vid(8), "activity_type": "like", "account_id": "learner_a", "timestamp_provenance": "unknown"},
    ]
    subs = [
        # Undated subscription -> excluded from period metrics, counted in undated_by_source
        {"item_id": _cid(1), "activity_type": "subscription", "account_id": "learner_a", "timestamp_provenance": "unknown"}
    ]
    (tmp_path / "sample_channels.json").write_text(json.dumps(channels), encoding="utf-8")
    (tmp_path / "sample_videos.json").write_text(json.dumps(videos), encoding="utf-8")
    (tmp_path / "sample_likes.json").write_text(json.dumps(likes), encoding="utf-8")
    (tmp_path / "sample_subscriptions.json").write_text(json.dumps(subs), encoding="utf-8")

    raw, gw, _, ctx = _setup_gateway(tmp_path, now=now)
    svc = EngagementService(gw, ctx)

    # Supplying both period and period_days fails before provider calls
    both_err = svc.tool_response(
        lambda: svc.analyse(["likes"], period={"days": 30}, period_days=30)
    )
    assert both_err["error"]["code"] == "INVALID_ARGUMENTS"
    assert raw.requests == 0

    resp = svc.tool_response(
        lambda: svc.analyse(
            ["likes", "subscriptions"],
            period={"start": "2026-11-01", "end": "2026-11-15"},
            comparison_period={"start": "2026-10-01", "end": "2026-10-15"},
            group_by="week",
        )
    )
    assert "result" in resp
    res = resp["result"]
    assert res["observation_count"] == 4
    assert res["undated_by_source"]["subscriptions"] == 1
    assert PUBLICATION_FALLBACK_WARNING in res["warnings"]
    assert any("Fewer than 10" in w for w in res["warnings"])

    chan_delta = next(
        c for c in res["comparison"]["deltas"]["channels"] if c["channel_id"] == _cid(1)
    )
    assert chan_delta["current_share"] == 0.75
    assert chan_delta["baseline_share"] == 0.5
    assert chan_delta["count_delta"] == 1
    assert chan_delta["count_percentage_delta"] == 50.0

    # Zero-baseline bin percentage delta is None
    assert res["comparison"]["deltas"]["histogram"]["lt_5m"]["baseline"] == 0
    assert res["comparison"]["deltas"]["histogram"]["lt_5m"]["percentage_delta"] is None

    assert raw.writes == 0
    assert resp["meta"]["search_calls"] == 0
    assert resp["meta"]["quota_used"] <= 60
