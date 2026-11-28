"""Unit and integration tests for Workstream 2: quota manager, gateway, and retries (C16)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from focuslist.clock import FakeClock
from focuslist.config import Settings
from focuslist.context import RequestContext
from focuslist.curation import propose_playlist_action
from focuslist.errors import (
    ErrorCode,
    InvalidArgumentsError,
    NetworkTimeoutError,
    QuotaBudgetExceededError,
    QuotaExhaustedError,
    RateLimitedError,
)
from focuslist.platform.fault_provider import FaultInjectionProvider
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.quota import QuotaManager, estimate_operation_cost
from focuslist.platform.storage import FocusListStorage


def _build_gateway(
    tmp_path: Path,
    clock: FakeClock,
    *,
    settings: Settings | None = None,
    cache_enabled: bool = True,
) -> tuple[FocusListStorage, QuotaManager, FixtureVideoProvider, FaultInjectionProvider, ProviderGateway]:
    cfg = settings or Settings(provider="fixture", db_path=tmp_path / "quota.db")
    storage = FocusListStorage(cfg.db_path, clock=clock)
    qm = QuotaManager(storage=storage, settings=cfg, clock=clock)
    fixture = FixtureVideoProvider(fixture_dir=Path("tests/fixtures"))
    fault = FaultInjectionProvider(target_provider=fixture)
    gateway = ProviderGateway(
        fault,
        storage=storage,
        quota_manager=qm,
        settings=cfg,
        clock=clock,
        cache_enabled=cache_enabled,
        sleep_fn=lambda _: None,
        jitter_fn=lambda _: 0.0,
    )
    return storage, qm, fixture, fault, gateway


def test_estimate_quota_local_appendix_b_and_validation(tmp_path: Path) -> None:
    """Verify dry-run estimate_quota matches Appendix B 12-item baseline with zero calls."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    storage, qm, _, _, _ = _build_gateway(tmp_path, clock)

    prop_est = estimate_operation_cost("propose_playlist", storage=storage, quota_manager=qm)
    assert prop_est.estimated_general_units == 15
    assert prop_est.estimated_search_calls == 3
    assert prop_est.feasible is True

    confirm_est = estimate_operation_cost(
        "confirm_playlist", {"item_count": 12}, storage=storage, quota_manager=qm
    )
    assert confirm_est.estimated_general_units == 651
    assert confirm_est.estimated_search_calls == 0
    assert confirm_est.feasible is True

    audit_est = estimate_operation_cost(
        "audit_playlist", {"item_count": 120}, storage=storage, quota_manager=qm
    )
    assert audit_est.estimated_general_units == 7  # 2 * ceil(120/50) + 1 = 7

    with pytest.raises(InvalidArgumentsError):
        estimate_operation_cost("unknown_tool", storage=storage, quota_manager=qm)


def test_cache_hit_costs_zero_and_pacific_rollover_resets_ledger(tmp_path: Path) -> None:
    """Verify cache hits incur zero quota and Pacific midnight resets daily balances."""
    # 2026-11-27 23:30 PST = 2026-11-28 07:30 UTC
    clock = FakeClock(datetime(2026, 11, 28, 7, 30, tzinfo=UTC))
    _, qm, fixture, _, gateway = _build_gateway(tmp_path, clock)

    first = gateway.get_video_details(["syn_vid0001"])
    assert len(first) == 1
    assert fixture.network_attempts == 1
    assert qm.get_status().general_units_used == 1
    assert qm.get_status().pacific_date == "2026-11-27"

    # Second call hits cache -> 0 provider calls, 0 units, cache_hits == 1
    second = gateway.get_video_details(["syn_vid0001"])
    assert second == first
    assert fixture.network_attempts == 1
    snap = qm.get_status()
    assert snap.general_units_used == 1
    assert snap.cache_hits == 1

    # Advance 35 minutes past midnight PST -> new Pacific day 2026-11-28 with fresh budget
    clock.advance(timedelta(minutes=35))
    after_reset = qm.get_status()
    assert after_reset.pacific_date == "2026-11-28"
    assert after_reset.general_units_used == 0
    assert after_reset.search_calls_used == 0


