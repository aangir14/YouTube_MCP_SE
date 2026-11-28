"""Reproduce the C08 paired FR-1 evaluation with no provider or network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from focuslist.discovery.videos import build_video_corpus, rank_similar_videos
from focuslist.metadata import normalise_video_record, video_watch_url
from focuslist.ranking_weights import VIDEO_WEIGHTS
from focuslist.types import VideoRecord

_BASELINE_WEIGHTS = {name: float(name == "text_cosine") for name in VIDEO_WEIGHTS}
_TARGET = 0.60
_FROZEN_CLOCK = datetime(2026, 11, 25, tzinfo=UTC)


def relevance_metrics(labels: list[int]) -> dict[str, float]:
    return {
        "precision_at_5": sum(labels[:5]) / 5,
        "reciprocal_rank": next((1 / rank for rank, label in enumerate(labels, 1) if label), 0.0),
    }


def _record(seed: dict[str, Any], fixture: dict[str, Any]) -> VideoRecord:
    return normalise_video_record(VideoRecord(
        video_id=seed["video_id"], canonical_url=video_watch_url(seed["video_id"]),
        title=seed["title"], description=seed["description"], channel_id=fixture["channel_key"],
        channel_title="MIT OpenCourseWare fixture", language=fixture["language"],
        duration_seconds=fixture["duration_seconds"], published_at=fixture["published_at"],
        tags=fixture["tags"], category_id=fixture["category_id"], visibility="public",
    ))


def _ranked_arm(
    seed: VideoRecord,
    candidates: list[VideoRecord],
    corpus: dict[str, dict[str, float]],
    weights: dict[str, float],
    relevant: set[str],
) -> dict[str, Any]:
    ranked = rank_similar_videos(seed, candidates, weights=weights, corpus=corpus)
    ids = [row["item_id"] for row in ranked]
    if len(ids) != len(candidates) or set(ids) != {v.video_id for v in candidates}:
        raise ValueError("Ranked IDs did not match the frozen candidate pool.")
    if ranked != rank_similar_videos(seed, list(reversed(candidates)), weights=weights, corpus=corpus):
        raise ValueError("Ranking changed when the same candidate pool was reversed.")
    labels = [int(vid in relevant) for vid in ids]
    ordering = [
        {"video_id": vid, "score": row["score"], "relevant": label}
        for vid, row, label in zip(ids, ranked, labels, strict=True)
    ]
    return {
        **relevance_metrics(labels),
        "adjacent_score_ties": len(ordering) - len({row["score"] for row in ordering}),
        "ranking": ordering,
    }


def evaluate(manifest: bytes) -> dict[str, Any]:
    data = json.loads(manifest)
    seeds = data["seeds"]
    ids = {seed["video_id"] for seed in seeds}
    sources = {seed["source"] for seed in seeds}
    if (
        data["version"] != "c08-mit6006-v1" or len(seeds) != 20 or len(ids) != len(seeds)
        or len(sources) != len(seeds)
        or any(not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) for vid in ids)
        or any(urlsplit(src).scheme != "https" or not urlsplit(src).hostname for src in sources)
    ):
        raise ValueError("Expected the 20 unique public C08 v1 seeds and source URLs.")

    records = {seed["video_id"]: _record(seed, data["shared_fixture_metadata"]) for seed in seeds}
    rows = []
    for annotation in seeds:
        seed_id = annotation["video_id"]
        ordered_ids = sorted(ids - {seed_id})
        positives = annotation["relevant_candidate_ids"]
        relevant = set(positives)
        if not relevant or len(relevant) != len(positives) or not relevant < set(ordered_ids):
            raise ValueError(f"Invalid frozen relevance labels for {seed_id}.")
        seed = records[seed_id]
        candidates = [records[vid] for vid in ordered_ids]
        corpus = build_video_corpus([seed, *candidates])
        baseline = _ranked_arm(seed, candidates, corpus, _BASELINE_WEIGHTS, relevant)
        weighted = _ranked_arm(seed, candidates, corpus, VIDEO_WEIGHTS, relevant)
        rows.append({
            "seed_id": seed_id, "candidate_ids": ordered_ids, "positive_count": len(relevant),
            "tfidf_only": baseline, "weighted": weighted,
            "delta_precision_at_5": round(weighted["precision_at_5"] - baseline["precision_at_5"], 12),
            "delta_reciprocal_rank": round(weighted["reciprocal_rank"] - baseline["reciprocal_rank"], 12),
        })

    aggregates = {
        arm: {
            "precision_at_5": round(fmean(row[arm]["precision_at_5"] for row in rows), 12),
            "mrr": round(fmean(row[arm]["reciprocal_rank"] for row in rows), 12),
            "adjacent_score_ties": sum(row[arm]["adjacent_score_ties"] for row in rows),
        }
        for arm in ("tfidf_only", "weighted")
    }
    aggregates["weighted_minus_baseline"] = {
        key: round(aggregates["weighted"][key] - aggregates["tfidf_only"][key], 12)
        for key in ("precision_at_5", "mrr")
    }
    return {
        "manifest_version": data["version"],
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "seed_count": len(rows), "candidates_per_seed": 19, "directed_pairs": 19 * len(rows),
        "weights": {"tfidf_only": _BASELINE_WEIGHTS, "weighted": VIDEO_WEIGHTS},
        "provisional_precision_at_5_target": _TARGET,
        "weighted_delta_from_target": round(aggregates["weighted"]["precision_at_5"] - _TARGET, 12),
        "aggregate": aggregates, "seeds": rows,
    }


def benchmark() -> dict[str, Any]:
    """Measure 20 full 150-candidate weighted ranks with deterministic synthetic inputs."""
    records = [
        VideoRecord(
            video_id=f"bench{i:06d}", canonical_url=video_watch_url(f"bench{i:06d}"),
            title=f"Recursion graph {i % 23} lecture {i}", description=f"Example {i % 13} sorting",
            channel_id=f"channel-{i % 11}", channel_title="Benchmark fixture", language="en",
            published_at=_FROZEN_CLOCK, duration_seconds=300 + i * 4, tags=["graph", f"tag-{i % 5}"],
            category_id=str(20 + i % 4),
        )
        for i in range(151)
    ]
    seed, candidates = records[0], records[1:]
    rank_similar_videos(seed, candidates)
    elapsed = []
    for _ in range(20):
        before = perf_counter()
        rank_similar_videos(seed, candidates)
        elapsed.append(1000 * (perf_counter() - before))
    p95 = sorted(elapsed)[math.ceil(0.95 * len(elapsed)) - 1]
    return {
        "runs": len(elapsed), "candidates": len(candidates), "p95_ms": round(p95, 3),
        "mean_ms": round(fmean(elapsed), 3), "p95_method": "nearest rank",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.manifest.read_bytes())
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["aggregate"], indent=2))
    if args.benchmark:
        print(json.dumps(benchmark(), indent=2))


if __name__ == "__main__":
    main()
