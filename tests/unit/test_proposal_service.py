"""Unit tests for C15 read-only proposal service, seams, and hard-filter enforcement."""

from __future__ import annotations

from datetime import UTC, datetime

from focuslist.clock import FakeClock
from focuslist.config import Settings
from focuslist.context import RequestContext
from focuslist.curation import propose_playlist_action
from focuslist.curation.approval import PlaylistApprovals
from focuslist.errors import ErrorCode, QuotaBudgetExceededError
from focuslist.platform.auth import AuthManager, MemoryCredentialStore
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.platform.storage import FocusListStorage
from focuslist.types import VideoRecord


def _make_context(quota_remaining: int = 10000) -> RequestContext:
    cfg = Settings(provider="fixture")
    clock = FakeClock(datetime(2026, 11, 26, 0, 0, tzinfo=UTC))
    ctx = RequestContext(settings=cfg, clock=clock)
    if quota_remaining < 10000:
        ctx.record_quota_charge(10000 - quota_remaining)
    return ctx


def test_propose_playlist_action_valid_fixture_returns_reviewable_proposal(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """Valid 45m/20m request on default fixtures returns PROPOSED with 0 writes."""
    fixture_provider.reset_counters()
    ctx = _make_context()

    resp = propose_playlist_action(
        {
            "topic": "recursion",
            "target_duration": "PT45M",
            "max_item_duration": "PT20M",
            "language": "en",
        },
        provider=fixture_provider,
        context=ctx,
    )
    res = resp["result"]
    assert res["status"] == "PREVIEW"
    assert res["privacy_status"] == "private"
    assert res["writes_executed"] == 0
    assert fixture_provider.writes == 0
    assert fixture_provider.call_counts["search_candidates"] <= 3
    assert res["estimated_write_cost"] == 51 + (50 * res["item_count"])
    assert 2565 <= res["total_duration_seconds"] <= 2835
    assert all(item["untrusted"] is True for item in res["items"])
    assert res["confirmation_token"] is None


def test_propose_playlist_action_infeasible_returns_nearest_achievable(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """2h target on 5-video fixture (76m total) returns INFEASIBLE with nearest runtime."""
    fixture_provider.reset_counters()
    ctx = _make_context()

    resp = propose_playlist_action(
        {
            "topic": "recursion",
            "target_duration": "PT2H",
            "max_item_duration": "PT20M",
        },
        provider=fixture_provider,
        context=ctx,
    )
    res = resp["result"]
    assert res["status"] == "INFEASIBLE"
    assert res["proposal_id"] is None
    assert res["confirmation_token"] is None
    assert res["nearest_achievable_seconds"] == 3960
    assert res["writes_executed"] == 0
    assert fixture_provider.writes == 0
    assert res["unmet_constraints"][0]["constraint"] == "target_duration"


def test_propose_playlist_action_invalid_input_makes_zero_provider_calls(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """Invalid or contradictory arguments fail before any provider call or quota charge."""
    fixture_provider.reset_counters()
    ctx = _make_context()

    resp = propose_playlist_action(
        {
            "topic": "recursion",
            "target_duration": "PT1H",
            "min_item_duration": "PT25M",
            "max_item_duration": "PT15M",
        },
        provider=fixture_provider,
        context=ctx,
    )
    assert resp["error"]["code"] == ErrorCode.INVALID_ARGUMENTS.value
    assert fixture_provider.requests == 0
    assert fixture_provider.writes == 0
    assert resp["meta"]["quota_used"] == 0


def test_propose_playlist_action_quota_and_signer_seams(
    fixture_provider: FixtureVideoProvider,
) -> None:
    """Verify quota preflight seam rejects over-budget and signer seam signs payload."""
    fixture_provider.reset_counters()
    ctx = _make_context(quota_remaining=5)

    over_budget = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT45M", "max_item_duration": "PT20M"},
        provider=fixture_provider,
        context=ctx,
    )
    assert over_budget["error"]["code"] == ErrorCode.QUOTA_BUDGET_EXCEEDED.value
    assert fixture_provider.requests == 0

    def _reject_quota(searches: int, units: int) -> None:
        raise QuotaBudgetExceededError("Blocked by C19 seam")

    ctx_ok = _make_context()
    hook_rejected = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT45M", "max_item_duration": "PT20M"},
        provider=fixture_provider,
        context=ctx_ok,
        quota_preflight=_reject_quota,
    )
    assert hook_rejected["error"]["code"] == ErrorCode.QUOTA_BUDGET_EXCEEDED.value
    assert fixture_provider.requests == 0

    store = FocusListStorage(ctx_ok.settings.db_path, clock=ctx_ok.clock)
    auth = AuthManager(settings=ctx_ok.settings, storage=store, credential_store=MemoryCredentialStore())
    approvals = PlaylistApprovals(store, auth, ctx_ok)
    signed = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT45M", "max_item_duration": "PT20M"},
        provider=fixture_provider,
        context=ctx_ok,
        approvals=approvals,
    )
    review = signed["result"]
    verified = approvals.load(review["proposal_id"], token=review["confirmation_token"])
    assert verified.action.review["items"] == review["items"]


def test_propose_playlist_action_hydrates_and_filters_duplicates_and_unknown_lang() -> None:
    """Verify batch detail hydration, duplicate removal, and unknown-language policy."""
    class _SpyProvider(FixtureVideoProvider):
        def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
            self._record_call("search_candidates", query=query, max_results=max_results)
            return [
                VideoRecord(
                    video_id="hyd_vid_001",
                    canonical_url="https://www.youtube.com/watch?v=hyd_vid_001",
                    title="Recursion Part 1",
                    channel_id="UC_hyd_1",
                    channel_title="Hydration Academy",
                    duration_seconds=600,
                    language=None,  # triggers unknown-language & hydration check
                ),
                VideoRecord(
                    video_id="hyd_vid_001",  # duplicate
                    canonical_url="https://www.youtube.com/watch?v=hyd_vid_001",
                    title="Recursion Part 1",
                    channel_id="UC_hyd_1",
                    channel_title="Hydration Academy",
                    duration_seconds=600,
                    language=None,
                ),
            ]

    provider = _SpyProvider()
    strict_resp = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT10M", "max_item_duration": "PT20M"},
        provider=provider,
        context=_make_context(),
    )
    assert strict_resp["result"]["status"] == "INFEASIBLE"
    assert strict_resp["result"]["filtered_out_counts"]["duplicate"] == 1
    assert strict_resp["result"]["filtered_out_counts"]["language_mismatch"] == 1
    assert provider.writes == 0

    permissive_resp = propose_playlist_action(
        {
            "topic": "recursion",
            "target_duration": "PT10M",
            "max_item_duration": "PT20M",
            "allow_unknown_language": True,
        },
        provider=provider,
        context=_make_context(),
    )
    assert permissive_resp["result"]["status"] == "PREVIEW"
    assert permissive_resp["result"]["items"][0]["unknown_language_flagged"] is True
    assert permissive_resp["result"]["warnings"]
    assert provider.writes == 0
