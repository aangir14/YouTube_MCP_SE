"""Read-only constraint proposal service (C15, SRS FR-5.1–5.8)."""

from __future__ import annotations

from collections.abc import Callable
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
from focuslist.platform.provider import VideoProvider
from focuslist.types import VideoRecord, format_duration_display

_MAX_SEARCH_CALLS = 3
_MAX_DETAIL_BATCHES = 3
_PROPOSAL_READ_BASELINE_UNITS = 15
_PROPOSAL_EXPIRY_MINUTES = 30

# Type aliases for eventual C19 (quota) and C21 (signing) seams
QuotaPreflightHook = Callable[[int, int], None]
ProposalSignerHook = Callable[[dict[str, Any]], str]


def _retrieve_bounded_candidates(
    provider: VideoProvider,
    constraints: ValidatedPlaylistConstraints,
    *,
    max_search_calls: int = _MAX_SEARCH_CALLS,
) -> list[VideoRecord]:
    """Retrieve bounded candidates (<= 3 search calls, <= 150 items) and batch-hydrate."""
    collected: list[VideoRecord] = []

    # Optional seed lookup (counts as 1 detail lookup)
    if constraints.seed_video_id:
        for vid in provider.get_video_details([constraints.seed_video_id]):
            collected.append(normalise_video_record(vid))

    # Bounded search calls (at most 3 calls, <= 50 per call, total cap 150)
    search_cap = min(max_search_calls, _MAX_SEARCH_CALLS)
    queries = [constraints.topic]
    for q in queries[:search_cap]:
        batch = provider.search_candidates(q, max_results=50)
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
            for hv in provider.get_video_details(chunk):
                norm_h = normalise_video_record(hv)
                hydrated_by_id[norm_h.video_id] = norm_h
        if hydrated_by_id:
            collected = [hydrated_by_id.get(v.video_id, v) for v in collected]

    return collected


def propose_playlist_action(
    raw_arguments: dict[str, Any],
    *,
    provider: VideoProvider,
    context: RequestContext,
    quota_preflight: QuotaPreflightHook | None = None,
    signer: ProposalSignerHook | None = None,
) -> dict[str, Any]:
    """Validate constraints, retrieve bounded metadata, solve, and return read-only proposal.

    Guarantees:
    - Zero provider calls and zero quota charges on invalid/contradictory arguments.
    - Zero write calls (create_playlist, insert_playlist_item, delete_playlist) ever executed.
    - Deferred SQLite persistence (C16), committed quota ledger (C19), and HMAC signing (C21).
    """
    try:
        constraints = validate_proposal_arguments(raw_arguments)
    except FocusListError as exc:
        return context.failure(exc).model_dump()

    # Quota seam (C19): check remaining daily budget before any provider calls
    if quota_preflight is not None:
        try:
            quota_preflight(_MAX_SEARCH_CALLS, _PROPOSAL_READ_BASELINE_UNITS)
        except FocusListError as exc:
            return context.failure(exc).model_dump()
    elif max(0, context.settings.daily_general_quota - context.quota_used) < _PROPOSAL_READ_BASELINE_UNITS:
        return context.failure(
            QuotaBudgetExceededError(
                "Insufficient remaining daily quota units for playlist proposal discovery."
            )
        ).model_dump()

    try:
        candidates = _retrieve_bounded_candidates(provider, constraints)
    except FocusListError as exc:
        return context.failure(exc).model_dump()

    context.record_quota_charge(_PROPOSAL_READ_BASELINE_UNITS)

    now = context.clock.now()
    result: SolverResult = solve_playlist(candidates, constraints, now=now)

    if not result.feasible:
        return context.success(
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

    return context.success(
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
            "deferred_seams": [
                "C16_sqlite_persistence",
                "C19_committed_quota_ledger",
                "C21_hmac_signing_and_confirm",
            ],
            "note": (
                "Read-only proposal generated with 0 writes. Review the exact list above; "
                "separate explicit human confirmation is required before creation."
            ),
        }
    ).model_dump()
