"""Read-only constraint proposal service (C15, wired to C16 quota ledger)."""

from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import nullcontext
from datetime import timedelta
from typing import Any
from uuid import uuid4

from focuslist.context import RequestContext
from focuslist.curation.constraints import (
    ValidatedPlaylistConstraints,
    validate_proposal_arguments,
)
from focuslist.curation.solver import SolverResult, solve_playlist
from focuslist.errors import FocusListError, QuotaBudgetExceededError
from focuslist.metadata import normalise_video_record
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.provider import VideoProvider
from focuslist.platform.quota import QuotaManager
from focuslist.types import VideoRecord, format_duration_display

_MAX_SEARCH_CALLS = 3
_MAX_DETAIL_BATCHES = 3
_PROPOSAL_READ_BASELINE_UNITS = 15
_PROPOSAL_EXPIRY_MINUTES = 30

# Type aliases for eventual C21 (signing) and quota hooks
QuotaPreflightHook = Callable[[int, int], None]
ProposalSignerHook = Callable[[dict[str, Any]], str]


def _retrieve_bounded_candidates(
    provider: VideoProvider,
    constraints: ValidatedPlaylistConstraints,
    *,
    max_search_calls: int = _MAX_SEARCH_CALLS,
) -> tuple[list[VideoRecord], int, int]:
    """Retrieve bounded candidates (<= 3 searches, <= 150 items) and return (items, units, searches)."""
    collected: list[VideoRecord] = []
    observed_units = 0
    observed_searches = 0

    def _call_detail(ids: list[str]) -> list[VideoRecord]:
        nonlocal observed_units
        before = getattr(provider, "network_attempts", 0)
        try:
            return provider.get_video_details(ids)
        finally:
            after = getattr(provider, "network_attempts", before + 1)
            observed_units += max(0, after - before)

    def _call_search(query: str, max_results: int) -> list[VideoRecord]:
        nonlocal observed_searches, observed_units
        before = getattr(provider, "network_attempts", 0)
        try:
            return provider.search_candidates(query, max_results=max_results)
        finally:
            after = getattr(provider, "network_attempts", before + 1)
            delta = max(0, after - before)
            if delta > 0:
                observed_searches += 1
                if delta > 1:
                    # LiveVideoProvider search_candidates issues 1+ search pages plus detail batches
                    observed_units += delta - 1

    # Optional seed lookup (counts as 1 detail lookup)
    if constraints.seed_video_id:
        for vid in _call_detail([constraints.seed_video_id]):
            collected.append(normalise_video_record(vid))

    # Bounded search calls (at most 3 calls, <= 50 per call, total cap 150)
    search_cap = min(max_search_calls, _MAX_SEARCH_CALLS)
    queries = [constraints.topic]
    for q in queries[:search_cap]:
        batch = _call_search(q, 50)
        for vid in batch:
            collected.append(normalise_video_record(vid))
            if len(collected) >= 150:
                break
        if len(collected) >= 150:
            break

    # Batch-hydrate any unique candidate missing duration or language metadata (<= 3 batches of 50)
    needs_hydration = list(
        dict.fromkeys(
            v.video_id
            for v in collected
            if v.duration_seconds is None or v.duration_seconds == 0 or v.language is None
        )
    )
    if needs_hydration:
        hydrated_by_id: dict[str, VideoRecord] = {}
        for start in range(0, min(len(needs_hydration), _MAX_DETAIL_BATCHES * 50), 50):
            chunk = needs_hydration[start : start + 50]
            for hv in _call_detail(chunk):
                norm_h = normalise_video_record(hv)
                hydrated_by_id[norm_h.video_id] = norm_h
        if hydrated_by_id:
            collected = [hydrated_by_id.get(v.video_id, v) for v in collected]

    return collected, observed_units, observed_searches


