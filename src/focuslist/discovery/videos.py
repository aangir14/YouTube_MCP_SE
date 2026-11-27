"""FR-1 video facts, bounded candidate retrieval, and local C08 similarity."""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from functools import partial
from threading import Lock
from typing import Any, TypeVar

from focuslist.context import RequestContext
from focuslist.errors import (
    ChannelUnavailableError,
    FocusListError,
    InvalidArgumentsError,
    InvalidChannelIdError,
    InvalidVideoIdError,
    QuotaBudgetExceededError,
    VideoUnavailableError,
)
from focuslist.metadata import (
    normalise_video_record,
    parse_channel_reference,
    parse_video_id,
    primary_language,
    same_primary_language,
    video_watch_url,
)
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.provider import VideoProvider
from focuslist.types import VideoRecord

_PAGE = 50
_CANDIDATE_CAP = 150
_SEARCH_CAP = 2
_GENERAL_CAP = 6
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)
VIDEO_WEIGHTS = {
    "text_cosine": 0.50,
    "tag_overlap": 0.15,
    "category_match": 0.10,
    "duration_fit": 0.10,
    "language_match": 0.10,
    "same_channel": 0.05,
}
_EARLIEST = datetime.min.replace(tzinfo=UTC)
_T = TypeVar("_T")


def _tokens(text: str, language: str | None) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = "".join(c if c.isalnum() else " " for c in normalized).split()
    if primary_language(language) == "en":
        return [word for word in words if word not in _STOP_WORDS]
    return words


def _vectors(records: Sequence[VideoRecord]) -> dict[str, dict[str, float]]:
    documents = {
        video.video_id: Counter(
            _tokens(
                " ".join([video.title, video.description or "", *(video.tags or [])]),
                video.language,
            )
        )
        for video in records
    }
    frequency = Counter(term for document in documents.values() for term in document)
    vectors = {}
    for video_id, document in documents.items():
        weights = {
            term: count * (math.log((1 + len(documents)) / (1 + frequency[term])) + 1)
            for term, count in document.items()
        }
        norm = math.sqrt(math.fsum(value * value for value in weights.values()))
        vectors[video_id] = {term: value / norm for term, value in weights.items()} if norm else {}
    return vectors


def _tag_set(tags: list[str] | None) -> set[str]:
    return {unicodedata.normalize("NFKC", tag).casefold().strip() for tag in tags or ()}


def _pair_facts(video: VideoRecord, text: dict[str, float]) -> dict[str, bool]:
    return {
        "text": bool(text),
        "tags": video.tags is not None,
        "category_id": bool(video.category_id),
        "duration_seconds": video.duration_seconds is not None,
        "language": primary_language(video.language) is not None,
        "channel_id": bool(video.channel_id),
    }


def _video_fields(video: VideoRecord) -> dict[str, Any]:
    return {
        "video_id": video.video_id,
        "canonical_url": video_watch_url(video.video_id),
        "title": video.title,
        "channel_title": video.channel_title,
        "channel_id": video.channel_id or None,
        "duration": video.duration_display,
        "duration_seconds": video.duration_seconds,
        "duration_iso": video.duration_iso,
        "language": video.language,
        "language_provenance": video.language_provenance,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "untrusted_metadata": True,
    }


