"""FR-4 authorised account engagement analytics and period comparisons (C17)."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from functools import partial
from threading import Lock
from typing import Any

from focuslist.context import RequestContext
from focuslist.discovery.recommendations import validate_sources
from focuslist.discovery.scoring import (
    preflight_non_gateway,
    read_with_accounting,
    resolve_authorized_account,
    run_tool_with_envelope,
)
from focuslist.errors import InvalidArgumentsError
from focuslist.metadata import normalise_channel_record, normalise_video_record, parse_utc_datetime
from focuslist.platform.auth import AuthManager
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.provider import VideoProvider
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    VideoRecord,
    format_duration_display,
)

_GENERAL_CAP = 60
_MAX_LIKES = 200
_MAX_SUBS = 200
_MAX_PLAYLISTS = 5
_MAX_PLAYLIST_ITEMS = 100
_BATCH_SIZE = 50
_PRESET_DAYS = frozenset({30, 90, 365})

HISTOGRAM_BINS: tuple[tuple[str, int, int | None], ...] = (
    ("lt_5m", 0, 300),
    ("5_to_10m", 300, 600),
    ("10_to_20m", 600, 1200),
    ("20_to_40m", 1200, 2400),
    ("40_to_60m", 2400, 3600),
    ("gte_60m", 3600, None),
)

PUBLICATION_FALLBACK_WARNING = (
    "Some trend points use the video's publication date. "
    "The actual like or playlist add date was unavailable."
)


@dataclass(frozen=True, slots=True)
class _Observation:
    source: str
    item_id: str
    timestamp: datetime | None
    basis: str  # "genuine" | "publication_fallback" | "undated"
    channel_id: str | None
    channel_title: str | None
    category_id: str | None
    duration_seconds: int | None


def _parse_period_spec(
    period: dict[str, Any] | None,
    period_days: int | None,
    now: datetime,
    *,
    is_comparison: bool = False,
) -> tuple[datetime, datetime]:
    if not is_comparison and period is not None and period_days is not None:
        raise InvalidArgumentsError("Supply either 'period' or 'period_days', not both.")
    if period is None and period_days is None:
        if is_comparison:
            raise InvalidArgumentsError("comparison_period cannot be empty.")
        return now - timedelta(days=30), now
    if period_days is not None:
        if type(period_days) is not int or period_days not in _PRESET_DAYS:
            raise InvalidArgumentsError("period_days must be 30, 90, or 365.")
        return now - timedelta(days=period_days), now

    if not isinstance(period, dict):
        raise InvalidArgumentsError("period must be an object with 'days' or 'start'/'end'.")
    keys = set(period.keys())
    if keys == {"days"}:
        days = period["days"]
        if type(days) is not int or days not in _PRESET_DAYS:
            raise InvalidArgumentsError("period.days must be 30, 90, or 365.")
        return now - timedelta(days=days), now
    if keys == {"start", "end"}:
        start = parse_utc_datetime(period["start"], allow_date=True)
        end = parse_utc_datetime(period["end"], allow_date=True)
        if start >= end:
            raise InvalidArgumentsError("period.start must be strictly before period.end.")
        return start, end
    raise InvalidArgumentsError("period must contain either {'days'} or {'start', 'end'}.")


def _bucket_bounds(ts: datetime, group_by: str) -> tuple[datetime, datetime]:
    ts_utc = ts.astimezone(UTC)
    if group_by == "week":
        day_start = datetime.combine(ts_utc.date(), time.min, UTC)
        monday = day_start - timedelta(days=day_start.weekday())
        return monday, monday + timedelta(days=7)
    month_start = datetime(ts_utc.year, ts_utc.month, 1, tzinfo=UTC)
    if ts_utc.month == 12:
        next_month = datetime(ts_utc.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(ts_utc.year, ts_utc.month + 1, 1, tzinfo=UTC)
    return month_start, next_month


def _histogram_bin(seconds: int) -> str:
    for name, low, high in HISTOGRAM_BINS:
        if high is None:
            if seconds >= low:
                return name
        elif low <= seconds < high:
            return name
    return "gte_60m"


def _compute_delta(
    current: float | None,
    baseline: float | None,
    *,
    baseline_empty: bool,
) -> tuple[float | int | None, float | None]:
    if current is None or baseline is None or baseline_empty:
        return (
            round(current - baseline, 6) if (current is not None and baseline is not None) else None,
            None,
        )
    delta = current - baseline
    if isinstance(delta, float):
        delta = round(delta, 6)
    if baseline == 0:
        return delta, None
    pct = round(100.0 * (current - baseline) / baseline, 6)
    return delta, pct


def _summarise_period(
    observations: list[_Observation],
    undated_by_source: dict[str, int],
    *,
    start: datetime,
    end: datetime,
    group_by: str,
    categories_by_id: dict[str, str],
) -> dict[str, Any]:
    in_window = [
        obs
        for obs in observations
        if obs.timestamp is not None and start <= obs.timestamp < end
    ]

    source_counts = {"likes": 0, "subscriptions": 0, "playlists": 0}
    basis_counts = {"genuine": 0, "publication_fallback": 0}
    channel_counts: Counter[str] = Counter()
    channel_titles: dict[str, str] = {}
    unknown_channel_count = 0
    category_counts: Counter[str] = Counter()
    unknown_category_count = 0
    durations: list[int] = []
    unknown_duration_count = 0
    histogram = {name: 0 for name, _, _ in HISTOGRAM_BINS}

    buckets: dict[tuple[datetime, datetime], dict[str, Any]] = {}

    for obs in in_window:
        source_counts[obs.source] += 1
        if obs.basis in basis_counts:
            basis_counts[obs.basis] += 1

        if obs.channel_id:
            channel_counts[obs.channel_id] += 1
            if obs.channel_title:
                channel_titles.setdefault(obs.channel_id, obs.channel_title)
        else:
            unknown_channel_count += 1

        if obs.source != "subscriptions":
            if obs.category_id and obs.category_id in categories_by_id:
                category_counts[obs.category_id] += 1
            else:
                unknown_category_count += 1

            if obs.duration_seconds is not None:
                durations.append(obs.duration_seconds)
                histogram[_histogram_bin(obs.duration_seconds)] += 1
            else:
                unknown_duration_count += 1

        assert obs.timestamp is not None
        raw_start, raw_end = _bucket_bounds(obs.timestamp, group_by)
        clamped_start = max(raw_start, start)
        clamped_end = min(raw_end, end)
        key = (clamped_start, clamped_end)
        if key not in buckets:
            buckets[key] = {
                "bucket_start": clamped_start.isoformat(),
                "bucket_end": clamped_end.isoformat(),
                "count": 0,
                "source_counts": {"likes": 0, "subscriptions": 0, "playlists": 0},
                "basis_counts": {"genuine": 0, "publication_fallback": 0},
            }
        buckets[key]["count"] += 1
        buckets[key]["source_counts"][obs.source] += 1
        if obs.basis in buckets[key]["basis_counts"]:
            buckets[key]["basis_counts"][obs.basis] += 1

    channel_denom = sum(channel_counts.values())
    top_channels = [
        {
            "channel_id": cid,
            "channel_title": channel_titles.get(cid, cid),
            "count": count,
            "share": round(count / channel_denom, 6) if channel_denom > 0 else None,
            "untrusted_metadata": True,
        }
        for cid, count in sorted(channel_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    cat_denom = sum(category_counts.values())
    top_categories = [
        {
            "category_id": cat_id,
            "category_name": categories_by_id[cat_id],
            "count": count,
            "share": round(count / cat_denom, 6) if cat_denom > 0 else None,
        }
        for cat_id, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    mean_sec = round(statistics.mean(durations), 2) if durations else None
    median_sec = round(statistics.median(durations), 2) if durations else None
    trends = [buckets[k] for k in sorted(buckets)]

    warnings: list[str] = []
    obs_count = len(in_window)
    if obs_count < 10:
        warnings.append("Fewer than 10 observations in this window; metrics are partial.")
    if basis_counts["publication_fallback"] > 0:
        warnings.append(PUBLICATION_FALLBACK_WARNING)
    total_undated = sum(undated_by_source.values())
    if total_undated > 0:
        warnings.append(
            f"Excluded {total_undated} undated observation(s) from period metrics."
        )

    return {
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "group_by": group_by,
        },
        "observation_count": obs_count,
        "source_counts": source_counts,
        "undated_by_source": dict(undated_by_source),
        "basis_counts": basis_counts,
        "channel_denominator": channel_denom,
        "unknown_channel_count": unknown_channel_count,
        "top_channels": top_channels,
        "category_denominator": cat_denom,
        "unknown_category_count": unknown_category_count,
        "top_categories": top_categories,
        "duration": {
            "known_count": len(durations),
            "unknown_count": unknown_duration_count,
            "mean_seconds": mean_sec,
            "median_seconds": median_sec,
            "mean_display": format_duration_display(round(mean_sec)) if mean_sec is not None else None,
            "median_display": (
                format_duration_display(round(median_sec)) if median_sec is not None else None
            ),
            "histogram": histogram,
        },
        "trends": trends,
        "chart_data": {
            "trend_series": [
                {"label": row["bucket_start"], "count": row["count"]} for row in trends
            ],
            "duration_bins": [
                {"bin": name, "count": histogram[name]} for name, _, _ in HISTOGRAM_BINS
            ],
        },
        "warnings": warnings,
    }


def _compare_periods(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    baseline_empty = baseline["observation_count"] == 0

    obs_delta, obs_pct = _compute_delta(
        current["observation_count"],
        baseline["observation_count"],
        baseline_empty=baseline_empty,
    )

    source_deltas: dict[str, Any] = {}
    for src in ("likes", "subscriptions", "playlists"):
        cur_v = current["source_counts"][src]
        base_v = baseline["source_counts"][src]
        d_val, pct_val = _compute_delta(cur_v, base_v, baseline_empty=baseline_empty)
        source_deltas[src] = {
            "current": cur_v,
            "baseline": base_v,
            "absolute_delta": d_val,
            "percentage_delta": pct_val,
        }

    cur_ch = {row["channel_id"]: row for row in current["top_channels"]}
    base_ch = {row["channel_id"]: row for row in baseline["top_channels"]}
    channel_deltas: list[dict[str, Any]] = []
    for cid in sorted(set(cur_ch) | set(base_ch)):
        cur_row = cur_ch.get(cid)
        base_row = base_ch.get(cid)
        cur_cnt = cur_row["count"] if cur_row else 0
        base_cnt = base_row["count"] if base_row else (None if baseline_empty else 0)
        d_cnt, pct_cnt = _compute_delta(cur_cnt, base_cnt, baseline_empty=baseline_empty)
        cur_share = cur_row["share"] if cur_row else (0.0 if current["channel_denominator"] > 0 else None)
        base_share = (
            base_row["share"]
            if base_row
            else (0.0 if baseline["channel_denominator"] > 0 else None)
        )
        d_share, pct_share = _compute_delta(
            cur_share, base_share, baseline_empty=baseline_empty
        )
        channel_deltas.append(
            {
                "channel_id": cid,
                "channel_title": (cur_ch[cid] if cid in cur_ch else base_ch[cid])["channel_title"],
                "current_count": cur_cnt,
                "baseline_count": base_cnt if base_cnt is not None else 0,
                "count_delta": d_cnt,
                "count_percentage_delta": pct_cnt,
                "current_share": cur_share,
                "baseline_share": base_share,
                "share_delta": d_share,
                "share_percentage_delta": pct_share,
                "untrusted_metadata": True,
            }
        )

    cur_cat = {row["category_id"]: row for row in current["top_categories"]}
    base_cat = {row["category_id"]: row for row in baseline["top_categories"]}
    category_deltas: list[dict[str, Any]] = []
    for cat_id in sorted(set(cur_cat) | set(base_cat)):
        cur_row = cur_cat.get(cat_id)
        base_row = base_cat.get(cat_id)
        cur_cnt = cur_row["count"] if cur_row else 0
        base_cnt = base_row["count"] if base_row else (None if baseline_empty else 0)
        d_cnt, pct_cnt = _compute_delta(cur_cnt, base_cnt, baseline_empty=baseline_empty)
        category_deltas.append(
            {
                "category_id": cat_id,
                "category_name": (
                    cur_cat[cat_id] if cat_id in cur_cat else base_cat[cat_id]
                )["category_name"],
                "current_count": cur_cnt,
                "baseline_count": base_cnt if base_cnt is not None else 0,
                "count_delta": d_cnt,
                "count_percentage_delta": pct_cnt,
            }
        )

    histogram_deltas: dict[str, Any] = {}
    for bin_name, _, _ in HISTOGRAM_BINS:
        cur_v = current["duration"]["histogram"][bin_name]
        base_v = baseline["duration"]["histogram"][bin_name]
        d_val, pct_val = _compute_delta(
            cur_v,
            None if baseline_empty else base_v,
            baseline_empty=baseline_empty,
        )
        histogram_deltas[bin_name] = {
            "current": cur_v,
            "baseline": base_v,
            "absolute_delta": d_val,
            "percentage_delta": pct_val,
        }

    return {
        "observation_count": {
            "current": current["observation_count"],
            "baseline": baseline["observation_count"],
            "absolute_delta": obs_delta,
            "percentage_delta": obs_pct,
        },
        "source_counts": source_deltas,
        "channels": channel_deltas,
        "categories": category_deltas,
        "histogram": histogram_deltas,
    }


class EngagementService:
    """FR-4 service for bounded account engagement analytics and comparisons."""

    def __init__(
        self,
        provider: VideoProvider,
        context: RequestContext,
        *,
        auth_manager: AuthManager | None = None,
    ) -> None:
        self.provider = provider
        self.ctx = context
        self.auth_manager = auth_manager
        self._lock = Lock()

    def tool_response(self, operation: Any) -> dict[str, Any]:
        with self._lock:
            return run_tool_with_envelope(self.ctx, self.provider, operation)

    def analyse(
        self,
        sources: list[str],
        period: dict[str, Any] | None = None,
        period_days: int | None = None,
        comparison_period: dict[str, Any] | None = None,
        group_by: str = "week",
    ) -> dict[str, Any]:
        clean_sources = validate_sources(sources)
        if group_by not in {"week", "month"}:
            raise InvalidArgumentsError("group_by must be 'week' or 'month'.")
        now = self.ctx.clock.now()
        cur_start, cur_end = _parse_period_spec(period, period_days, now)
        comp_bounds: tuple[datetime, datetime] | None = None
        if comparison_period is not None:
            comp_bounds = _parse_period_spec(
                comparison_period, None, now, is_comparison=True
            )

        account_id = resolve_authorized_account(self.ctx, self.auth_manager)

        def _run() -> dict[str, Any]:
            likes_by_id: dict[str, AccountActivityRecord] = {}
            subs_by_id: dict[str, AccountActivityRecord] = {}
            playlist_entries: dict[tuple[str, str], AccountActivityRecord] = {}

            if "likes" in clean_sources:
                for rec in read_with_accounting(
                    self.ctx,
                    self.provider,
                    lambda: self.provider.get_user_likes(account_id, max_results=_MAX_LIKES),
                )[:_MAX_LIKES]:
                    likes_by_id.setdefault(rec.item_id, rec)

            if "subscriptions" in clean_sources:
                for rec in read_with_accounting(
                    self.ctx,
                    self.provider,
                    lambda: self.provider.get_user_subscriptions(
                        account_id, max_results=_MAX_SUBS
                    ),
                )[:_MAX_SUBS]:
                    subs_by_id.setdefault(rec.item_id, rec)

            if "playlists" in clean_sources:
                playlists = read_with_accounting(
                    self.ctx,
                    self.provider,
                    lambda: self.provider.get_user_playlists(
                        account_id, max_results=_MAX_PLAYLISTS
                    ),
                )[:_MAX_PLAYLISTS]
                for pl in playlists:
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
                    for idx, rec in enumerate(items):
                        dedup_key = (pid, rec.playlist_item_id or f"{rec.item_id}:{idx}")
                        playlist_entries.setdefault(dedup_key, rec)

            video_ids = list(
                dict.fromkeys(
                    [r.item_id for r in likes_by_id.values()]
                    + [r.item_id for r in playlist_entries.values()]
                )
            )
            videos: dict[str, VideoRecord] = {}
            for offset in range(0, len(video_ids), _BATCH_SIZE):
                batch = video_ids[offset : offset + _BATCH_SIZE]
                for video in read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.get_video_details, batch),
                ):
                    norm = normalise_video_record(video)
                    videos[norm.video_id] = norm

            sub_ids = list(subs_by_id.keys())
            sub_channels: dict[str, ChannelRecord] = {}
            for offset in range(0, len(sub_ids), _BATCH_SIZE):
                batch = sub_ids[offset : offset + _BATCH_SIZE]
                for channel in read_with_accounting(
                    self.ctx,
                    self.provider,
                    partial(self.provider.get_channels_details, batch),
                ):
                    normalised_channel = normalise_channel_record(channel)
                    sub_channels[normalised_channel.channel_id] = normalised_channel

            raw_categories = read_with_accounting(
                self.ctx,
                self.provider,
                lambda: self.provider.get_categories(),
            )
            categories_by_id = {
                str(cat["id"]): str(cat["title"])
                for cat in raw_categories
                if isinstance(cat, dict) and cat.get("id") and cat.get("title")
            }

            observations: list[_Observation] = []
            undated_by_source = {"likes": 0, "subscriptions": 0, "playlists": 0}

            def _resolve_video_obs(source_name: str, rec: AccountActivityRecord) -> None:
                video = videos.get(rec.item_id)
                if rec.timestamp is not None and rec.timestamp_provenance == "genuine":
                    ts = (
                        rec.timestamp.replace(tzinfo=UTC)
                        if rec.timestamp.tzinfo is None
                        else rec.timestamp.astimezone(UTC)
                    )
                    basis = "genuine"
                elif video is not None and video.published_at is not None:
                    ts = (
                        video.published_at.replace(tzinfo=UTC)
                        if video.published_at.tzinfo is None
                        else video.published_at.astimezone(UTC)
                    )
                    basis = "publication_fallback"
                else:
                    undated_by_source[source_name] += 1
                    return

                observations.append(
                    _Observation(
                        source=source_name,
                        item_id=rec.item_id,
                        timestamp=ts,
                        basis=basis,
                        channel_id=(video.channel_id if video else rec.channel_id) or None,
                        channel_title=video.channel_title if video else None,
                        category_id=video.category_id if video else None,
                        duration_seconds=video.duration_seconds if video else None,
                    )
                )

            for rec in likes_by_id.values():
                _resolve_video_obs("likes", rec)
            for rec in playlist_entries.values():
                _resolve_video_obs("playlists", rec)
            for cid, rec in subs_by_id.items():
                if rec.timestamp is not None and rec.timestamp_provenance == "genuine":
                    ts = (
                        rec.timestamp.replace(tzinfo=UTC)
                        if rec.timestamp.tzinfo is None
                        else rec.timestamp.astimezone(UTC)
                    )
                    ch = sub_channels.get(cid)
                    observations.append(
                        _Observation(
                            source="subscriptions",
                            item_id=cid,
                            timestamp=ts,
                            basis="genuine",
                            channel_id=cid,
                            channel_title=ch.title if ch else cid,
                            category_id=None,
                            duration_seconds=None,
                        )
                    )
                else:
                    undated_by_source["subscriptions"] += 1

            current_summary = _summarise_period(
                observations,
                undated_by_source,
                start=cur_start,
                end=cur_end,
                group_by=group_by,
                categories_by_id=categories_by_id,
            )

            warnings = list(current_summary["warnings"])
            comparison_payload: dict[str, Any] | None = None
            if comp_bounds is not None:
                base_start, base_end = comp_bounds
                baseline_summary = _summarise_period(
                    observations,
                    undated_by_source,
                    start=base_start,
                    end=base_end,
                    group_by=group_by,
                    categories_by_id=categories_by_id,
                )
                for w in baseline_summary["warnings"]:
                    if w not in warnings:
                        warnings.append(w)
                if (
                    current_summary["basis_counts"]["publication_fallback"] > 0
                    or baseline_summary["basis_counts"]["publication_fallback"] > 0
                ) and PUBLICATION_FALLBACK_WARNING not in warnings:
                    warnings.append(PUBLICATION_FALLBACK_WARNING)
                comparison_payload = {
                    "baseline": baseline_summary,
                    "deltas": _compare_periods(current_summary, baseline_summary),
                }

            summary_parts = [
                f"Analysed {current_summary['observation_count']} observation(s) across {', '.join(clean_sources)}."
            ]
            if comparison_payload is not None:
                delta_obs = comparison_payload["deltas"]["observation_count"]["absolute_delta"]
                summary_parts.append(
                    f"Comparison delta: {delta_obs:+d} observation(s) vs baseline."
                )
            if current_summary["observation_count"] < 10:
                summary_parts.append("Metrics are partial (<10 observations).")
            if any(w == PUBLICATION_FALLBACK_WARNING for w in warnings):
                summary_parts.append("Includes publication-date fallback points.")

            result: dict[str, Any] = {
                "sources": clean_sources,
                **current_summary,
                "warnings": warnings,
                "summary": " ".join(summary_parts),
            }
            if comparison_payload is not None:
                result["comparison"] = comparison_payload
            return result

        if isinstance(self.provider, ProviderGateway):
            with self.provider.operation_budget(_GENERAL_CAP, 0, context=self.ctx):
                return _run()
        preflight_non_gateway(self.ctx, self.provider, _GENERAL_CAP, 0)
        return _run()
