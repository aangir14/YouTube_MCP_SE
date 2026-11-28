"""Bounded, read-only playlist analysis and audit (FR-12)."""

from __future__ import annotations

import math
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean, median
from typing import Any

from focuslist.context import RequestContext
from focuslist.discovery.engagement import HISTOGRAM_BINS
from focuslist.discovery.scoring import tokenize_text
from focuslist.errors import InvalidArgumentsError
from focuslist.metadata import normalise_video_record, parse_playlist_id, primary_language
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.quota import PLAYLIST_PAGE_SIZE, PLAYLIST_SCAN_LIMIT, playlist_read_budget
from focuslist.types import PlaylistEntry, VideoRecord, format_duration_display

_TITLE_THRESHOLD = 0.90


@dataclass(frozen=True, slots=True)
class _ScannedItem:
    position: int
    entry: PlaylistEntry
    video: VideoRecord | None
    unavailable_reason: str | None


def _classify(
    entries: list[PlaylistEntry], records: dict[str, VideoRecord],
) -> list[_ScannedItem]:
    items = []
    for position, entry in enumerate(entries, 1):
        video = records.get(entry.video_id) if entry.video_id else None
        if video is None:
            reason = entry.availability_hint or "no_readable_video"
        elif video.visibility == "private":
            reason = "private"
            video = None
        else:
            reason = None
        items.append(_ScannedItem(position, entry, video, reason))
    return items


def _counts(counts: Counter[str], key: str) -> list[dict[str, Any]]:
    return [{key: item, "count": count}
            for item, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))]


def _summary(items: list[_ScannedItem]) -> dict[str, Any]:
    readable = [item.video for item in items if item.video is not None]
    durations = [v.duration_seconds for v in readable if v.duration_seconds is not None]
    total = sum(durations)
    channel_counts: Counter[str] = Counter()
    channel_titles: dict[str, str] = {}
    for video in readable:
        if video.channel_id:
            channel_counts[video.channel_id] += 1
            if video.channel_title:
                channel_titles.setdefault(video.channel_id, video.channel_title)
    known_channels = channel_counts.total()
    channels = [
        {
            **row, "channel": channel_titles.get(row["channel_id"]),
            "share": round(row["count"] / known_channels, 6), "untrusted_metadata": True,
        }
        for row in _counts(channel_counts, "channel_id")[:5]
    ]
    categories = Counter(v.category_id for v in readable if v.category_id)
    languages = Counter(lang for v in readable if (lang := primary_language(v.language)))
    years = [v.published_at.year for v in readable if v.published_at]
    return {
        "total_items": len(items), "readable_items": len(readable),
        "unavailable_items": len(items) - len(readable),
        "total_duration": format_duration_display(total), "total_duration_seconds": total,
        "duration": {
            "known_items": len(durations), "unknown_items": len(readable) - len(durations),
            "mean_seconds": round(fmean(durations), 6) if durations else None,
            "median_seconds": median(durations) if durations else None,
            "histogram": [
                {"bin": name, "count": sum(seconds >= low and (high is None or seconds < high)
                                           for seconds in durations)}
                for name, low, high in HISTOGRAM_BINS
            ],
        },
        "top_channels": channels, "known_channel_items": known_channels,
        "categories": _counts(categories, "category_id"),
        "languages": _counts(languages, "language"),
        "publication_year_range": {"min": min(years), "max": max(years)} if years else None,
        "unknown_readable_fields": {
            "category_id": len(readable) - categories.total(),
            "language": len(readable) - languages.total(),
            "published_at": len(readable) - len(years),
        },
    }


def _title_vector(title: str) -> dict[str, float]:
    terms = Counter(tokenize_text(title, None))
    norm = math.sqrt(sum(count * count for count in terms.values()))
    return {term: count / norm for term, count in terms.items()} if norm else {}


