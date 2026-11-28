"""FR-2 similar channel discovery and two-pass upload reranking (C17)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import partial
from threading import Lock
from typing import Any

from focuslist.context import RequestContext
from focuslist.discovery.scoring import (
    build_tfidf_vectors,
    cosine_and_shared_terms,
    explain_score,
    mean_normalized_vector,
    most_frequent_primary_language,
    preflight_non_gateway,
    read_with_accounting,
    run_tool_with_envelope,
    tokenize_text,
)
from focuslist.errors import ChannelUnavailableError, InvalidArgumentsError
from focuslist.metadata import (
    normalise_channel_record,
    normalise_video_record,
    parse_channel_reference,
    primary_language,
    same_primary_language,
)
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.provider import VideoProvider
from focuslist.ranking_weights import CHANNEL_WEIGHTS
from focuslist.types import ChannelRecord, VideoRecord

_SEARCH_CAP = 3
_GENERAL_CAP = 25
_CANDIDATE_CAP = 100
_BATCH_SIZE = 50
_RERANK_WINDOW = 10
_UPLOAD_SAMPLE_CAP = 20


def _channel_text(channel: ChannelRecord) -> str:
    return " ".join(
        [channel.title, channel.description or "", *(channel.keywords or ())]
    ).strip()


def _topic_set(channel: ChannelRecord) -> set[str]:
    return {topic.strip().casefold() for topic in channel.topic_categories if topic and topic.strip()}


def _channel_eligible(channel: ChannelRecord) -> bool:
    if channel.video_count is not None and channel.video_count > 0:
        return True
    return bool(channel.recent_upload_ids)


def _channel_search_queries(seed: ChannelRecord, seed_uploads: list[VideoRecord]) -> list[str]:
    queries: list[str] = []
    upload_titles = " ".join(v.title for v in seed_uploads[:5])
    sources = (
        seed.title,
        " ".join(seed.keywords or ()),
        f"{seed.description or ''} {upload_titles}".strip(),
    )
    for text in sources:
        terms = list(dict.fromkeys(tokenize_text(text, seed.language)))[:6]
        query = " ".join(terms)[:160].strip()
        if query and query not in queries:
            queries.append(query)
        if len(queries) == _SEARCH_CAP:
            break
    if not queries and seed.title.strip():
        queries.append(seed.title.strip()[:160])
    return queries


def _effective_channel_language(
    channel: ChannelRecord, uploads: list[VideoRecord] | None
) -> tuple[str | None, bool]:
    native = primary_language(channel.language)
    if native:
        return native, False
    if uploads:
        inferred = most_frequent_primary_language([v.language for v in uploads])
        if inferred:
            return inferred, True
    return None, False


def _score_channel_pair(
    seed: ChannelRecord,
    candidate: ChannelRecord,
    *,
    text_cosine: float,
    shared_terms: list[str],
    seed_lang: str | None,
    seed_lang_inferred: bool,
    cand_lang: str | None,
    cand_lang_inferred: bool,
    seed_has_text: bool,
    cand_has_text: bool,
    ranking_phase: str,
    weights: Mapping[str, float],
) -> dict[str, Any]:
    seed_topics = _topic_set(seed)
    cand_topics = _topic_set(candidate)
    topic_union = seed_topics | cand_topics
    topic_overlap = (
        len(seed_topics & cand_topics) / len(topic_union)
        if seed_topics and cand_topics and topic_union
        else 0.0
    )

    lang_match = float(same_primary_language(seed_lang, cand_lang) is True)

    seed_subs = None if seed.hidden_subscriber_count else seed.subscriber_count
    cand_subs = None if candidate.hidden_subscriber_count else candidate.subscriber_count
    if seed_subs is not None and cand_subs is not None:
        lo, hi = min(seed_subs, cand_subs), max(seed_subs, cand_subs)
        size_fit = (1.0 + math.log1p(lo)) / (1.0 + math.log1p(hi))
    else:
        size_fit = 0.0

    raw = {
        "text_cosine": text_cosine,
        "topic_overlap": topic_overlap,
        "language_match": lang_match,
        "size_fit": size_fit,
    }
    missing: list[str] = []
    if not cand_has_text:
        missing.append("text")
    if not seed_has_text:
        missing.append("seed.text")
    if not cand_topics:
        missing.append("topic_categories")
    if not seed_topics:
        missing.append("seed.topic_categories")
    if cand_lang is None or cand_lang_inferred:
        missing.append("language")
    if seed_lang is None or seed_lang_inferred:
        missing.append("seed.language")
    if cand_subs is None:
        missing.append("subscriber_count")
    if seed_subs is None:
        missing.append("seed.subscriber_count")
    if candidate.keywords is None:
        missing.append("keywords")

    low_confidence = (
        not cand_has_text
        or not seed_has_text
        or cand_lang is None
        or seed_lang is None
        or cand_lang != "en"
        or seed_lang != "en"
        or cand_lang_inferred
        or seed_lang_inferred
    )

    return {
        "item_id": candidate.channel_id,
        "channel_id": candidate.channel_id,
        "canonical_url": candidate.canonical_url,
        "title": candidate.title,
        "handle": candidate.handle,
        **explain_score(raw, weights, shared_terms=shared_terms, missing_fields=missing,
                        low_confidence=low_confidence),
        "ranking_phase": ranking_phase,
        "subscriber_count": cand_subs,
        "hidden_subscriber_count": candidate.hidden_subscriber_count,
        "video_count": candidate.video_count,
        "language": cand_lang if cand_lang_inferred else candidate.language,
        "language_provenance": "public_uploads" if cand_lang_inferred else candidate.language_provenance,
        "untrusted_metadata": True,
    }


def rank_similar_channels_two_pass(
    seed: ChannelRecord,
    seed_uploads: list[VideoRecord],
    candidates: list[ChannelRecord],
    candidate_uploads_by_id: dict[str, list[VideoRecord]] | None = None,
    *, weights: Mapping[str, float] = CHANNEL_WEIGHTS,
) -> list[dict[str, Any]]:
    """Rank eligible channels in two deterministic passes (Pass 1 metadata, Pass 2 top-10 uploads)."""
    if not candidates:
        return []

    meta_docs = {
        ch.channel_id: (_channel_text(ch), ch.language)
        for ch in [seed, *candidates]
    }
    meta_vectors = build_tfidf_vectors(meta_docs)
    seed_meta_vec = meta_vectors[seed.channel_id]
    seed_lang, seed_inferred = _effective_channel_language(seed, seed_uploads)

    pass1_rows: list[dict[str, Any]] = []
    for cand in candidates:
        cand_vec = meta_vectors[cand.channel_id]
        text_cos, shared = cosine_and_shared_terms(cand_vec, seed_meta_vec)
        cand_lang, cand_inferred = _effective_channel_language(cand, None)
        pass1_rows.append(
            _score_channel_pair(
                seed,
                cand,
                text_cosine=text_cos,
                shared_terms=shared,
                seed_lang=seed_lang,
                seed_lang_inferred=seed_inferred,
                cand_lang=cand_lang,
                cand_lang_inferred=cand_inferred,
                seed_has_text=bool(seed_meta_vec),
                cand_has_text=bool(cand_vec),
                ranking_phase="metadata_first_pass",
                weights=weights,
            )
        )

    pass1_rows.sort(key=lambda row: row["channel_id"])
    pass1_rows.sort(key=lambda row: row["score"], reverse=True)

    window_ids = [row["channel_id"] for row in pass1_rows[:_RERANK_WINDOW]]
    tail_rows = pass1_rows[_RERANK_WINDOW:]
    uploads_map = candidate_uploads_by_id or {}
    cand_by_id = {ch.channel_id: ch for ch in candidates}

    # Build one shared upload vocabulary over seed uploads + top-10 window uploads
    upload_docs: dict[str, tuple[str, str | None]] = {}
    for idx, v in enumerate(seed_uploads):
        upload_docs[f"seed:{v.video_id}:{idx}"] = (
            " ".join([v.title, v.description or "", *(v.tags or ())]),
            v.language,
        )
    for cid in window_ids:
        for idx, v in enumerate(uploads_map.get(cid, [])):
            upload_docs[f"{cid}:{v.video_id}:{idx}"] = (
                " ".join([v.title, v.description or "", *(v.tags or ())]),
                v.language,
            )

    upload_vectors = build_tfidf_vectors(upload_docs) if upload_docs else {}
    seed_upload_centroid = mean_normalized_vector(
        vec for key, vec in upload_vectors.items() if key.startswith("seed:")
    )

    reranked_rows: list[dict[str, Any]] = []
    for cid in window_ids:
        cand = cand_by_id[cid]
        cand_uploads = uploads_map.get(cid, [])
        cand_meta_vec = meta_vectors[cid]
        meta_cos, meta_shared = cosine_and_shared_terms(cand_meta_vec, seed_meta_vec)

        cand_upload_centroid = mean_normalized_vector(
            vec for key, vec in upload_vectors.items() if key.startswith(f"{cid}:")
        )
        upload_cos, upload_shared = cosine_and_shared_terms(
            cand_upload_centroid, seed_upload_centroid
        )

        has_meta = bool(cand_meta_vec) and bool(seed_meta_vec)
        has_upload = bool(cand_upload_centroid) and bool(seed_upload_centroid)
        if has_meta and has_upload:
            blended_cos = 0.5 * meta_cos + 0.5 * upload_cos
            phase = "reranked_with_uploads"
        elif has_upload:
            blended_cos = upload_cos
            phase = "reranked_with_uploads"
        else:
            blended_cos = meta_cos
            phase = "metadata_first_pass"

        merged_shared = list(dict.fromkeys([*meta_shared, *upload_shared]))[:5]
        cand_lang, cand_inferred = _effective_channel_language(cand, cand_uploads)
        reranked_rows.append(
            _score_channel_pair(
                seed,
                cand,
                text_cosine=blended_cos,
                shared_terms=merged_shared,
                seed_lang=seed_lang,
                seed_lang_inferred=seed_inferred,
                cand_lang=cand_lang,
                cand_lang_inferred=cand_inferred,
                seed_has_text=bool(seed_meta_vec) or bool(seed_upload_centroid),
                cand_has_text=bool(cand_meta_vec) or bool(cand_upload_centroid),
                ranking_phase=phase,
                weights=weights,
            )
        )

    reranked_rows.sort(key=lambda row: row["channel_id"])
    reranked_rows.sort(key=lambda row: row["score"], reverse=True)

    combined = [*reranked_rows, *tail_rows]
    return [{**row, "rank": rank} for rank, row in enumerate(combined, 1)]


class ChannelDiscovery:
    """FR-2 service for bounded channel resolution and two-pass similarity ranking."""

    def __init__(self, provider: VideoProvider, context: RequestContext) -> None:
        self.provider = provider
        self.ctx = context
        self._lock = Lock()

    def tool_response(self, operation: Any) -> dict[str, Any]:
        with self._lock:
            return run_tool_with_envelope(self.ctx, self.provider, operation)

    def similar(self, reference: str, limit: int = 10) -> dict[str, Any]:
        seed_ref = parse_channel_reference(reference)
        if type(limit) is not int or not 1 <= limit <= 25:
            raise InvalidArgumentsError("Limit must be an integer between 1 and 25.")

        def _run() -> dict[str, Any]:
            seed_raw = read_with_accounting(
                self.ctx,
                self.provider,
                lambda: self.provider.get_channel_details(**seed_ref.provider_arguments()),
            )
            if seed_raw is None:
                raise ChannelUnavailableError()
            seed = normalise_channel_record(seed_raw)

            seed_uploads = [
                normalise_video_record(v)
                for v in read_with_accounting(
                    self.ctx,
                    self.provider,
                    lambda: self.provider.get_channel_recent_uploads(
                        seed.channel_id, max_results=_UPLOAD_SAMPLE_CAP
                    ),
                )[:_UPLOAD_SAMPLE_CAP]
            ]

            candidate_ids_ordered: dict[str, None] = {}
            for query in _channel_search_queries(seed, seed_uploads):
                page_ids = read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.search_channel_ids, query, max_results=_BATCH_SIZE),
                    search=True,
                )
                for cid in page_ids[:_BATCH_SIZE]:
                    if cid and cid != seed.channel_id:
                        candidate_ids_ordered.setdefault(cid, None)
                    if len(candidate_ids_ordered) >= _CANDIDATE_CAP:
                        break
                if len(candidate_ids_ordered) >= _CANDIDATE_CAP:
                    break

            candidate_ids = list(candidate_ids_ordered)
            eligible_by_id: dict[str, ChannelRecord] = {}
            for offset in range(0, len(candidate_ids), _BATCH_SIZE):
                batch = candidate_ids[offset : offset + _BATCH_SIZE]
                records = read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.get_channels_details, batch),
                )
                for rec in records:
                    norm = normalise_channel_record(rec)
                    if (
                        norm.channel_id != seed.channel_id
                        and norm.channel_id not in eligible_by_id
                        and _channel_eligible(norm)
                    ):
                        eligible_by_id[norm.channel_id] = norm

            eligible = list(eligible_by_id.values())
            weights = self.ctx.settings.scoring_weights["similar_channels"]
            pass1 = rank_similar_channels_two_pass(seed, seed_uploads, eligible, weights=weights)
            top_window_ids = [row["channel_id"] for row in pass1[:_RERANK_WINDOW]]

            uploads_by_id: dict[str, list[VideoRecord]] = {}
            for cid in top_window_ids:
                uploads_by_id[cid] = [
                    normalise_video_record(v)
                    for v in read_with_accounting(
                        self.ctx,
                        self.provider,
                        partial(
                            self.provider.get_channel_recent_uploads,
                            cid,
                            max_results=_UPLOAD_SAMPLE_CAP,
                        ),
                    )[:_UPLOAD_SAMPLE_CAP]
                ]

            ranked = rank_similar_channels_two_pass(
                seed, seed_uploads, eligible, candidate_uploads_by_id=uploads_by_id, weights=weights,
            )[:limit]

            warnings: list[str] = []
            if not ranked:
                warnings.append("No eligible channels with public uploads were found.")
            if any(row["hidden_subscriber_count"] for row in ranked):
                warnings.append(
                    "One or more channels have hidden subscriber counts; size_fit scored 0.0."
                )
            if any("keywords" in row["missing_fields"] for row in ranked):
                warnings.append("Some channels have missing keywords.")
            if any(row["language_provenance"] == "public_uploads" for row in ranked):
                warnings.append(
                    "Some channel languages were inferred from recent public uploads."
                )

            return {
                "seed": seed.channel_id,
                "seed_title": seed.title,
                "count": len(ranked),
                "candidate_count": len(candidate_ids),
                "eligible_count": len(eligible),
                "reranked_count": len(top_window_ids),
                "channels": ranked,
                "warnings": warnings,
            }

        if isinstance(self.provider, ProviderGateway):
            with self.provider.operation_budget(_GENERAL_CAP, _SEARCH_CAP, context=self.ctx):
                return _run()
        preflight_non_gateway(self.ctx, self.provider, _GENERAL_CAP, _SEARCH_CAP)
        return _run()