def rank_similar_videos(
    seed: VideoRecord, candidates: Sequence[VideoRecord]
) -> list[dict[str, Any]]:
    """Score an eligible, deduplicated set using one fixed C08 corpus and no I/O."""
    vectors = _vectors([seed, *candidates])
    seed_vector = vectors[seed.video_id]
    seed_facts = _pair_facts(seed, seed_vector)
    seed_tags = _tag_set(seed.tags)
    ranked = []
    for candidate in candidates:
        vector = vectors[candidate.video_id]
        facts = _pair_facts(candidate, vector)
        products = {
            term: weight * seed_vector[term]
            for term, weight in vector.items()
            if term in seed_vector
        }
        shared = sorted(products, key=lambda term: (-products[term], term))[:5]
        tags = _tag_set(candidate.tags)
        tag_union = seed_tags | tags
        seed_duration, duration = seed.duration_seconds, candidate.duration_seconds
        raw = {
            "text_cosine": min(1.0, math.fsum(products.values())),
            "tag_overlap": (
                len(seed_tags & tags) / len(tag_union)
                if seed_facts["tags"] and facts["tags"] and tag_union
                else 0.0
            ),
            "category_match": float(
                seed_facts["category_id"] and seed.category_id == candidate.category_id
            ),
            "duration_fit": (
                min(seed_duration, duration) / max(seed_duration, duration)
                if seed_duration and duration
                else 0.0
            ),
            "language_match": float(
                same_primary_language(seed.language, candidate.language) is True
            ),
            "same_channel": float(
                seed_facts["channel_id"] and seed.channel_id == candidate.channel_id
            ),
        }
        trace = {
            name: {"raw": raw[name], "weight": weight, "contribution": raw[name] * weight}
            for name, weight in VIDEO_WEIGHTS.items()
        }
        score = round(math.fsum(factor["contribution"] for factor in trace.values()), 6)
        missing = sorted(
            [name for name, present in facts.items() if not present]
            + [f"seed.{name}" for name, present in seed_facts.items() if not present]
            + (["published_at"] if candidate.published_at is None else [])
        )
        low_confidence = (
            not all(seed_facts.values())
            or not all(facts.values())
            or primary_language(seed.language) != "en"
            or primary_language(candidate.language) != "en"
        )
        positives = sorted(
            (name for name in trace if trace[name]["contribution"] > 0),
            key=lambda name: (-trace[name]["contribution"], name),
        )
        reason = (
            "Strongest signals: "
            + ", ".join(name.replace("_", " ") for name in positives[:3])
            + "."
            if positives
            else "No positive similarity signals in the available metadata."
        )
        item = {
            **_video_fields(candidate),
            "item_id": candidate.video_id,
            "score": score,
            "reason": reason,
            "components": dict(VIDEO_WEIGHTS),
            "feature_trace": trace,
            "shared_terms": shared,
            "missing_fields": missing,
            "low_confidence": low_confidence,
        }
        ranked.append((item, candidate.published_at))

    # Stable passes preserve case-sensitive ID order after comparing dates and scores.
    ranked.sort(key=lambda row: row[0]["item_id"])
    ranked.sort(key=lambda row: (row[1] is not None, row[1] or _EARLIEST), reverse=True)
    ranked.sort(key=lambda row: row[0]["score"], reverse=True)
    return [{**item, "rank": rank} for rank, (item, _) in enumerate(ranked, 1)]


def _eligible(video: VideoRecord) -> bool:
    return (
        video.visibility == "public"
        and video.is_live is False
        and video.is_upcoming is False
        and video.is_age_restricted is False
        and video.duration_seconds is not None
        and video.duration_seconds >= 60
    )


def _search_queries(seed: VideoRecord) -> list[str]:
    queries = []
    for text in (seed.title, " ".join(seed.tags or []), seed.description or ""):
        terms = list(dict.fromkeys(_tokens(text, seed.language)))[:6]
        query = " ".join(terms)[:160].strip()
        if query and query not in queries:
            queries.append(query)
        if len(queries) == _SEARCH_CAP:
            break
    return queries


def _candidate_ids(seed_id: str, pages: Iterable[Sequence[str]]) -> list[str]:
    ids: dict[str, None] = {}
    for page in pages:
        for value in page[:_PAGE]:
            try:
                video_id = parse_video_id(value)
            except InvalidVideoIdError:
                continue
            if video_id == value and video_id != seed_id:
                ids.setdefault(video_id, None)
            if len(ids) == _CANDIDATE_CAP:
                return list(ids)
    return list(ids)


