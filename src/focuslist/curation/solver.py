"""Pure deterministic playlist constraint solver and FR-5 scorer (C12)."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from focuslist.curation.constraints import ValidatedPlaylistConstraints
from focuslist.curation.ordering import (
    StudySession,
    diversify_candidates,
    order_candidates,
    pack_sessions,
)
from focuslist.discovery.scoring import ScoreExplanation, cosine_and_shared_terms, explain_score
from focuslist.metadata import (
    format_duration_iso,
    normalise_video_record,
    primary_language,
    same_primary_language,
)
from focuslist.ranking_weights import FR5_WEIGHTS
from focuslist.types import VideoRecord, format_duration_display

_TOKEN_RE = re.compile(r"[0-9A-Za-z\u00C0-\u024F\u0370-\u1FFF\u2C00-\uD7AF]+")
_FIVE_YEARS_DAYS = 1825.0


def _tokenize(text: str) -> list[str]:
    """Normalize NFKC + casefold and extract alphanumeric tokens (ADR-002/ADR-004 shared)."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return _TOKEN_RE.findall(normalized)


def _compute_tfidf_matches(query: str, documents: list[str]) -> list[tuple[float, list[str], bool]]:
    """Keep C15 query scoring and expose the most influential shared terms."""
    q_tokens = _tokenize(query)

    doc_tokens_list = [_tokenize(doc) for doc in documents]
    n_docs = len(doc_tokens_list) + 1  # Include query in corpus document frequency

    df: Counter[str] = Counter(set(q_tokens))
    for toks in doc_tokens_list:
        df.update(set(toks))

    def _tfidf_vec(tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        vec = {
            term: count * (math.log((1.0 + n_docs) / (1.0 + df[term])) + 1.0)
            for term, count in tf.items()
        }
        norm = math.sqrt(sum(val * val for val in vec.values()))
        if norm == 0.0:
            return {}
        return {term: val / norm for term, val in vec.items()}

    q_vec = _tfidf_vec(q_tokens)
    scores: list[tuple[float, list[str], bool]] = []
    for toks in doc_tokens_list:
        d_vec = _tfidf_vec(toks)
        dot = sum(q_vec[t] * d_vec[t] for t in q_vec if t in d_vec)
        _, shared = cosine_and_shared_terms(q_vec, d_vec)
        scores.append((min(1.0, max(0.0, dot)), shared, bool(d_vec)))
    return scores


class ScoredCandidate(BaseModel):
    """Eligible candidate video with deterministic FR-5 score breakdown."""

    model_config = ConfigDict(frozen=True)

    video: VideoRecord
    score: float = Field(ge=0.0, le=1.0)
    components: dict[str, float] = Field(default_factory=dict)
    reason: str = Field(default="Matches topic and duration constraints.")
    unknown_language_flagged: bool = False
    explanation: ScoreExplanation | None = None


class SelectedPlaylistItem(BaseModel):
    """Selected item in a solved playlist result."""

    model_config = ConfigDict(frozen=True)

    order: int = Field(ge=1)
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    duration_seconds: int
    duration_iso: str
    duration_display: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str
    untrusted: bool = True
    unknown_language_flagged: bool = False
    components: dict[str, float] = Field(default_factory=dict)
    feature_trace: dict[str, dict[str, float]] = Field(default_factory=dict)
    shared_terms: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    low_confidence: bool = False


class ConstraintViolation(BaseModel):
    """Structured explanation of an unmet constraint when selection is infeasible."""

    constraint: str
    requested: str
    achieved: str
    deficit_seconds: int = 0


class SolverResult(BaseModel):
    """Explicit feasible or nearest-infeasible outcome from the pure duration solver."""

    feasible: bool
    selected_items: list[SelectedPlaylistItem] = Field(default_factory=list)
    total_duration_seconds: int = 0
    total_duration_iso: str = "PT0S"
    total_duration_display: str = "00:00"
    item_count: int = 0
    total_score: float = 0.0
    nearest_achievable_seconds: int = 0
    nearest_items: list[SelectedPlaylistItem] = Field(default_factory=list)
    constraint_status: dict[str, Any] = Field(default_factory=dict)
    unmet_constraints: list[ConstraintViolation] = Field(default_factory=list)
    filtered_out_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    sessions: list[StudySession] = Field(default_factory=list)


def filter_eligible_candidates(
    candidates: list[VideoRecord],
    constraints: ValidatedPlaylistConstraints,
) -> tuple[list[tuple[VideoRecord, bool]], dict[str, int]]:
    """Apply hard eligibility filters before scoring or selection (never silently relaxed)."""
    seen_ids: set[str] = set()
    eligible: list[tuple[VideoRecord, bool]] = []
    dropped: dict[str, int] = {
        "duplicate": 0,
        "live_or_upcoming": 0,
        "age_restricted": 0,
        "unknown_duration": 0,
        "duration_out_of_range": 0,
        "language_mismatch": 0,
    }

    for raw_video in candidates:
        video = normalise_video_record(raw_video)
        if video.video_id in seen_ids:
            dropped["duplicate"] += 1
            continue
        seen_ids.add(video.video_id)

        if video.is_live or video.is_upcoming:
            dropped["live_or_upcoming"] += 1
            continue

        if video.is_age_restricted and not constraints.allow_age_restricted:
            dropped["age_restricted"] += 1
            continue

        if video.duration_seconds is None or video.duration_seconds <= 0:
            dropped["unknown_duration"] += 1
            continue

        if not (
            constraints.min_item_duration_seconds
            <= video.duration_seconds
            <= constraints.max_item_duration_seconds
        ):
            dropped["duration_out_of_range"] += 1
            continue

        lang_match = same_primary_language(video.language, constraints.language)
        unknown_lang = False
        if lang_match is False:
            dropped["language_mismatch"] += 1
            continue
        if lang_match is None:
            if not constraints.allow_unknown_language:
                dropped["language_mismatch"] += 1
                continue
            unknown_lang = True

        eligible.append((video, unknown_lang))

    return eligible, dropped


def score_candidates_fr5(
    eligible: list[tuple[VideoRecord, bool]],
    constraints: ValidatedPlaylistConstraints,
    now: datetime,
    *, weights: Mapping[str, float] = FR5_WEIGHTS,
) -> list[ScoredCandidate]:
    """Compute deterministic FR-5 scores (0.65/0.10/0.10/0.10/0.05) with zero engagement inputs."""
    if not eligible:
        return []

    now_utc = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
    docs = [
        " ".join(
            part
            for part in (
                v.title,
                v.description or "",
                " ".join(v.tags or []),
            )
            if part
        )
        for v, _ in eligible
    ]
    matches = _compute_tfidf_matches(constraints.topic, docs)

    scored: list[ScoredCandidate] = []
    for (video, unknown_lang), (topic_sim, shared, has_text) in zip(eligible, matches, strict=True):
        captions = 1.0 if video.has_captions is True else 0.0

        if video.published_at is not None:
            pub_utc = (
                video.published_at.astimezone(UTC)
                if video.published_at.tzinfo is not None
                else video.published_at.replace(tzinfo=UTC)
            )
            age_days = max(0.0, (now_utc - pub_utc).total_seconds() / 86400.0)
            freshness = max(0.0, 1.0 - age_days / _FIVE_YEARS_DAYS)
        else:
            freshness = 0.0

        # Objective non-engagement quality signal (ADR-004 §6.2)
        desc_ok = 1.0 if len((video.description or "").strip()) >= 50 else 0.0
        tags_ok = 1.0 if len(video.tags or []) >= 3 else 0.0
        cat_ok = 1.0 if video.category_id is not None else 0.0
        capped_quality = (desc_ok + tags_ok + cat_ok) / 3.0

        known_lang = 1.0 if not unknown_lang else 0.0

        features = {
            "topic_match": topic_sim,
            "caption_availability": captions,
            "freshness": freshness,
            "capped_quality": capped_quality,
            "known_language": known_lang,
        }
        total = sum(features[name] * weights[name] for name in FR5_WEIGHTS)
        total_rounded = round(min(1.0, max(0.0, total)), 6)
        facts_missing = {
            "text": not has_text, "language": unknown_lang or not video.language,
            "has_captions": video.has_captions is None, "published_at": video.published_at is None,
            "description": video.description is None, "tags": video.tags is None,
            "category_id": not video.category_id,
        }
        explanation = explain_score(
            features, weights, shared_terms=shared,
            missing_fields=[name for name, missing in facts_missing.items() if missing],
            low_confidence=not has_text or primary_language(video.language) != "en",
        )

        scored.append(
            ScoredCandidate(
                video=video,
                score=total_rounded,
                components={name: round(value, 6) for name, value in features.items()},
                reason=explanation["reason"],
                explanation=explanation,
                unknown_language_flagged=unknown_lang,
            )
        )
    return scored


def _canonical_tie_key(
    indices: tuple[int, ...],
    ordered: list[ScoredCandidate],
    total_score: float,
    total_dur: int,
    target_dur: int,
) -> tuple[float, int, tuple[str, ...]]:
    """Deterministic maximization key: higher score, closer to target, lexicographical IDs."""
    # Negate abs diff and reverse lexical IDs via negation/comparison helper
    return (
        round(total_score, 6),
        -abs(total_dur - target_dur),
        tuple(sorted(ordered[i].video.video_id for i in indices)),
    )


def _is_better_solution(
    cand_score: float,
    cand_dur: int,
    cand_indices: tuple[int, ...],
    best_score: float,
    best_dur: int,
    best_indices: tuple[int, ...],
    ordered: list[ScoredCandidate],
    target_dur: int,
) -> bool:
    s_cand = round(cand_score, 6)
    s_best = round(best_score, 6)
    if s_cand != s_best:
        return s_cand > s_best
    err_cand = abs(cand_dur - target_dur)
    err_best = abs(best_dur - target_dur)
    if err_cand != err_best:
        return err_cand < err_best
    ids_cand = tuple(sorted(ordered[i].video.video_id for i in cand_indices))
    ids_best = tuple(sorted(ordered[i].video.video_id for i in best_indices))
    return ids_cand < ids_best


def _to_selected_items(
    indices: tuple[int, ...],
    ordered: list[ScoredCandidate],
    constraints: ValidatedPlaylistConstraints,
) -> list[SelectedPlaylistItem]:
    chosen = order_candidates([ordered[i] for i in indices], constraints.ordering)
    items: list[SelectedPlaylistItem] = []
    for idx, cand in enumerate(chosen, start=1):
        dur = cand.video.duration_seconds or 0
        explanation = cand.explanation
        items.append(
            SelectedPlaylistItem(
                order=idx,
                video_id=cand.video.video_id,
                title=cand.video.title,
                channel_id=cand.video.channel_id,
                channel_title=cand.video.channel_title,
                duration_seconds=dur,
                duration_iso=cand.video.duration_iso or format_duration_iso(dur),
                duration_display=format_duration_display(dur),
                score=cand.score,
                reason=cand.reason,
                untrusted=True,
                unknown_language_flagged=cand.unknown_language_flagged,
                components=explanation["components"] if explanation else {},
                feature_trace=explanation["feature_trace"] if explanation else {},
                shared_terms=explanation["shared_terms"] if explanation else [],
                missing_fields=explanation["missing_fields"] if explanation else [],
                low_confidence=explanation["low_confidence"] if explanation else False,
            )
        )
    return items


def solve_playlist(
    candidates: list[VideoRecord],
    constraints: ValidatedPlaylistConstraints,
    *,
    now: datetime | None = None,
    pre_scored: dict[str, float] | None = None,
    weights: Mapping[str, float] = FR5_WEIGHTS,
) -> SolverResult:
    """Pure deterministic bounded duration solver over hard-filtered candidates.

    Uses integer seconds and bounded DP with Pareto pruning (no network or storage).
    """
    ref_now = now or datetime(2026, 1, 1, tzinfo=UTC)
    eligible, dropped = filter_eligible_candidates(candidates, constraints)

    if pre_scored is not None:
        scored = [
            ScoredCandidate(
                video=video,
                score=round(min(1.0, max(0.0, pre_scored.get(video.video_id, 0.5))), 6),
                reason="Pre-scored candidate.",
                unknown_language_flagged=unknown_lang,
            )
            for video, unknown_lang in eligible
        ]
    else:
        scored = score_candidates_fr5(eligible, constraints, ref_now, weights=weights)

    scored, diversity_drops = diversify_candidates(scored)
    dropped.update(diversity_drops)
    # Sort deterministically so candidate permutation never changes solver outcome
    ordered = sorted(scored, key=lambda c: (-c.score, c.video.video_id))

    t_low = constraints.target_lower_seconds
    t_high = constraints.target_upper_seconds
    t_target = constraints.target_duration_seconds
    max_items = constraints.max_items

    # Track best feasible solution and nearest infeasible reachable duration
    best_feasible: tuple[float, int, tuple[int, ...]] | None = None
    nearest_under: tuple[int, float, tuple[int, ...]] | None = None

    # Sparse DP map: duration_seconds -> list of Pareto-optimal (count, score, indices)
    # Dominated if another state at the same duration has count <= c and score >= s.
    dp: dict[int, list[tuple[int, float, tuple[int, ...]]]] = {0: [(0, 0.0, ())]}

    # Precompute suffix max remaining duration to prune dead states early
    n = len(ordered)
    suffix_dur = [0] * (n + 1)
    for idx in range(n - 1, -1, -1):
        suffix_dur[idx] = suffix_dur[idx + 1] + (ordered[idx].video.duration_seconds or 0)

    for idx, cand in enumerate(ordered):
        d = cand.video.duration_seconds or 0
        s = cand.score
        if d > t_high:
            continue

        rem_dur = suffix_dur[idx + 1]
        new_states: list[tuple[int, int, float, tuple[int, ...]]] = []

        for cur_dur, bucket in dp.items():
            nxt_dur = cur_dur + d
            if nxt_dur > t_high:
                continue
            for count, cur_score, indices in bucket:
                if count >= max_items:
                    continue
                nxt_count = count + 1
                nxt_score = cur_score + s
                nxt_indices = indices + (idx,)

                if t_low <= nxt_dur <= t_high:
                    if best_feasible is None or _is_better_solution(
                        nxt_score,
                        nxt_dur,
                        nxt_indices,
                        best_feasible[0],
                        best_feasible[1],
                        best_feasible[2],
                        ordered,
                        t_target,
                    ):
                        best_feasible = (nxt_score, nxt_dur, nxt_indices)
                elif nxt_dur < t_low and (
                    nearest_under is None
                    or nxt_dur > nearest_under[0]
                    or (
                        nxt_dur == nearest_under[0]
                        and _is_better_solution(
                            nxt_score,
                            nxt_dur,
                            nxt_indices,
                            nearest_under[1],
                            nearest_under[0],
                            nearest_under[2],
                            ordered,
                            t_target,
                        )
                    )
                ):
                    nearest_under = (nxt_dur, nxt_score, nxt_indices)

                # Only propagate states that can still contribute or beat bounds
                if nxt_count < max_items and (nxt_dur + rem_dur >= t_low or best_feasible is None):
                    new_states.append((nxt_dur, nxt_count, nxt_score, nxt_indices))

        for nxt_dur, nxt_count, nxt_score, nxt_indices in new_states:
            next_bucket = dp.get(nxt_dur)
            if next_bucket is None:
                dp[nxt_dur] = [(nxt_count, nxt_score, nxt_indices)]
                continue
            # Check dominance
            dominated = False
            filtered_bucket: list[tuple[int, float, tuple[int, ...]]] = []
            for b_cnt, b_scr, b_idx in next_bucket:
                if b_cnt <= nxt_count and round(b_scr, 6) >= round(nxt_score, 6):
                    if b_cnt < nxt_count or round(b_scr, 6) > round(nxt_score, 6):
                        dominated = True
                        break
                    # Equal count & score: keep lexicographically better
                    ids_b = tuple(sorted(ordered[i].video.video_id for i in b_idx))
                    ids_n = tuple(sorted(ordered[i].video.video_id for i in nxt_indices))
                    if ids_b <= ids_n:
                        dominated = True
                        break
                if not (nxt_count <= b_cnt and round(nxt_score, 6) >= round(b_scr, 6)):
                    filtered_bucket.append((b_cnt, b_scr, b_idx))
            if not dominated:
                filtered_bucket.append((nxt_count, nxt_score, nxt_indices))
                dp[nxt_dur] = filtered_bucket

    warnings: list[str] = []
    if best_feasible is not None:
        score_val, dur_val, idx_tuple = best_feasible
        items = _to_selected_items(idx_tuple, ordered, constraints)
        if any(item.unknown_language_flagged for item in items):
            warnings.append("Some selected items have unknown language (explicitly allowed).")
        return SolverResult(
            feasible=True,
            selected_items=items,
            total_duration_seconds=dur_val,
            total_duration_iso=format_duration_iso(dur_val),
            total_duration_display=format_duration_display(dur_val),
            item_count=len(items),
            total_score=round(score_val, 6),
            nearest_achievable_seconds=dur_val,
            constraint_status={
                "status": "satisfied",
                "target_range_seconds": [t_low, t_high],
                "max_item_duration_seconds": constraints.max_item_duration_seconds,
                "min_item_duration_seconds": constraints.min_item_duration_seconds,
                "language": constraints.language,
                "max_items": max_items,
            },
            filtered_out_counts=dropped,
            warnings=warnings,
            sessions=pack_sessions(items, constraints.session_minutes),
        )

    # Infeasible: check if a single over-target or combined set was closest above t_high
    # (already bounded by d <= max_item_duration, and nearest_under holds max reachable < t_low)
    nearest_dur = nearest_under[0] if nearest_under is not None else 0
    nearest_items = _to_selected_items(
        nearest_under[2], ordered, constraints
    ) if nearest_under is not None else []
    deficit = nearest_dur - t_low

    unmet = [
        ConstraintViolation(
            constraint="target_duration",
            requested=f"{t_low}s to {t_high}s ({format_duration_display(t_low)}–{format_duration_display(t_high)})",
            achieved=f"{nearest_dur}s ({format_duration_display(nearest_dur)})",
            deficit_seconds=deficit,
        )
    ]

    return SolverResult(
        feasible=False,
        selected_items=[],
        total_duration_seconds=0,
        total_duration_iso="PT0S",
        total_duration_display="00:00",
        item_count=0,
        total_score=round(nearest_under[1], 6) if nearest_under is not None else 0.0,
        nearest_achievable_seconds=nearest_dur,
        nearest_items=nearest_items,
        constraint_status={
            "status": "infeasible",
            "target_range_seconds": [t_low, t_high],
            "max_item_duration_seconds": constraints.max_item_duration_seconds,
            "min_item_duration_seconds": constraints.min_item_duration_seconds,
            "language": constraints.language,
            "max_items": max_items,
        },
        unmet_constraints=unmet,
        filtered_out_counts=dropped,
        warnings=["Constraints could not be satisfied without relaxing hard filters."],
    )


def greedy_baseline_select(
    candidates: list[VideoRecord],
    constraints: ValidatedPlaylistConstraints,
    *,
    now: datetime | None = None,
    pre_scored: dict[str, float] | None = None,
) -> SolverResult:
    """Simple greedy-by-score baseline used to benchmark the DP solver in tests/docs."""
    ref_now = now or datetime(2026, 1, 1, tzinfo=UTC)
    eligible, dropped = filter_eligible_candidates(candidates, constraints)
    if pre_scored is not None:
        scored = [
            ScoredCandidate(
                video=video,
                score=round(min(1.0, max(0.0, pre_scored.get(video.video_id, 0.5))), 6),
                reason="Pre-scored candidate.",
                unknown_language_flagged=unknown_lang,
            )
            for video, unknown_lang in eligible
        ]
    else:
        scored = score_candidates_fr5(eligible, constraints, ref_now)

    ordered = sorted(scored, key=lambda c: (-c.score, c.video.video_id))
    chosen_indices: list[int] = []
    total_dur = 0
    total_score = 0.0
    for idx, cand in enumerate(ordered):
        d = cand.video.duration_seconds or 0
        if len(chosen_indices) >= constraints.max_items:
            break
        if total_dur + d <= constraints.target_upper_seconds:
            chosen_indices.append(idx)
            total_dur += d
            total_score += cand.score

    feasible = (
        constraints.target_lower_seconds <= total_dur <= constraints.target_upper_seconds
        and len(chosen_indices) > 0
    )
    items = _to_selected_items(tuple(chosen_indices), ordered, constraints) if feasible else []
    return SolverResult(
        feasible=feasible,
        selected_items=items,
        total_duration_seconds=total_dur if feasible else 0,
        total_duration_iso=format_duration_iso(total_dur) if feasible else "PT0S",
        total_duration_display=format_duration_display(total_dur) if feasible else "00:00",
        item_count=len(items),
        total_score=round(total_score, 6),
        nearest_achievable_seconds=total_dur,
        filtered_out_counts=dropped,
    )