def test_oversized_request_and_near_cap_safety_margin_reject_zero_calls(tmp_path: Path) -> None:
    """Reject over-cap (>2600) and margin-exceeding workflows with zero provider calls."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    _, qm, fixture, fault, gateway = _build_gateway(tmp_path, clock)

    # Request cap (2600) exceeded -> zero calls
    with pytest.raises(QuotaBudgetExceededError):
        qm.reserve(2601, 0)
    assert fixture.requests == 0

    # Near-cap: consume 9,495 units -> 5 effective units left (500 safety margin retained)
    qm.charge_attempt(9495, 0)
    assert qm.get_status().effective_general_remaining == 5
    # 5 units succeeds, 6 units fails with zero provider calls
    res_ok = qm.reserve(5, 0)
    qm.release_reservation(res_ok)

    ctx = RequestContext(settings=gateway.settings, clock=clock)
    out = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT45M", "max_item_duration": "PT20M"},
        provider=gateway,
        context=ctx,
    )
    assert out["error"]["code"] == ErrorCode.QUOTA_BUDGET_EXCEEDED.value
    assert fixture.requests == 0
    assert fault.requests == 0


def test_retry_accounting_exhaustion_stop_and_retry_budget_cap(tmp_path: Path) -> None:
    """Retries charge each attempt; quota/rate faults stop retries and mark bucket exhausted."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    cfg = Settings(provider="fixture", db_path=tmp_path / "retry.db", max_retries=3)
    _, qm, fixture, fault, gateway = _build_gateway(tmp_path, clock, settings=cfg, cache_enabled=False)

    # 2 transient timeouts then success -> 3 total attempts charged (initial + 2 retries)
    fault.inject_normalized_fault("get_video_details", "timeout", count=2)
    res = gateway.get_video_details(["syn_vid0001"])
    assert len(res) == 1
    assert fault.network_attempts == 3
    assert qm.get_status().general_units_used == 3

    # Retry stopped when remaining effective budget cannot afford retry
    qm.charge_attempt(9496, 0)  # 1 effective unit left (9500 - 3 - 9496 = 1)
    fault.inject_normalized_fault("get_video_details", "timeout", count=2)
    with pytest.raises(NetworkTimeoutError):
        gateway.get_video_details(["syn_vid0002"])
    # Initial call charged the last 1 effective unit; retry saw 0 left and did NOT execute
    assert fault.network_attempts == 4
    assert qm.get_status().general_units_used == 9500

    # Rate limit / quota exhaustion marks bucket exhausted and blocks follow-up with 0 attempts
    clock.advance(timedelta(days=1))
    fault.inject_normalized_fault("search_video_ids", "rate", count=1)
    with pytest.raises(RateLimitedError):
        gateway.search_video_ids("recursion")
    assert qm.get_status().search_exhausted is True
    attempts_before = fault.network_attempts
    with pytest.raises(QuotaExhaustedError):
        gateway.search_video_ids("recursion")
    assert fault.network_attempts == attempts_before
    assert fixture.writes == 0


def test_concurrent_competing_requests_for_same_budget(tmp_path: Path) -> None:
    """Two concurrent requests competing for remaining budget cannot overspend."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    cfg = Settings(
        provider="fixture",
        db_path=tmp_path / "compete.db",
        daily_general_quota=100,
        quota_safety_margin=0.0,
        request_unit_cap=100,
    )
    storage = FocusListStorage(cfg.db_path, clock=clock)
    qm = QuotaManager(storage=storage, settings=cfg, clock=clock)

    def _attempt(_: int) -> str:
        worker_qm = QuotaManager(
            storage=FocusListStorage(cfg.db_path, clock=clock, auto_migrate=False, run_startup_cleanup=False),
            settings=cfg,
            clock=clock,
        )
        try:
            r = worker_qm.reserve(60, 0)
            worker_qm.charge_attempt(60, 0, reservation=r)
            worker_qm.release_reservation(r)
            return "ok"
        except QuotaBudgetExceededError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(_attempt, range(4)))

    assert outcomes.count("ok") == 1
    assert outcomes.count("rejected") == 3
    assert qm.get_status().general_units_used == 60


def test_c15_proposal_uses_observed_charges_and_enforces_both_buckets(tmp_path: Path) -> None:
    """C15 proposal path charges observed attempts (not fixed 15) and enforces search bucket."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    cfg = Settings(provider="fixture", db_path=tmp_path / "prop.db", daily_search_quota=4)
    _, qm, fixture, _, gateway = _build_gateway(tmp_path, clock, settings=cfg)

    ctx = RequestContext(settings=cfg, clock=clock)
    res = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT45M", "max_item_duration": "PT20M"},
        provider=gateway,
        context=ctx,
    )
    assert res["result"]["status"] == "PREVIEW"
    # Observed charge: 1 search call, 0 general units (not fixed 15)
    assert res["meta"]["search_calls"] == 1
    assert res["meta"]["quota_used"] == 0
    assert qm.get_status().search_calls_used == 1
    assert qm.get_status().search_calls_remaining == 3

    # Only 3 searches left -> second proposal runs (3 >= 3 baseline)
    res2 = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT45M", "max_item_duration": "PT20M"},
        provider=gateway,
        context=RequestContext(settings=cfg, clock=clock),
    )
    assert res2["result"]["status"] == "PREVIEW"
    assert qm.get_status().search_calls_remaining == 2

    # Now only 2 searches remain (< 3 worst-case for propose_playlist) -> rejected with 0 calls
    before_reqs = fixture.requests
    res3 = propose_playlist_action(
        {"topic": "recursion", "target_duration": "PT45M", "max_item_duration": "PT20M"},
        provider=gateway,
        context=RequestContext(settings=cfg, clock=clock),
    )
    assert res3["error"]["code"] == ErrorCode.QUOTA_BUDGET_EXCEEDED.value
    assert fixture.requests == before_reqs
