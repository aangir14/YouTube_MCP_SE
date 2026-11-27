"""Quota-enforcing, cache-backed provider gateway implementing COM-5 retries (C16)."""

from __future__ import annotations

import contextvars
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from focuslist.clock import Clock, SystemClock
from focuslist.config import Settings, get_settings
from focuslist.context import RequestContext
from focuslist.errors import (
    FocusListError,
    NetworkTimeoutError,
    QuotaExhaustedError,
    RateLimitedError,
    UpstreamFailureError,
    UpstreamUnavailableError,
)
from focuslist.metadata import normalise_channel_record, normalise_video_record
from focuslist.platform.provider import VideoProvider
from focuslist.platform.quota import METHOD_COSTS, QuotaManager, QuotaReservation
from focuslist.platform.storage import FocusListStorage
from focuslist.platform.write_contracts import AmbiguousWriteError
from focuslist.types import AccountActivityRecord, ChannelRecord, VideoRecord

_T = TypeVar("_T")

_RETRYABLE_READ_ERRORS = (
    NetworkTimeoutError,
    UpstreamFailureError,
    UpstreamUnavailableError,
)

_MAX_BATCH_SIZE = 50


@dataclass
class _GatewayScope:
    reservation: QuotaReservation | None
    context: RequestContext | None
    units_spent: int = 0
    searches_spent: int = 0
    cache_hits: int = 0


_active_scope: contextvars.ContextVar[_GatewayScope | None] = contextvars.ContextVar(
    "focuslist_gateway_scope", default=None
)


