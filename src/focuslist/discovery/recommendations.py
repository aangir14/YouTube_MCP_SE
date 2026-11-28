"""FR-3 personalized recommendations from consented account data (C17)."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from datetime import UTC, datetime
from functools import partial
from threading import Lock
from typing import Any

from focuslist.context import RequestContext
from focuslist.discovery.scoring import (
    build_tfidf_vectors,
    cosine_and_shared_terms,
    explain_score,
    mean_normalized_vector,
    preflight_non_gateway,
    read_with_accounting,
    resolve_authorized_account,
    run_tool_with_envelope,
)
from focuslist.errors import InvalidArgumentsError, NoProfileDataError
from focuslist.metadata import (
    normalise_channel_record,
    normalise_video_record,
    primary_language,
    video_watch_url,
)
from focuslist.platform.auth import AuthManager
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.provider import VideoProvider
from focuslist.platform.storage import FocusListStorage
from focuslist.ranking_weights import RECOMMENDATION_WEIGHTS
from focuslist.types import AccountActivityRecord, ChannelRecord, VideoRecord

_VALID_SOURCES = frozenset({"likes", "subscriptions", "playlists"})
_MAX_LIKES = 200
_MAX_SUBS = 200
_MAX_PLAYLISTS = 5
_MAX_PLAYLIST_ITEMS = 100
_MAX_SEARCHES = 3
_MAX_SUB_CHANNELS = 5
_CANDIDATE_CAP = 400
_BATCH_SIZE = 50
_GENERAL_CAP = 40
_EARLIEST = datetime.min.replace(tzinfo=UTC)

__all__ = ["RECOMMENDATION_WEIGHTS", "WATCH_HISTORY_DISCLOSURE", "RecommendationService",
           "validate_sources"]

WATCH_HISTORY_DISCLOSURE = (
    "Watch history is unavailable and excluded; recommendations are derived from "
    "selected authorised likes, subscriptions, and playlists only."
)


def validate_sources(sources: Any) -> list[str]:
    """Validate required 1-3 distinct source names from likes, subscriptions, playlists."""
    if not isinstance(sources, list) or not (1 <= len(sources) <= 3):
        raise InvalidArgumentsError(
            "sources must be a list of 1 to 3 distinct values from: likes, subscriptions, playlists."
        )
    cleaned: list[str] = []
    for item in sources:
        if not isinstance(item, str) or item not in _VALID_SOURCES or item in cleaned:
            raise InvalidArgumentsError(
                "sources must contain 1 to 3 distinct values from: likes, subscriptions, playlists."
            )
        cleaned.append(item)
    return cleaned


def _eligible_video(video: VideoRecord) -> bool:
    return (
        video.visibility == "public"
        and video.is_live is False
        and video.is_upcoming is False
        and video.is_age_restricted is False
        and video.duration_seconds is not None
        and video.duration_seconds >= 60
    )


def _source_fingerprint(
    sources: list[str],
    likes: list[AccountActivityRecord],
    subs: list[AccountActivityRecord],
    playlist_items: list[AccountActivityRecord],
) -> str:
    payload = {
        "sources": sorted(sources),
        "likes": sorted(r.item_id for r in likes),
        "subs": sorted(r.item_id for r in subs),
        "playlists": sorted(f"{r.playlist_id}:{r.item_id}" for r in playlist_items),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RecommendationService:
    """FR-3 service building account-scoped profiles and bounded recommendations."""

    def __init__(
        self,
        provider: VideoProvider,
        context: RequestContext,
        *,
        storage: FocusListStorage | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        self.provider = provider
        self.ctx = context
        self.storage = storage or (
            provider.storage if isinstance(provider, ProviderGateway) else None
        )
        self.auth_manager = auth_manager
        self._lock = Lock()

    def tool_response(self, operation: Any) -> dict[str, Any]:
        with self._lock:
            return run_tool_with_envelope(self.ctx, self.provider, operation)

    def recommend(
        self,
        sources: list[str],
        topic: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        clean_sources = validate_sources(sources)
        clean_topic: str | None = None
        if topic is not None:
            if not isinstance(topic, str):
                raise InvalidArgumentsError("topic must be a string between 1 and 200 characters.")
            stripped = topic.strip()
            if not (1 <= len(stripped) <= 200):
                raise InvalidArgumentsError("topic must be between 1 and 200 characters.")
            clean_topic = stripped
        if type(limit) is not int or not 1 <= limit <= 50:
            raise InvalidArgumentsError("limit must be an integer between 1 and 50.")

        # Check consent before any provider I/O
        account_id = resolve_authorized_account(self.ctx, self.auth_manager)

        def _run() -> dict[str, Any]:
            likes: list[AccountActivityRecord] = []
            subs: list[AccountActivityRecord] = []
            playlist_items: list[AccountActivityRecord] = []

            if "likes" in clean_sources:
                likes = read_with_accounting(
                    self.ctx,
                    self.provider,
                    lambda: self.provider.get_user_likes(account_id, max_results=_MAX_LIKES),
                )[:_MAX_LIKES]

            if "subscriptions" in clean_sources:
                subs = read_with_accounting(
                    self.ctx,
                    self.provider,
                    lambda: self.provider.get_user_subscriptions(account_id, max_results=_MAX_SUBS),
                )[:_MAX_SUBS]

            if "playlists" in clean_sources:
                owned_playlists = read_with_accounting(
                    self.ctx,
                    self.provider,
                    lambda: self.provider.get_user_playlists(
                        account_id, max_results=_MAX_PLAYLISTS
                    ),
                )[:_MAX_PLAYLISTS]
                for pl in owned_playlists:
                    pid = str(pl.get("playlist_id") or "")
                    if not pid:
                        continue
                    items = read_with_accounting(
                        self.ctx,
                        self.provider,
                        partial(
                            self.provider.get_playlist_items,
                            pid,
                            max_results=_MAX_PLAYLIST_ITEMS,
                        ),
                    )[:_MAX_PLAYLIST_ITEMS]
                    playlist_items.extend(items)

            if not likes and not subs and not playlist_items:
                raise NoProfileDataError()

            seen_video_ids = {r.item_id for r in likes} | {r.item_id for r in playlist_items}
            profile_video_ids = list(dict.fromkeys([r.item_id for r in likes] + [r.item_id for r in playlist_items]))
            profile_videos: dict[str, VideoRecord] = {}
            for offset in range(0, len(profile_video_ids), _BATCH_SIZE):
                batch = profile_video_ids[offset : offset + _BATCH_SIZE]
                for rec in read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.get_video_details, batch),
                ):
                    norm = normalise_video_record(rec)
                    profile_videos[norm.video_id] = norm

            sub_channel_ids = list(dict.fromkeys(r.item_id for r in subs if r.item_id))
            sub_channels: dict[str, ChannelRecord] = {}
            for offset in range(0, len(sub_channel_ids), _BATCH_SIZE):
                batch = sub_channel_ids[offset : offset + _BATCH_SIZE]
                for channel in read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.get_channels_details, batch),
                ):
                    normalised_channel = normalise_channel_record(channel)
                    sub_channels[normalised_channel.channel_id] = normalised_channel

            # Build profile documents (namespaced by type)
            profile_docs: dict[str, tuple[str, str | None]] = {}
            profile_labels: dict[str, dict[str, str]] = {}
            for vid, v in profile_videos.items():
                doc_id = f"video:{vid}"
                profile_docs[doc_id] = (
                    " ".join([v.title, v.description or "", *(v.tags or ())]),
                    v.language,
                )
                profile_labels[doc_id] = {
                    "type": "video",
                    "id": vid,
                    "title": v.title,
                    "source": "likes" if any(r.item_id == vid for r in likes) else "playlists",
                }
            for cid, ch in sub_channels.items():
                doc_id = f"channel:{cid}"
                profile_docs[doc_id] = (
                    " ".join([ch.title, ch.description or "", *(ch.keywords or ())]),
                    ch.language,
                )
                profile_labels[doc_id] = {
                    "type": "channel",
                    "id": cid,
                    "title": ch.title,
                    "source": "subscriptions",
                }

            if not profile_docs:
                raise NoProfileDataError()

            # Compute profile metadata summary & persist in account-scoped cache
            cat_counts = Counter(
                v.category_id for v in profile_videos.values() if v.category_id
            )
            cat_total = sum(cat_counts.values())
            lang_counts = Counter(
                primary_language(v.language)
                for v in profile_videos.values()
                if primary_language(v.language)
            )
            for ch in sub_channels.values():
                lang = primary_language(ch.language)
                if lang:
                    lang_counts[lang] += 1
            lang_total = sum(lang_counts.values())

            positive_durations = [
                v.duration_seconds
                for v in profile_videos.values()
                if v.duration_seconds is not None and v.duration_seconds > 0
            ]
            median_duration = (
                float(statistics.median(positive_durations)) if positive_durations else None
            )

            channel_counts: Counter[str] = Counter()
            dedup_profile_items: dict[str, str] = {}
            for vid, v in profile_videos.items():
                if v.channel_id:
                    dedup_profile_items[f"v:{vid}"] = v.channel_id
            for cid in sub_channels:
                dedup_profile_items[f"c:{cid}"] = cid
            for cid in dedup_profile_items.values():
                channel_counts[cid] += 1
            total_channel_items = sum(channel_counts.values())

            fp = _source_fingerprint(clean_sources, likes, subs, playlist_items)
            if self.storage is not None and self.ctx.settings.cache_enabled:
                self.storage.set_cache(
                    "derived_profile",
                    {"fingerprint": fp, "sources": sorted(clean_sources)},
                    "derived_profile",
                    {
                        "fingerprint": fp,
                        "category_counts": dict(cat_counts),
                        "language_counts": dict(lang_counts),
                        "median_duration": median_duration,
                        "channel_counts": dict(channel_counts),
                    },
                    account_id=account_id,
                )

            # Choose up to 5 subscribed channels for upload harvesting
            selected_sub_ids: list[str] = []
            if sub_channels:
                sub_docs = {cid: profile_docs[f"channel:{cid}"] for cid in sub_channels}
                if clean_topic:
                    sub_docs["__query__"] = (clean_topic, "en")
                    sub_vecs = build_tfidf_vectors(sub_docs)
                    q_vec = sub_vecs["__query__"]
                else:
                    sub_vecs = build_tfidf_vectors(sub_docs)
                    q_vec = mean_normalized_vector(sub_vecs.values())

                def _sub_key(cid: str) -> tuple[float, str]:
                    cos, _ = cosine_and_shared_terms(sub_vecs.get(cid, {}), q_vec)
                    return (-cos, cid)

                selected_sub_ids = sorted(sub_channels, key=_sub_key)[:_MAX_SUB_CHANNELS]

            # Build up to 3 search queries
            search_queries: list[str] = []
            if clean_topic:
                search_queries.append(clean_topic)
            prof_vecs_only = build_tfidf_vectors(profile_docs)
            prof_mean = mean_normalized_vector(prof_vecs_only.values())
            top_terms = sorted(prof_mean, key=lambda t: (-prof_mean[t], t))[:6]
            if top_terms:
                q_terms = " ".join(top_terms)[:160].strip()
                if q_terms and q_terms not in search_queries:
                    search_queries.append(q_terms)
            for cid in selected_sub_ids:
                if len(search_queries) >= _MAX_SEARCHES:
                    break
                title_q = sub_channels[cid].title.strip()[:160]
                if title_q and title_q not in search_queries:
                    search_queries.append(title_q)

            candidate_ids_ordered: dict[str, None] = {}
            for query in search_queries[:_MAX_SEARCHES]:
                page_ids = read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.search_video_ids, query, max_results=_BATCH_SIZE),
                    search=True,
                )
                for vid in page_ids[:_BATCH_SIZE]:
                    if vid and vid not in seen_video_ids:
                        candidate_ids_ordered.setdefault(vid, None)
                    if len(candidate_ids_ordered) >= _CANDIDATE_CAP:
                        break
                if len(candidate_ids_ordered) >= _CANDIDATE_CAP:
                    break

            for cid in selected_sub_ids:
                if len(candidate_ids_ordered) >= _CANDIDATE_CAP:
                    break
                upload_ids = read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.get_channel_upload_ids, cid, max_results=_BATCH_SIZE),
                )
                for vid in upload_ids[:_BATCH_SIZE]:
                    if vid and vid not in seen_video_ids:
                        candidate_ids_ordered.setdefault(vid, None)
                    if len(candidate_ids_ordered) >= _CANDIDATE_CAP:
                        break

            candidate_ids = list(candidate_ids_ordered)
            eligible: dict[str, VideoRecord] = {}
            for offset in range(0, len(candidate_ids), _BATCH_SIZE):
                batch = candidate_ids[offset : offset + _BATCH_SIZE]
                for rec in read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.get_video_details, batch),
                ):
                    norm = normalise_video_record(rec)
                    if (
                        norm.video_id not in seen_video_ids
                        and norm.video_id not in eligible
                        and _eligible_video(norm)
                    ):
                        eligible[norm.video_id] = norm

            if not eligible:
                return {
                    "sources": clean_sources,
                    "topic": clean_topic,
                    "count": 0,
                    "candidate_count": len(candidate_ids),
                    "eligible_count": 0,
                    "recommendations": [],
                    "watch_history_disclosure": WATCH_HISTORY_DISCLOSURE,
                    "source_counts": {
                        "likes": len(likes),
                        "subscriptions": len(subs),
                        "playlist_items": len(playlist_items),
                    },
                    "warnings": [
                        WATCH_HISTORY_DISCLOSURE,
                        "No eligible unseen videos were found within the search bounds.",
                    ],
                }

            all_docs: dict[str, tuple[str, str | None]] = dict(profile_docs)
            for vid, v in eligible.items():
                all_docs[f"cand:{vid}"] = (
                    " ".join([v.title, v.description or "", *(v.tags or ())]),
                    v.language,
                )
            vectors = build_tfidf_vectors(all_docs)
            profile_mean_vec = mean_normalized_vector(
                vec for key, vec in vectors.items() if not key.startswith("cand:")
            )
            profile_languages = [primary_language(lang) for _, lang in profile_docs.values()]
            profile_missing = []
            if not profile_mean_vec:
                profile_missing.append("profile.text")
            if None in profile_languages:
                profile_missing.append("profile.language")
            profile_uses_fallback = any(lang != "en" for lang in profile_languages)
            now_utc = self.ctx.clock.now()

            ranked: list[tuple[dict[str, Any], datetime | None]] = []
            for vid, cand in eligible.items():
                cand_vec = vectors[f"cand:{vid}"]
                text_cos, shared = cosine_and_shared_terms(cand_vec, profile_mean_vec)

                cat_share = (
                    cat_counts[cand.category_id] / cat_total
                    if cand.category_id and cat_total > 0
                    else 0.0
                )
                cand_lang = primary_language(cand.language)
                lang_share = (
                    lang_counts[cand_lang] / lang_total
                    if cand_lang and lang_total > 0
                    else 0.0
                )
                profile_sim = (text_cos + cat_share + lang_share) / 3.0

                if cand.published_at is not None and cand.published_at <= now_utc:
                    age_days = (now_utc - cand.published_at).total_seconds() / 86_400.0
                    freshness = max(0.0, 1.0 - age_days / 365.0)
                else:
                    freshness = 0.0

                if median_duration and cand.duration_seconds:
                    duration_fit = min(cand.duration_seconds, median_duration) / max(
                        cand.duration_seconds, median_duration
                    )
                else:
                    duration_fit = 0.0

                channel_affinity = (
                    channel_counts[cand.channel_id] / total_channel_items
                    if cand.channel_id and total_channel_items > 0
                    else 0.0
                )

                raw = {
                    "profile_similarity": profile_sim,
                    "freshness": freshness,
                    "duration_fit": duration_fit,
                    "channel_affinity": channel_affinity,
                }

                # Up to 3 contributing profile items/channels by positive cosine
                contributors: list[tuple[float, str, dict[str, str]]] = []
                for doc_id, label in profile_labels.items():
                    cos_i, _ = cosine_and_shared_terms(cand_vec, vectors[doc_id])
                    if cos_i > 0:
                        contributors.append((cos_i, label["id"], label))
                contributors.sort(key=lambda row: (-row[0], row[1]))
                top_contributors = [
                    {**item, "similarity": round(cos_val, 6), "untrusted_metadata": True}
                    for cos_val, _, item in contributors[:3]
                ]

                missing = profile_missing.copy()
                if not cand_vec:
                    missing.append("text")
                if not cand.category_id:
                    missing.append("category_id")
                if cand_lang is None:
                    missing.append("language")
                if cand.published_at is None:
                    missing.append("published_at")
                if not cand.channel_id:
                    missing.append("channel_id")

                low_confidence = (
                    not cand_vec or not profile_mean_vec or cand_lang != "en" or profile_uses_fallback
                )

                item = {
                    "item_id": cand.video_id,
                    "video_id": cand.video_id,
                    "canonical_url": video_watch_url(cand.video_id),
                    "title": cand.title,
                    "channel_id": cand.channel_id or None,
                    "channel_title": cand.channel_title,
                    "duration": cand.duration_display,
                    "duration_seconds": cand.duration_seconds,
                    "duration_iso": cand.duration_iso,
                    "language": cand.language,
                    "published_at": cand.published_at.isoformat() if cand.published_at else None,
                    **explain_score(
                        raw, self.ctx.settings.scoring_weights["recommend_videos"],
                        shared_terms=shared, missing_fields=missing, low_confidence=low_confidence,
                    ),
                    "contributing_items": top_contributors,
                    "untrusted_metadata": True,
                }
                ranked.append((item, cand.published_at))

            ranked.sort(key=lambda row: row[0]["item_id"])
            ranked.sort(key=lambda row: (row[1] is not None, row[1] or _EARLIEST), reverse=True)
            ranked.sort(key=lambda row: row[0]["score"], reverse=True)
            final = [{**row, "rank": rank} for rank, (row, _) in enumerate(ranked[:limit], 1)]

            warnings = [WATCH_HISTORY_DISCLOSURE]
            if any(item["low_confidence"] or item["missing_fields"] for item in final):
                warnings.append(
                    "Some recommendations have missing metadata or non-English fallback."
                )

            return {
                "sources": clean_sources,
                "topic": clean_topic,
                "count": len(final),
                "candidate_count": len(candidate_ids),
                "eligible_count": len(eligible),
                "recommendations": final,
                "watch_history_disclosure": WATCH_HISTORY_DISCLOSURE,
                "source_counts": {
                    "likes": len(likes),
                    "subscriptions": len(subs),
                    "playlist_items": len(playlist_items),
                },
                "warnings": warnings,
            }

        if isinstance(self.provider, ProviderGateway):
            with self.provider.operation_budget(_GENERAL_CAP, _MAX_SEARCHES, context=self.ctx):
                return _run()
        preflight_non_gateway(self.ctx, self.provider, _GENERAL_CAP, _MAX_SEARCHES)
        return _run()