def _local_preflight_fallback(context: RequestContext, searches: int, units: int) -> None:
    """Enforce per-request cap, 5% safety margin, and search budget when no QuotaManager is attached."""
    settings = context.settings
    if units > settings.request_unit_cap:
        raise QuotaBudgetExceededError(
            f"Playlist proposal worst-case cost ({units} units) exceeds per-request cap "
            f"({settings.request_unit_cap})."
        )
    margin = math.ceil(settings.daily_general_quota * settings.quota_safety_margin)
    effective_remaining = max(0, settings.daily_general_quota - margin - context.quota_used)
    if effective_remaining < units:
        raise QuotaBudgetExceededError(
            "Insufficient remaining daily quota units (after 5% safety margin) for playlist proposal."
        )
    search_remaining = max(0, settings.daily_search_quota - context.search_calls_used)
    if search_remaining < searches:
        raise QuotaBudgetExceededError(
            "Insufficient remaining daily search calls for playlist proposal."
        )


def propose_playlist_action(
    raw_arguments: dict[str, Any],
    *,
    provider: VideoProvider,
    context: RequestContext,
    quota_preflight: QuotaPreflightHook | None = None,
    signer: ProposalSignerHook | None = None,
    quota_manager: QuotaManager | None = None,
) -> dict[str, Any]:
    """Validate constraints, retrieve bounded metadata, solve, and return read-only proposal.

    Guarantees:
    - Zero provider calls and zero quota charges on invalid/contradictory arguments.
    - Zero write calls (create_playlist, insert_playlist_item, delete_playlist) ever executed.
    - Shared C16 quota admission & dispatch accounting via ProviderGateway / QuotaManager.
    """
    before_units = context.quota_used
    before_searches = context.search_calls_used
    before_hits = context.cache_hits

    try:
        constraints = validate_proposal_arguments(raw_arguments)
    except FocusListError as exc:
        resp = context.failure(exc).model_dump()
        resp["meta"]["quota_used"] = 0
        resp["meta"]["search_calls"] = 0
        resp["meta"]["cache_hits"] = 0
        return resp

    active_qm = quota_manager or (
        provider.quota_manager if isinstance(provider, ProviderGateway) else None
    )

    try:
        if quota_preflight is not None:
            quota_preflight(_MAX_SEARCH_CALLS, _PROPOSAL_READ_BASELINE_UNITS)

        if isinstance(provider, ProviderGateway):
            budget_cm: Any = provider.operation_budget(
                _PROPOSAL_READ_BASELINE_UNITS,
                _MAX_SEARCH_CALLS,
                context=context,
            )
            gateway_managed = True
        elif active_qm is not None:
            reservation = active_qm.reserve(_PROPOSAL_READ_BASELINE_UNITS, _MAX_SEARCH_CALLS)
            budget_cm = nullcontext(reservation)
            gateway_managed = False
        else:
            if quota_preflight is None:
                _local_preflight_fallback(context, _MAX_SEARCH_CALLS, _PROPOSAL_READ_BASELINE_UNITS)
            budget_cm = nullcontext(None)
            gateway_managed = False
    except FocusListError as exc:
        resp = context.failure(exc).model_dump()
        resp["meta"]["quota_used"] = 0
        resp["meta"]["search_calls"] = 0
        resp["meta"]["cache_hits"] = 0
        return resp

    try:
        with budget_cm as scope_or_res:
            try:
                candidates, obs_units, obs_searches = _retrieve_bounded_candidates(
                    provider, constraints
                )
            finally:
                if not gateway_managed and active_qm is not None and scope_or_res is not None:
                    # Only reach here if _retrieve_bounded_candidates succeeded or raised
                    pass

            if not gateway_managed:
                if active_qm is not None and scope_or_res is not None:
                    active_qm.charge_attempt(obs_units, obs_searches, reservation=scope_or_res)
                    active_qm.release_reservation(scope_or_res)
                    context.set_quota_remaining(active_qm.get_status().general_units_remaining)
                context.record_quota_charge(obs_units)
                context.record_search_charge(obs_searches)
    except FocusListError as exc:
        if not gateway_managed and active_qm is not None and scope_or_res is not None:
            active_qm.release_reservation(scope_or_res)
        resp = context.failure(exc).model_dump()
        resp["meta"]["quota_used"] = context.quota_used - before_units
        resp["meta"]["search_calls"] = context.search_calls_used - before_searches
        resp["meta"]["cache_hits"] = context.cache_hits - before_hits
        return resp

    now = context.clock.now()
    result: SolverResult = solve_playlist(candidates, constraints, now=now)

    deferred_seams = ["C16_sqlite_persistence", "C21_hmac_signing_and_confirm"]
    if active_qm is None:
        deferred_seams.insert(1, "C19_committed_quota_ledger")

    if not result.feasible:
        resp = context.success(
            {
                "status": "INFEASIBLE",
                "proposal_id": None,
                "confirmation_token": None,
                "topic": constraints.topic,
                "language": constraints.language,
                "privacy_status": constraints.privacy_status,
                "nearest_achievable_seconds": result.nearest_achievable_seconds,
                "nearest_achievable_duration": format_duration_display(
                    result.nearest_achievable_seconds
                ),
                "nearest_items": [item.model_dump() for item in result.nearest_items],
                "constraint_status": result.constraint_status,
                "unmet_constraints": [u.model_dump() for u in result.unmet_constraints],
                "filtered_out_counts": result.filtered_out_counts,
                "warnings": result.warnings,
                "writes_executed": 0,
                "note": (
                    "Constraints could not be satisfied without relaxing hard filters. "
                    "Review nearest achievable runtime and adjust constraints."
                ),
            }
        ).model_dump()
        resp["meta"]["quota_used"] = context.quota_used - before_units
        resp["meta"]["search_calls"] = context.search_calls_used - before_searches
        resp["meta"]["cache_hits"] = context.cache_hits - before_hits
        return resp

    proposal_id = f"prop_{uuid4().hex[:12]}"
    resolved_title = constraints.title or f"{constraints.topic} - {now.strftime('%Y-%m-%d')}"
    expires_at = now + timedelta(minutes=_PROPOSAL_EXPIRY_MINUTES)
    estimated_write_cost = 51 + (50 * result.item_count)

    canonical_payload = {
        "proposal_id": proposal_id,
        "action_kind": "create",
        "title": resolved_title,
        "privacy_status": constraints.privacy_status,
        "ordered_video_ids": [item.video_id for item in result.selected_items],
        "expires_at": expires_at.isoformat(),
    }
    token = (
        signer(canonical_payload)
        if signer is not None
        else f"pending_c21_hmac_signing:{proposal_id}"
    )

    items_payload = [
        {
            "order": item.order,
            "video_id": item.video_id,
            "title": item.title,
            "channel_id": item.channel_id,
            "channel_title": item.channel_title,
            "duration": item.duration_display,
            "duration_seconds": item.duration_seconds,
            "duration_iso": item.duration_iso,
            "score": item.score,
            "reason": item.reason,
            "untrusted": item.untrusted,
            "unknown_language_flagged": item.unknown_language_flagged,
        }
        for item in result.selected_items
    ]

    resp = context.success(
        {
            "status": "PROPOSED",
            "proposal_id": proposal_id,
            "action_kind": "create",
            "title": resolved_title,
            "topic": constraints.topic,
            "privacy_status": constraints.privacy_status,
            "language": constraints.language,
            "ordering": constraints.ordering,
            "item_count": result.item_count,
            "total_duration": result.total_duration_display,
            "total_duration_iso": result.total_duration_iso,
            "total_duration_seconds": result.total_duration_seconds,
            "total_score": result.total_score,
            "estimated_write_cost": estimated_write_cost,
            "expires_at": expires_at.isoformat(),
            "expires_in_minutes": _PROPOSAL_EXPIRY_MINUTES,
            "confirmation_token": token,
            "constraint_status": result.constraint_status,
            "filtered_out_counts": result.filtered_out_counts,
            "items": items_payload,
            "warnings": result.warnings,
            "writes_executed": 0,
            "deferred_seams": deferred_seams,
            "note": (
                "Read-only proposal generated with 0 writes. Review the exact list above; "
                "separate explicit human confirmation is required before creation."
            ),
        }
    ).model_dump()
    resp["meta"]["quota_used"] = context.quota_used - before_units
    resp["meta"]["search_calls"] = context.search_calls_used - before_searches
    resp["meta"]["cache_hits"] = context.cache_hits - before_hits
    return resp