class ProviderGateway(VideoProvider):
    """Single platform gateway owning cache access, quota accounting, and COM-5 retries."""

    def __init__(
        self,
        provider: VideoProvider,
        *,
        storage: FocusListStorage,
        quota_manager: QuotaManager | None = None,
        settings: Settings | None = None,
        clock: Clock | None = None,
        cache_enabled: bool | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        jitter_fn: Callable[[float], float] | None = None,
    ) -> None:
        self.provider = provider
        self.storage = storage
        self.settings = settings or get_settings()
        self.clock: Clock = clock or storage.clock or SystemClock()
        self.quota_manager = quota_manager or QuotaManager(
            storage=storage, settings=self.settings, clock=self.clock
        )
        self.cache_enabled = (
            self.settings.cache_enabled if cache_enabled is None else cache_enabled
        )
        self._sleep = sleep_fn or time.sleep
        self._jitter = jitter_fn or (lambda max_j: random.uniform(0.0, max_j))

        self.requests: int = 0
        self.network_attempts: int = 0
        self.writes: int = 0
        self.cache_hits: int = 0
        self._live_observed_during_call: list[tuple[str, int]] = []
        self._previous_live_observer: Callable[[str, int], None] | None = None

        # Hook LiveVideoProvider's attempt observer if wrapping a LiveVideoProvider
        if hasattr(self.provider, "_attempt_observer"):
            self._previous_live_observer = self.provider._attempt_observer
            self.provider._attempt_observer = self._on_live_attempt

    def _on_live_attempt(self, endpoint_name: str, count: int) -> None:
        self._live_observed_during_call.append((endpoint_name, count))
        if self._previous_live_observer is not None:
            self._previous_live_observer(endpoint_name, count)

    def reset_counters(self) -> None:
        """Reset gateway instrumentation counters (delegating to inner provider if supported)."""
        self.requests = 0
        self.network_attempts = 0
        self.writes = 0
        self.cache_hits = 0
        if hasattr(self.provider, "reset_counters"):
            self.provider.reset_counters()

    @contextmanager
    def operation_budget(
        self,
        worst_case_units: int,
        worst_case_searches: int = 0,
        *,
        context: RequestContext | None = None,
        scheduled_live_mode: bool | None = None,
    ) -> Iterator[_GatewayScope]:
        """Atomically preflight and reserve budget for a multi-call tool workflow."""
        reservation = self.quota_manager.reserve(
            worst_case_units,
            worst_case_searches,
            scheduled_live_mode=scheduled_live_mode,
        )
        scope = _GatewayScope(reservation=reservation, context=context)
        token = _active_scope.set(scope)
        try:
            yield scope
        finally:
            try:
                self.quota_manager.release_reservation(reservation)
                if context is not None:
                    snap = self.quota_manager.get_status()
                    context.set_quota_remaining(snap.general_units_remaining)
            finally:
                _active_scope.reset(token)

    def _record_cache_hit(self, count: int = 1) -> None:
        if count <= 0:
            return
        self.cache_hits += count
        self.quota_manager.record_cache_hit(count)
        scope = _active_scope.get()
        if scope is not None:
            scope.cache_hits += count
            if scope.context is not None:
                scope.context.record_cache_hit(count)

    def _charge_events(
        self,
        events: list[tuple[str, int]],
        scope: _GatewayScope | None,
        reservation: QuotaReservation | None,
    ) -> None:
        total_u = 0
        total_s = 0
        for name, count in events:
            u, s = METHOD_COSTS.get(name, (1, 0))
            total_u += u * count
            total_s += s * count
        if total_u or total_s:
            self.quota_manager.charge_attempt(total_u, total_s, reservation=reservation)
            if scope is not None:
                scope.units_spent += total_u
                scope.searches_spent += total_s
                if scope.context is not None:
                    if total_u:
                        scope.context.record_quota_charge(total_u)
                    if total_s:
                        scope.context.record_search_charge(total_s)
        if scope is not None and scope.context is not None:
            snap = self.quota_manager.get_status()
            scope.context.set_quota_remaining(snap.general_units_remaining)

    def _execute_with_accounting(
        self,
        method_name: str,
        fn: Callable[[], _T],
        *,
        is_write: bool = False,
        expected_units: int | None = None,
        expected_searches: int | None = None,
    ) -> _T:
        """Execute a provider method with atomic preflight, per-attempt charging, and COM-5 retry."""
        self.requests += 1
        default_u, default_s = METHOD_COSTS.get(method_name, (1, 0))
        req_u = default_u if expected_units is None else expected_units
        req_s = default_s if expected_searches is None else expected_searches

        scope = _active_scope.get()
        local_reservation: QuotaReservation | None = None
        reservation = scope.reservation if scope is not None else None
        if reservation is None:
            local_reservation = self.quota_manager.reserve(req_u, req_s)
            reservation = local_reservation

        is_live = hasattr(self.provider, "_attempt_observer")
        retries_remaining = 0 if is_write else self.settings.max_retries
        attempt_idx = 0

        try:
            while True:
                self._live_observed_during_call.clear()
                before_attempts = getattr(self.provider, "network_attempts", 0)
                try:
                    result = fn()
                except FocusListError as exc:
                    self._commit_attempt_delta(
                        method_name,
                        before_attempts,
                        is_live=is_live,
                        scope=scope,
                        reservation=reservation,
                    )
                    if isinstance(exc, QuotaExhaustedError):
                        bucket = "search" if req_s > 0 and req_u == 0 else "general"
                        self.quota_manager.mark_exhausted(bucket)
                        raise
                    if isinstance(exc, RateLimitedError):
                        bucket = "search" if req_s > 0 and req_u == 0 else "general"
                        self.quota_manager.mark_exhausted(bucket)
                        raise

                    if is_write:
                        if isinstance(exc, NetworkTimeoutError) and not isinstance(
                            exc, AmbiguousWriteError
                        ):
                            raise AmbiguousWriteError(method_name) from exc
                        raise

                    if (
                        isinstance(exc, _RETRYABLE_READ_ERRORS)
                        and retries_remaining > 0
                        and self.quota_manager.can_afford_retry(
                            default_u, default_s, reservation=reservation
                        )
                    ):
                        retries_remaining -= 1
                        backoff = (0.5 * (2**attempt_idx)) + self._jitter(0.25)
                        attempt_idx += 1
                        self._sleep(backoff)
                        continue
                    raise
                else:
                    self._commit_attempt_delta(
                        method_name,
                        before_attempts,
                        is_live=is_live,
                        scope=scope,
                        reservation=reservation,
                    )
                    if is_write:
                        self.writes += 1
                    return result
        finally:
            if local_reservation is not None:
                self.quota_manager.release_reservation(local_reservation)

    def _commit_attempt_delta(
        self,
        method_name: str,
        before_attempts: int,
        *,
        is_live: bool,
        scope: _GatewayScope | None,
        reservation: QuotaReservation | None,
    ) -> None:
        if is_live and self._live_observed_during_call:
            observed = list(self._live_observed_during_call)
            self._live_observed_during_call.clear()
            self.network_attempts += sum(c for _, c in observed)
            self._charge_events(observed, scope, reservation)
            return

        after_attempts = getattr(self.provider, "network_attempts", before_attempts + 1)
        delta = max(0, after_attempts - before_attempts)
        if delta > 0:
            self.network_attempts += delta
            self._charge_events([(method_name, delta)], scope, reservation)

    # ==========================================================================
    # VideoProvider Interface (with Cache + Quota + Retries)
    # ==========================================================================

    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        deduped = list(dict.fromkeys(vid for vid in video_ids if vid))
        if not deduped:
            return []

        cached_by_id: dict[str, VideoRecord] = {}
        missing_ids: list[str] = []
        if self.cache_enabled:
            for vid in deduped:
                cached = self.storage.get_cache(
                    "video_detail", {"video_id": vid}, category="video"
                )
                if cached is not None:
                    cached_by_id[vid] = normalise_video_record(VideoRecord(**cached))
                else:
                    missing_ids.append(vid)
            if cached_by_id:
                self._record_cache_hit(len(cached_by_id))
        else:
            missing_ids = deduped

        fetched_by_id: dict[str, VideoRecord] = {}
        if missing_ids:
            batches = max(1, (len(missing_ids) + _MAX_BATCH_SIZE - 1) // _MAX_BATCH_SIZE)
            records = self._execute_with_accounting(
                "get_video_details",
                lambda: self.provider.get_video_details(missing_ids),
                expected_units=batches,
                expected_searches=0,
            )
            for rec in records:
                norm = normalise_video_record(rec)
                fetched_by_id[norm.video_id] = norm
                if self.cache_enabled:
                    self.storage.set_cache(
                        "video_detail",
                        {"video_id": norm.video_id},
                        "video",
                        norm.model_dump(mode="json"),
                    )

        combined: list[VideoRecord] = []
        for vid in deduped:
            if vid in cached_by_id:
                combined.append(cached_by_id[vid])
            elif vid in fetched_by_id:
                combined.append(fetched_by_id[vid])
        return combined

    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        return self._execute_with_accounting(
            "search_candidates",
            lambda: self.provider.search_candidates(query, max_results=max_results),
            expected_units=0,
            expected_searches=1,
        )

    def search_video_ids(self, query: str, max_results: int = 50) -> list[str]:
        return self._execute_with_accounting(
            "search_video_ids",
            lambda: self.provider.search_video_ids(query, max_results=max_results),
            expected_units=0,
            expected_searches=1,
        )

    def search_channel_ids(self, query: str, max_results: int = 50) -> list[str]:
        return self._execute_with_accounting(
            "search_channel_ids",
            lambda: self.provider.search_channel_ids(query, max_results=max_results),
            expected_units=0,
            expected_searches=1,
        )

    def get_channel_upload_ids(self, channel_id: str, max_results: int = 50) -> list[str]:
        return self._execute_with_accounting(
            "get_channel_upload_ids",
            lambda: self.provider.get_channel_upload_ids(channel_id, max_results=max_results),
            expected_units=1,
            expected_searches=0,
        )

    def get_channel_details(
        self,
        channel_id: str | None = None,
        handle: str | None = None,
    ) -> ChannelRecord | None:
        norm_handle = handle.lstrip("@").casefold() if handle else None
        params = {"channel_id": channel_id, "handle": norm_handle}
        if self.cache_enabled:
            cached = self.storage.get_cache("channel_detail", params, category="channel")
            if cached is not None:
                self._record_cache_hit(1)
                return normalise_channel_record(ChannelRecord(**cached))

        record = self._execute_with_accounting(
            "get_channel_details",
            lambda: self.provider.get_channel_details(channel_id=channel_id, handle=handle),
            expected_units=1,
            expected_searches=0,
        )
        if record is not None and self.cache_enabled:
            norm = normalise_channel_record(record)
            self.storage.set_cache(
                "channel_detail", params, "channel", norm.model_dump(mode="json")
            )
            return norm
        return record

    def get_channels_details(self, channel_ids: list[str]) -> list[ChannelRecord]:
        deduped = list(dict.fromkeys(cid for cid in channel_ids if cid))
        if not deduped:
            return []

        cached_by_id: dict[str, ChannelRecord] = {}
        missing_ids: list[str] = []
        if self.cache_enabled:
            for cid in deduped:
                cached = self.storage.get_cache(
                    "channel_detail", {"channel_id": cid, "handle": None}, category="channel"
                )
                if cached is not None:
                    cached_by_id[cid] = normalise_channel_record(ChannelRecord(**cached))
                else:
                    missing_ids.append(cid)
            if cached_by_id:
                self._record_cache_hit(len(cached_by_id))
        else:
            missing_ids = deduped

        fetched_by_id: dict[str, ChannelRecord] = {}
        if missing_ids:
            batches = max(1, (len(missing_ids) + _MAX_BATCH_SIZE - 1) // _MAX_BATCH_SIZE)
            records = self._execute_with_accounting(
                "get_channels_details",
                lambda: self.provider.get_channels_details(missing_ids),
                expected_units=batches,
                expected_searches=0,
            )
            for rec in records:
                norm = normalise_channel_record(rec)
                fetched_by_id[norm.channel_id] = norm
                if self.cache_enabled:
                    self.storage.set_cache(
                        "channel_detail",
                        {"channel_id": norm.channel_id, "handle": None},
                        "channel",
                        norm.model_dump(mode="json"),
                    )

        return [
            cached_by_id[cid] if cid in cached_by_id else fetched_by_id[cid]
            for cid in deduped
            if cid in cached_by_id or cid in fetched_by_id
        ]

    def get_channel_recent_uploads(
        self,
        channel_id: str,
        max_results: int = 20,
    ) -> list[VideoRecord]:
        return self._execute_with_accounting(
            "get_channel_recent_uploads",
            lambda: self.provider.get_channel_recent_uploads(channel_id, max_results=max_results),
            expected_units=1,
            expected_searches=0,
        )

    def get_user_likes(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        params = {"max_results": max_results}
        if self.cache_enabled and account_id:
            cached = self.storage.get_cache(
                "user_likes", params, category="user", account_id=account_id
            )
            if cached is not None:
                self._record_cache_hit(1)
                return [AccountActivityRecord(**item) for item in cached]

        records = self._execute_with_accounting(
            "get_user_likes",
            lambda: self.provider.get_user_likes(account_id, max_results=max_results),
            expected_units=1,
            expected_searches=0,
        )
        if self.cache_enabled and account_id:
            self.storage.set_cache(
                "user_likes",
                params,
                "user",
                [r.model_dump(mode="json") for r in records],
                account_id=account_id,
            )
        return records

    def get_user_subscriptions(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        params = {"max_results": max_results}
        if self.cache_enabled and account_id:
            cached = self.storage.get_cache(
                "user_subscriptions", params, category="user", account_id=account_id
            )
            if cached is not None:
                self._record_cache_hit(1)
                return [AccountActivityRecord(**item) for item in cached]

        records = self._execute_with_accounting(
            "get_user_subscriptions",
            lambda: self.provider.get_user_subscriptions(account_id, max_results=max_results),
            expected_units=1,
            expected_searches=0,
        )
        if self.cache_enabled and account_id:
            self.storage.set_cache(
                "user_subscriptions",
                params,
                "user",
                [r.model_dump(mode="json") for r in records],
                account_id=account_id,
            )
        return records

    def get_user_playlists(
        self,
        account_id: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        params = {"max_results": max_results}
        if self.cache_enabled and account_id:
            cached = self.storage.get_cache(
                "user_playlists", params, category="user", account_id=account_id
            )
            if cached is not None:
                self._record_cache_hit(1)
                return list(cached)

        playlists = self._execute_with_accounting(
            "get_user_playlists",
            lambda: self.provider.get_user_playlists(account_id, max_results=max_results),
            expected_units=1,
            expected_searches=0,
        )
        if self.cache_enabled and account_id:
            self.storage.set_cache(
                "user_playlists", params, "user", playlists, account_id=account_id
            )
        return playlists

    def get_playlist_items(
        self,
        playlist_id: str,
        max_results: int = 100,
    ) -> list[AccountActivityRecord]:
        cap = max(1, min(max_results, 100))
        pages = max(1, (cap + _MAX_BATCH_SIZE - 1) // _MAX_BATCH_SIZE)
        return self._execute_with_accounting(
            "get_playlist_items",
            lambda: self.provider.get_playlist_items(playlist_id, max_results=cap),
            expected_units=pages,
            expected_searches=0,
        )

    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        params = {"region_code": region_code}
        if self.cache_enabled:
            cached = self.storage.get_cache("categories", params, category="category")
            if cached is not None:
                self._record_cache_hit(1)
                return list(cached)

        categories = self._execute_with_accounting(
            "get_categories",
            lambda: self.provider.get_categories(region_code=region_code),
            expected_units=1,
            expected_searches=0,
        )
        if self.cache_enabled:
            self.storage.set_cache("categories", params, "category", categories)
        return categories

    def check_channel_eligibility(self, account_id: str) -> bool:
        return self._execute_with_accounting(
            "check_channel_eligibility",
            lambda: self.provider.check_channel_eligibility(account_id),
            expected_units=1,
            expected_searches=0,
        )

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
        **kwargs: Any,
    ) -> str:
        return self._execute_with_accounting(
            "create_playlist",
            lambda: self.provider.create_playlist(title, description, privacy=privacy, **kwargs),
            is_write=True,
            expected_units=50,
            expected_searches=0,
        )

    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
        **kwargs: Any,
    ) -> str:
        return self._execute_with_accounting(
            "insert_playlist_item",
            lambda: self.provider.insert_playlist_item(
                playlist_id, video_id, position=position, **kwargs
            ),
            is_write=True,
            expected_units=50,
            expected_searches=0,
        )

    def delete_playlist(self, playlist_id: str, **kwargs: Any) -> bool:
        return self._execute_with_accounting(
            "delete_playlist",
            lambda: self.provider.delete_playlist(playlist_id, **kwargs),
            is_write=True,
            expected_units=50,
            expected_searches=0,
        )
