"""FR-8 diversity, ordering and study sessions for the duration solver."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from focuslist.types import format_duration_display

if TYPE_CHECKING:
    from focuslist.curation.solver import ScoredCandidate, SelectedPlaylistItem

_EPISODE = re.compile(r"(?:\b(?:part|episode|lesson|lecture|module)\s*#?\s*|#)(\d{1,4})\b")
_INTRO = {"intro", "introduction", "beginner", "basics", "fundamentals", "getting started"}
_ADVANCED = {"advanced", "expert", "optimisation", "optimization", "masterclass"}


class StudySession(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int
    video_ids: list[str]
    total_duration_seconds: int
    total_duration: str
    oversized: bool


def _tokens(title: str) -> Counter[str]:
    return Counter(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", title).casefold()))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    norm = math.sqrt(sum(x * x for x in left.values()) * sum(x * x for x in right.values()))
    return sum(count * right[word] for word, count in left.items()) / norm if norm else 0.0


def _relevance(item: ScoredCandidate) -> tuple[float, str]:
    return (-item.score, item.video.video_id)


def diversify_candidates(
    scored: list[ScoredCandidate],
) -> tuple[list[ScoredCandidate], dict[str, int]]:
    """Collapse near-duplicates by relevance, then admit three per known channel using MMR."""
    vectors = {item.video.video_id: _tokens(item.video.title) for item in scored}
    similarities: dict[tuple[str, str], float] = {}

    def similarity(left: str, right: str) -> float:
        key = (left, right) if left < right else (right, left)
        if key not in similarities:
            similarities[key] = _cosine(vectors[left], vectors[right])
        return similarities[key]

    candidates: dict[str, ScoredCandidate] = {}
    for item in sorted(scored, key=_relevance):
        video_id = item.video.video_id
        if all(similarity(video_id, seen) < 0.90 for seen in candidates):
            candidates[video_id] = item
    duplicates = len(scored) - len(candidates)

    selected: list[ScoredCandidate] = []
    counts: Counter[str] = Counter()
    redundancy = dict.fromkeys(candidates, 0.0)
    capped = 0
    while candidates:
        best_id = min(
            candidates,
            key=lambda vid: (
                -(0.7 * candidates[vid].score - 0.3 * redundancy[vid]),
                *_relevance(candidates[vid]),
            ),
        )
        best = candidates.pop(best_id)
        channel = best.video.channel_id
        if channel and counts[channel] == 3:
            capped += 1
            continue
        if channel:
            counts[channel] += 1
        selected.append(best)
        for vid in candidates:
            redundancy[vid] = max(redundancy[vid], similarity(vid, best_id))

    return selected, {"near_duplicate_title": duplicates, "channel_cap": capped}


def _difficulty(title: str) -> int:
    text = title.casefold()
    terms = _tokens(text)
    if any(cue in terms for cue in _ADVANCED):
        return 2
    return 0 if any(cue in terms for cue in _INTRO) or "getting started" in text else 1


def order_candidates(
    chosen: list[ScoredCandidate],
    ordering: Literal["learning_path", "relevance", "chronological"],
) -> list[ScoredCandidate]:
    """Order the chosen set without changing membership."""
    ranked = sorted(chosen, key=_relevance)
    if ordering == "relevance":
        return ranked
    if ordering == "chronological":
        return sorted(ranked, key=lambda c: c.video.published_at or datetime.max.replace(tzinfo=UTC))

    groups: list[list[ScoredCandidate]] = []
    series: dict[str, list[list[tuple[int, Counter[str], ScoredCandidate]]]] = defaultdict(list)
    for item in ranked:
        title = unicodedata.normalize("NFKC", item.video.title).casefold()
        match = _EPISODE.search(title)
        if match is None or not item.video.channel_id:
            groups.append([item])
            continue
        number = int(match[1])
        title_tokens = _tokens(title[:match.start()] + " " + title[match.end():])
        channel_groups = series[item.video.channel_id]
        for group in channel_groups:
            if all(number != other and _cosine(title_tokens, tokens) >= 0.60
                   for other, tokens, _ in group):
                group.append((number, title_tokens, item))
                break
        else:
            channel_groups.append([(number, title_tokens, item)])

    for channel_groups in series.values():
        for group in channel_groups:
            groups.append([item for _, _, item in sorted(group, key=lambda entry: entry[0])])
    groups.sort(key=lambda group: (
        min(_difficulty(item.video.title) for item in group),
        min(_relevance(item) for item in group),
    ))
    return [item for group in groups for item in group]


def pack_sessions(
    items: list[SelectedPlaylistItem], target_minutes: int | None
) -> list[StudySession]:
    """Pack consecutive whole items and give each oversized item its own session."""
    if target_minutes is None:
        return []
    cap = target_minutes * 60
    sessions: list[StudySession] = []
    ids: list[str] = []
    total = 0

    def finish() -> None:
        sessions.append(StudySession(
            number=len(sessions) + 1,
            video_ids=ids,
            total_duration_seconds=total,
            total_duration=format_duration_display(total),
            oversized=total > cap,
        ))

    for item in items:
        if ids and total + item.duration_seconds > cap:
            finish()
            ids, total = [], 0
        ids.append(item.video_id)
        total += item.duration_seconds
    if ids:
        finish()
    return sessions
