"""Unit, boundary, baseline-comparison, and property tests for C12 curation solver."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from focuslist.curation import (
    greedy_baseline_select,
    solve_playlist,
    validate_proposal_arguments,
)
from focuslist.errors import InvalidArgumentsError, InvalidVideoIdError
from focuslist.types import VideoRecord

_REF_NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def _make_video(
    vid: str,
    *,
    title: str = "Recursion Tutorial",
    duration: int = 600,
    language: str | None = "en",
    channel_id: str = "UC_chan_000000000000001",
    tags: list[str] | None = None,
    has_captions: bool | None = True,
    is_live: bool = False,
    is_upcoming: bool = False,
    is_age_restricted: bool = False,
) -> VideoRecord:
    return VideoRecord(
        video_id=vid,
        canonical_url=f"https://www.youtube.com/watch?v={vid}",
        title=title,
        channel_id=channel_id,
        channel_title="CS Academy",
        description="A clear, structured explanation of recursion and base cases in Python.",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        duration_seconds=duration,
        duration_iso=f"PT{duration}S",
        tags=tags if tags is not None else ["recursion", "algorithms", "python"],
        category_id="27",
        language=language,
        is_live=is_live,
        is_upcoming=is_upcoming,
        is_age_restricted=is_age_restricted,
        has_captions=has_captions,
    )


# ==============================================================================
# 1. Schema & Argument Validation Tests
# ==============================================================================


def test_validate_two_hour_twenty_minute_defaults() -> None:
    """Verify baseline 2h/20m request applies SRS defaults (en, 5%, 30 items, private)."""
    c = validate_proposal_arguments(
        {
            "topic": "  recursion  ",
            "target_duration": "PT2H",
            "max_item_duration": "PT20M",
        }
    )
    assert c.topic == "recursion"
    assert c.target_duration_seconds == 7200
    assert c.target_lower_seconds == 6840
    assert c.target_upper_seconds == 7560
    assert c.max_item_duration_seconds == 1200
    assert c.min_item_duration_seconds == 120
    assert c.language == "en"
    assert c.max_items == 30
    assert c.privacy_status == "private"
    assert c.ordering == "learning_path"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"topic": "", "target_duration": "PT1H", "max_item_duration": "PT20M"},
        {"topic": "   ", "target_duration": "PT1H", "max_item_duration": "PT20M"},
        {"topic": "a" * 201, "target_duration": "PT1H", "max_item_duration": "PT20M"},
        {"topic": "recursion", "target_duration": "PT0S", "max_item_duration": "PT20M"},
        {"topic": "recursion", "target_duration": "-PT1H", "max_item_duration": "PT20M"},
        {"topic": "recursion", "target_duration": "PT1H", "max_item_duration": "PT0M"},
        {
            "topic": "recursion",
            "target_duration": "PT1H",
            "min_item_duration": "PT25M",
            "max_item_duration": "PT20M",
        },
        {
            "topic": "recursion",
            "target_duration": "PT10M",
            "min_item_duration": "PT15M",
            "max_item_duration": "PT20M",
        },
        {"topic": "recursion", "target_duration": "PT1H", "max_item_duration": "PT20M", "max_items": 51},
        {"topic": "recursion", "target_duration": "PT1H", "max_item_duration": "PT20M", "max_items": 0},
        {"topic": "recursion", "target_duration": "PT1H", "max_item_duration": "PT20M", "max_items": True},
        {"topic": "recursion", "target_duration": "PT1H", "max_item_duration": "PT20M", "language": "und"},
        {"topic": "recursion", "target_duration": "PT1H", "max_item_duration": "PT20M", "unknown_key": 1},
        {"topic": "recursion", "target_duration": "PT1H", "max_item_duration": "PT20M", "seed": "bad_id"},
    ],
)
def test_validate_rejects_invalid_and_contradictory_arguments(bad_payload: dict) -> None:
    """Verify malformed, unknown, and contradictory constraints fail with FocusList validation errors."""
    with pytest.raises((InvalidArgumentsError, InvalidVideoIdError)):
        validate_proposal_arguments(bad_payload)


# ==============================================================================
# 2. Boundary & Acceptance Solver Tests
# ==============================================================================


def test_solver_two_hour_twenty_minute_baseline_with_hard_filters() -> None:
    """12x10m English recursion videos solve 2h exact; ineligible candidates are excluded."""
    constraints = validate_proposal_arguments(
        {
            "topic": "recursion",
            "target_duration": "PT2H",
            "max_item_duration": "PT20M",
            "language": "en",
        }
    )
    candidates = [_make_video(f"rec_vid_{i:03d}", duration=600) for i in range(1, 13)]
    # Add ineligible items that must be hard-filtered
    candidates.extend(
        [
            _make_video("rec_vid_001", duration=600),  # duplicate
            _make_video("bad_live001", duration=600, is_live=True),
            _make_video("bad_upcm001", duration=600, is_upcoming=True),
            _make_video("bad_age_001", duration=600, is_age_restricted=True),
            _make_video("bad_long001", duration=1500),  # 25m > 20m cap
            _make_video("bad_shrt001", duration=60),  # 1m < 2m min
            _make_video("bad_lang001", duration=600, language="es"),
            _make_video("bad_unkl001", duration=600, language=None),
        ]
    )

    res = solve_playlist(candidates, constraints, now=_REF_NOW)
    assert res.feasible is True
    assert res.item_count == 12
    assert res.total_duration_seconds == 7200
    assert res.total_duration_iso == "PT2H"
    assert res.constraint_status["status"] == "satisfied"
    assert all(item.video_id.startswith("rec_vid_") for item in res.selected_items)
    assert res.filtered_out_counts["duplicate"] == 1
    assert res.filtered_out_counts["live_or_upcoming"] == 2
    assert res.filtered_out_counts["age_restricted"] == 1
    assert res.filtered_out_counts["duration_out_of_range"] == 2
    assert res.filtered_out_counts["language_mismatch"] == 2


def test_solver_exact_window_bounds() -> None:
    """Verify tolerance bounds [6840, 7560] accept boundary values and reject 1s outside."""
    constraints = validate_proposal_arguments(
        {"topic": "recursion", "target_duration": "PT2H", "max_item_duration": "PT20M"}
    )
    # 6 items of 1140s = 6840s (exact lower bound)
    low_ok = solve_playlist(
        [_make_video(f"low_{i:07d}", duration=1140) for i in range(6)],
        constraints,
        now=_REF_NOW,
    )
    assert low_ok.feasible is True
    assert low_ok.total_duration_seconds == 6840

    # 7 items of 1080s = 7560s (exact upper bound)
    high_ok = solve_playlist(
        [_make_video(f"hi_{i:08d}", duration=1080) for i in range(7)],
        constraints,
        now=_REF_NOW,
    )
    assert high_ok.feasible is True
    assert high_ok.total_duration_seconds == 7560

    # 6839s (1s below lower bound) -> infeasible
    too_short = solve_playlist(
        [_make_video(f"sh_{i:08d}", duration=1139) for i in range(5)]
        + [_make_video("sh_00000005", duration=1144)],
        constraints,
        now=_REF_NOW,
    )
    assert too_short.feasible is False
    assert too_short.nearest_achievable_seconds == 6839
    assert too_short.unmet_constraints[0].deficit_seconds == -1


def test_solver_unknown_language_policy() -> None:
    """Unknown-language videos require allow_unknown_language=True and emit a warning."""
    strict_c = validate_proposal_arguments(
        {"topic": "recursion", "target_duration": "PT20M", "max_item_duration": "PT20M"}
    )
    unk_vids = [_make_video(f"unk_{i:07d}", duration=600, language=None) for i in range(2)]
    res_strict = solve_playlist(unk_vids, strict_c, now=_REF_NOW)
    assert res_strict.feasible is False

    permissive_c = validate_proposal_arguments(
        {
            "topic": "recursion",
            "target_duration": "PT20M",
            "max_item_duration": "PT20M",
            "allow_unknown_language": True,
        }
    )
    res_perm = solve_playlist(unk_vids, permissive_c, now=_REF_NOW)
    assert res_perm.feasible is True
    assert all(item.unknown_language_flagged for item in res_perm.selected_items)
    assert res_perm.warnings


def test_solver_max_50_items_cap_enforced() -> None:
    """60 short 2m videos for a 2h target cannot exceed 50 items (100m < 114m -> infeasible)."""
    constraints = validate_proposal_arguments(
        {
            "topic": "recursion",
            "target_duration": "PT2H",
            "max_item_duration": "PT20M",
            "max_items": 50,
        }
    )
    candidates = [_make_video(f"vid_{i:07d}", duration=120) for i in range(60)]
    res = solve_playlist(candidates, constraints, now=_REF_NOW)
    assert res.feasible is False
    assert res.nearest_achievable_seconds == 50 * 120
    assert len(res.nearest_items) == 50


def test_solver_determinism_under_permutation_and_ties() -> None:
    """Shuffling input candidates yields identical selected video IDs and total score."""
    constraints = validate_proposal_arguments(
        {"topic": "recursion", "target_duration": "PT30M", "max_item_duration": "PT15M"}
    )
    candidates = [_make_video(f"tie_{i:07d}", duration=600) for i in range(10)]
    scores = {v.video_id: 0.85 for v in candidates}

    base = solve_playlist(candidates, constraints, pre_scored=scores)
    assert base.feasible is True
    base_ids = [item.video_id for item in base.selected_items]

    rng = random.Random(42)
    for _ in range(10):
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        alt = solve_playlist(shuffled, constraints, pre_scored=scores)
        assert [item.video_id for item in alt.selected_items] == base_ids
        assert alt.total_score == base.total_score


def test_solver_beats_greedy_baseline_on_shortlist() -> None:
    """DP solver finds a feasible higher-value solution where greedy fails to hit window."""
    # Target: 30m (1800s ± 5% -> 1710..1890s), max item 20m (1200s)
    constraints = validate_proposal_arguments(
        {"topic": "recursion", "target_duration": "PT30M", "max_item_duration": "PT20M"}
    )
    # Candidate A: 1100s, score 0.90 (greedy picks A first, leaving 790s max)
    # Candidate B, C: 900s each, score 0.80 each (together 1800s, total score 1.60 -> feasible!)
    # Candidate D: 500s, score 0.50 (with A = 1600s < 1710s -> greedy misses window!)
    vids = [
        _make_video("vid_A000001", duration=1100),
        _make_video("vid_B000002", duration=900),
        _make_video("vid_C000003", duration=900),
        _make_video("vid_D000004", duration=500),
    ]
    scores = {"vid_A000001": 0.90, "vid_B000002": 0.80, "vid_C000003": 0.80, "vid_D000004": 0.50}

    greedy_res = greedy_baseline_select(vids, constraints, pre_scored=scores)
    dp_res = solve_playlist(vids, constraints, pre_scored=scores)

    assert greedy_res.feasible is False
    assert dp_res.feasible is True
    assert dp_res.total_duration_seconds == 1800
    assert {item.video_id for item in dp_res.selected_items} == {"vid_B000002", "vid_C000003"}


# ==============================================================================
# 3. Deterministic Property Tests (250 Generated Cases)
# ==============================================================================


def test_solver_property_invariants_across_250_cases() -> None:
    """Verify hard-filter, bound, uniqueness, and determinism invariants across 250 cases."""
    rng = random.Random(20261125)
    for case_idx in range(250):
        target_min = rng.randint(15, 90)
        max_item_min = rng.randint(5, 20)
        min_item_min = rng.randint(2, min(5, max_item_min))
        max_items = rng.randint(3, 25)
        constraints = validate_proposal_arguments(
            {
                "topic": "algorithms",
                "target_duration": f"PT{target_min}M",
                "max_item_duration": f"PT{max_item_min}M",
                "min_item_duration": f"PT{min_item_min}M",
                "max_items": max_items,
            }
        )

        pool_size = rng.randint(4, 24)
        pool: list[VideoRecord] = []
        scores: dict[str, float] = {}
        for j in range(pool_size):
            vid = f"p_{case_idx:03d}_{j:04d}"
            dur = rng.randint(60, 1500)
            lang = rng.choice(["en", "en", "en", "es", None])
            pool.append(_make_video(vid, duration=dur, language=lang))
            scores[vid] = round(rng.uniform(0.1, 1.0), 4)

        res = solve_playlist(pool, constraints, pre_scored=scores)
        if res.feasible:
            assert (
                constraints.target_lower_seconds
                <= res.total_duration_seconds
                <= constraints.target_upper_seconds
            )
            assert 1 <= res.item_count <= constraints.max_items <= 50
            ids = [item.video_id for item in res.selected_items]
            assert len(ids) == len(set(ids))
            assert sum(item.duration_seconds for item in res.selected_items) == (
                res.total_duration_seconds
            )
            for item in res.selected_items:
                assert (
                    constraints.min_item_duration_seconds
                    <= item.duration_seconds
                    <= constraints.max_item_duration_seconds
                )
        else:
            assert res.selected_items == []
            assert res.unmet_constraints
            assert res.nearest_achievable_seconds < constraints.target_lower_seconds
