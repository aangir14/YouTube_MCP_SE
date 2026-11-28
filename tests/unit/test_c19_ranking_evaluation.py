"""Check the frozen paired artifact, metric arithmetic, and configurable trace contract."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from focuslist.config import Settings
from focuslist.discovery.evaluate_ranking import evaluate, relevance_metrics
from focuslist.discovery.scoring import explain_score
from focuslist.ranking_weights import VIDEO_WEIGHTS

_EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "testing"


def test_frozen_manifest_reproduces_saved_paired_evidence():
    data = (_EVIDENCE / "ranking-evaluation-seeds.json").read_bytes()
    observed = evaluate(data)
    saved = json.loads((_EVIDENCE / "ranking-evaluation-c19-results.json").read_bytes())
    assert observed == saved
    assert observed["seed_count"] == 20 and observed["directed_pairs"] == 380
    assert observed["weighted_delta_from_target"] == -0.07
    for seed in observed["seeds"]:
        candidates = seed["candidate_ids"]
        assert len(candidates) == 19 and seed["seed_id"] not in candidates
        for arm in ("tfidf_only", "weighted"):
            assert sorted(row["video_id"] for row in seed[arm]["ranking"]) == candidates

    invalid = json.loads(data)
    invalid["seeds"][0]["relevant_candidate_ids"].append(invalid["seeds"][0]["video_id"])
    with pytest.raises(ValueError, match="Invalid frozen relevance"):
        evaluate(json.dumps(invalid).encode())


@pytest.mark.parametrize(("labels", "precision", "rr"), [
    ([0, 1, 0, 1, 0], 0.4, 0.5),
    ([1, 0, 1, 0, 0], 0.4, 1.0),
    ([0] * 19, 0.0, 0.0),
    ([1], 0.2, 1.0),
    ([0, 0, 0, 0, 0, 1], 0.0, 1 / 6),
])
def test_metric_examples_and_full_reciprocal_rank(labels, precision, rr):
    assert relevance_metrics(labels) == {"precision_at_5": precision, "reciprocal_rank": rr}


def test_explanation_invariants_and_override_validation():
    raw = {name: 0.1 * i for i, name in enumerate(VIDEO_WEIGHTS)}
    common = {
        "shared_terms": ["z", "z", "a", "b", "c", "d", "e"],
        "missing_fields": ["tags", "language", "tags"], "low_confidence": True,
    }
    trace = explain_score(raw, VIDEO_WEIGHTS, **common)
    assert trace == explain_score(raw, VIDEO_WEIGHTS, **common)
    assert trace["shared_terms"] == ["z", "a", "b", "c", "d"]
    assert trace["missing_fields"] == ["language", "tags"] and trace["low_confidence"]
    assert len(trace["reason"]) <= 200
    assert math.isclose(sum(row["contribution"] for row in trace["feature_trace"].values()),
                        trace["score"], rel_tol=0.0, abs_tol=1e-6)

    for override in ({"similar_videos": {"text_cosine": 1}}, {"fake": {}},
                     {"similar_videos": {**VIDEO_WEIGHTS, "text_cosine": True}},
                     {"similar_videos": {**VIDEO_WEIGHTS, "text_cosine": 0.6}}):
        with pytest.raises(ValidationError):
            Settings(scoring_weights=override)