class VideoDiscovery:
    """FR-1 service using the shared provider and C07 response context."""

    def __init__(self, provider: VideoProvider, context: RequestContext) -> None:
        self.provider = provider
        self.ctx = context
        self.search_calls_used = 0
        self._lock = Lock()

    def tool_response(self, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Serialize FR-1 admission against the process-local C07 counters."""
        with self._lock:
            before_units, before_searches = self.ctx.quota_used, self.search_calls_used
            before_hits = self.ctx.cache_hits
            try:
                result = operation()
            except FocusListError as exc:
                payload = self.ctx.failure(exc).model_dump()
            else:
                payload = self.ctx.success(result).model_dump()
            payload["meta"]["quota_used"] = self.ctx.quota_used - before_units
            payload["meta"]["search_calls"] = self.search_calls_used - before_searches
            payload["meta"]["cache_hits"] = self.ctx.cache_hits - before_hits
            return payload

    def _preflight(self, general: int, searches: int = 0) -> None:
        if isinstance(self.provider, ProviderGateway):
            return
        settings = self.ctx.settings
        available = (
            settings.daily_general_quota
            - math.ceil(settings.daily_general_quota * settings.quota_safety_margin)
            - self.ctx.quota_used
        )
        if (
            general > min(available, settings.request_unit_cap)
            or searches > settings.daily_search_quota - self.search_calls_used
        ):
            raise QuotaBudgetExceededError()

    def _read(self, operation: Callable[[], _T], *, search: bool = False) -> _T:
        before = self.provider.network_attempts
        before_hits = getattr(self.provider, "cache_hits", 0)
        try:
            return operation()
        finally:
            attempts = self.provider.network_attempts - before
            hits = getattr(self.provider, "cache_hits", 0) - before_hits
            if hits > 0:
                self.ctx.record_cache_hit(hits)
            if search:
                self.search_calls_used += attempts
            else:
                self.ctx.record_quota_charge(attempts)
            if isinstance(self.provider, ProviderGateway):
                self.ctx.set_quota_remaining(
                    self.provider.quota_manager.get_status().general_units_remaining
                )

    def _seed(self, video_id: str) -> VideoRecord:
        records = self._read(lambda: self.provider.get_video_details([video_id]))
        for record in records:
            if record.video_id == video_id and record.visibility != "private":
                return normalise_video_record(record)
        raise VideoUnavailableError()

    def details(self, reference: str) -> dict[str, Any]:
        video_id = parse_video_id(reference)
        if isinstance(self.provider, ProviderGateway):
            with self.provider.operation_budget(1, 0):
                video = self._seed(video_id)
        else:
            self._preflight(1)
            video = self._seed(video_id)
        facts = {
            "description": video.description,
            "tags": video.tags,
            "category_id": video.category_id,
            "view_count": video.view_count,
            "like_count": video.like_count,
            "has_captions": video.has_captions,
            "visibility": video.visibility,
            "is_live": video.is_live,
            "is_upcoming": video.is_upcoming,
            "is_age_restricted": video.is_age_restricted,
        }
        fields = {**_video_fields(video), **facts}
        fields["missing_fields"] = sorted(name for name, value in fields.items() if value is None)
        return fields

    def similar(self, reference: str, limit: int) -> dict[str, Any]:
        video_id = parse_video_id(reference)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise InvalidArgumentsError("Limit must be an integer between 1 and 50.")

        def _run_similar() -> dict[str, Any]:
            seed = self._seed(video_id)

            pages = []
            for query in _search_queries(seed):
                pages.append(
                    self._read(
                        partial(self.provider.search_video_ids, query, max_results=_PAGE),
                        search=True,
                    )
                )

            warnings = []
            try:
                channel = parse_channel_reference(seed.channel_id)
            except InvalidChannelIdError:
                warnings.append("The seed channel is unknown, so its uploads were skipped.")
            else:
                if channel.kind == "id":
                    try:
                        pages.append(
                            self._read(
                                lambda: self.provider.get_channel_upload_ids(
                                    channel.value, max_results=_PAGE
                                )
                            )
                        )
                    except ChannelUnavailableError:
                        warnings.append("The seed channel uploads were unavailable.")
                else:
                    warnings.append(
                        "The seed channel has no canonical ID, so its uploads were skipped."
                    )

            ids = _candidate_ids(video_id, pages)
            candidates: dict[str, VideoRecord] = {}
            for offset in range(0, len(ids), _PAGE):
                batch = ids[offset : offset + _PAGE]
                records = self._read(partial(self.provider.get_video_details, batch))
                for record in records:
                    if record.video_id in batch and record.video_id not in candidates:
                        video = normalise_video_record(record)
                        if _eligible(video):
                            candidates[video.video_id] = video
            results = rank_similar_videos(seed, list(candidates.values()))[:limit]
            if not results:
                warnings.append("No eligible videos were found within the search bounds.")
            if any(item["missing_fields"] or item["low_confidence"] for item in results):
                warnings.append(
                    "Some scores use limited metadata. See each item's missing fields."
                )
            return {
                "seed": video_id,
                "count": len(results),
                "candidate_count": len(ids),
                "eligible_count": len(candidates),
                "videos": results,
                "warnings": warnings,
            }

        if isinstance(self.provider, ProviderGateway):
            with self.provider.operation_budget(_GENERAL_CAP, _SEARCH_CAP):
                return _run_similar()
        self._preflight(_GENERAL_CAP, _SEARCH_CAP)
        return _run_similar()