def _findings(
    items: list[_ScannedItem], cutoff: datetime, max_seconds: int | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    first_id: dict[str, int] = {}
    prior_titles: list[tuple[int, dict[str, float]]] = []
    for item in items:
        vid, video = item.entry.video_id, item.video
        detail = {"position": item.position, "video_id": vid, "untrusted_metadata": True}
        if video is not None:
            detail["title"] = video.title

        if vid and vid in first_id:
            findings.append({**detail, "code": "duplicate_id", "duplicate_of": first_id[vid]})
        else:
            if vid:
                first_id[vid] = item.position
            if video is not None and (vector := _title_vector(video.title)):
                for earlier, other in prior_titles:
                    similarity = min(1.0, math.fsum(value * other.get(word, 0.0)
                                                     for word, value in vector.items()))
                    if similarity + 1e-12 >= _TITLE_THRESHOLD:
                        findings.append({
                            **detail, "code": "duplicate_title", "duplicate_of": earlier,
                            "title_cosine": round(similarity, 6),
                        })
                        break
                prior_titles.append((item.position, vector))

        if video is None:
            findings.append({**detail, "code": "unavailable", "reason": item.unavailable_reason})
            continue
        if (max_seconds is not None and video.duration_seconds is not None
                and video.duration_seconds > max_seconds):
            findings.append({
                **detail, "code": "over_length", "duration_seconds": video.duration_seconds,
                "max_duration_seconds": max_seconds,
            })
        if video.published_at is not None and video.published_at < cutoff:
            findings.append({**detail, "code": "stale", "published_at": video.published_at.isoformat()})
        if video.is_live:
            findings.append({**detail, "code": "live"})
        if video.is_upcoming:
            findings.append({**detail, "code": "upcoming"})
    return findings


class PlaylistAnalysis:
    def __init__(self, provider: ProviderGateway, context: RequestContext) -> None:
        self.provider = provider
        self.context = context

    def _scan(self, playlist_id: str, item_limit: int) -> tuple[list[_ScannedItem], bool, int | None]:
        with self.provider.operation_budget(playlist_read_budget(item_limit), context=self.context):
            info = self.provider.get_playlist_info(playlist_id)
            entries: list[PlaylistEntry] = []
            token: str | None = None
            seen_tokens: set[str] = set()
            if info.item_count != 0:
                for _ in range(math.ceil(item_limit / PLAYLIST_PAGE_SIZE)):
                    remaining = item_limit - len(entries)
                    page = self.provider.get_playlist_page(
                        playlist_id, token, page_size=min(PLAYLIST_PAGE_SIZE, remaining),
                    )
                    entries.extend(page.entries[:min(PLAYLIST_PAGE_SIZE, remaining)])
                    token = page.next_page_token
                    if not token or token in seen_tokens or len(entries) >= item_limit:
                        break
                    seen_tokens.add(token)
            ids = list(dict.fromkeys(entry.video_id for entry in entries if entry.video_id))
            records: dict[str, VideoRecord] = {}
            for offset in range(0, len(ids), PLAYLIST_PAGE_SIZE):
                batch = ids[offset:offset + PLAYLIST_PAGE_SIZE]
                records.update({
                    v.video_id: normalise_video_record(v)
                    for v in self.provider.get_playlist_video_details(batch)
                })
        return _classify(entries, records), bool(token), info.item_count

    def analyse(self, reference: str, item_limit: int = PLAYLIST_SCAN_LIMIT) -> dict[str, Any]:
        playlist_id = parse_playlist_id(reference)
        items, truncated, reported = self._scan(playlist_id, item_limit)
        warnings = []
        if truncated:
            warnings.append(f"Results cover the first {len(items)} inspected positions. More may exist.")
        if any(item.video is None for item in items):
            warnings.append("Unavailable positions count as items and contribute no metadata or runtime.")
        return {
            "playlist_id": playlist_id, **_summary(items), "reported_item_count": reported,
            "truncated": truncated, "warnings": warnings, "writes_executed": 0,
        }

    def audit(
        self,
        reference: str,
        *,
        max_item_length_minutes: int | None = None,
        stale_after_years: int = 5,
        item_limit: int = PLAYLIST_SCAN_LIMIT,
    ) -> dict[str, Any]:
        playlist_id = parse_playlist_id(reference)
        if max_item_length_minutes is not None and (
            type(max_item_length_minutes) is not int or not 1 <= max_item_length_minutes <= 1440
        ):
            raise InvalidArgumentsError("Maximum item length must be an integer in 1..1440 minutes.")
        if type(stale_after_years) is not int or not 1 <= stale_after_years <= 100:
            raise InvalidArgumentsError("Stale threshold must be an integer in 1..100 years.")
        now = self.context.clock.now()
        year = now.year - stale_after_years
        cutoff = now.replace(year=year, day=min(now.day, monthrange(year, now.month)[1]))
        items, truncated, reported = self._scan(playlist_id, item_limit)
        max_seconds = max_item_length_minutes * 60 if max_item_length_minutes is not None else None
        findings = _findings(items, cutoff, max_seconds)
        flagged_count = len({row["position"] for row in findings})
        warnings = []
        if truncated:
            warnings.append(f"Results cover the first {len(items)} inspected positions. More may exist.")
        return {
            "playlist_id": playlist_id, **_summary(items), "total_items_scanned": len(items),
            "reported_item_count": reported, "truncated": truncated, "flagged_count": flagged_count,
            "issues": findings, "issue_counts": dict(sorted(Counter(row["code"] for row in findings).items())),
            "health_score": round(1 - flagged_count / len(items), 6) if items else None,
            "thresholds": {"max_item_length_minutes": max_item_length_minutes,
                           "stale_after_years": stale_after_years, "stale_before": cutoff.isoformat(),
                           "duplicate_title_cosine": _TITLE_THRESHOLD},
            "warnings": warnings, "writes_executed": 0,
        }
