"""Configurable fault-injection wrapper for simulating upstream YouTube API failures."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from focuslist.errors import (
    AuthCancelledError,
    AuthExpiredError,
    AuthRequiredError,
    ChannelUnavailableError,
    FocusListError,
    NetworkTimeoutError,
    NoYouTubeChannelError,
    QuotaBudgetExceededError,
    QuotaExhaustedError,
    RateLimitedError,
    UpstreamFailureError,
    UpstreamUnavailableError,
    VideoUnavailableError,
)
from focuslist.platform.provider import VideoProvider
from focuslist.platform.write_contracts import WriteAuthorizationContext
from focuslist.types import AccountActivityRecord, ChannelRecord, VideoRecord

NORMALIZED_FAULT_MAP: dict[str, Callable[[str | None], FocusListError]] = {
    "quota": QuotaExhaustedError,
    "quota_budget": QuotaBudgetExceededError,
    "rate": RateLimitedError,
    "unavailable": VideoUnavailableError,
    "channel_unavailable": ChannelUnavailableError,
    "timeout": NetworkTimeoutError,
    "no_channel": NoYouTubeChannelError,
    "auth": AuthExpiredError,
    "auth_required": AuthRequiredError,
    "auth_expired": AuthExpiredError,
    "auth_cancelled": AuthCancelledError,
    "upstream_500": UpstreamFailureError,
    "upstream_503": UpstreamUnavailableError,
}

# Faults that reject locally before any outbound network attempt
_PREFLIGHT_FAULT_KINDS = {"quota_budget", "auth_required", "auth_cancelled"}


class FaultInjectionProvider(VideoProvider):
    """Wraps any VideoProvider to inject configurable simulated failures (SRS FR-11.3)."""

    def __init__(self, target_provider: VideoProvider) -> None:
        self.target = target_provider
        self.fault_rules: dict[str, tuple[Exception, bool]] = {}
        self.remaining_fault_counts: dict[str, int] = {}
        self.requests: int = 0
        self.network_attempts: int = 0
        self.writes: int = 0
        self.faulted_calls: int = 0

    def reset_counters(self) -> None:
        """Reset fault-wrapper counters for isolated test assertions."""
        self.requests = 0
        self.network_attempts = 0
        self.writes = 0
        self.faulted_calls = 0

    def inject_fault(
        self,
        method_name: str,
        exception: Exception,
        count: int = 1,
        *,
        counts_as_attempt: bool = True,
    ) -> None:
        """Inject an exception to be raised on the next `count` invocations of `method_name`."""
        self.fault_rules[method_name] = (exception, counts_as_attempt)
        self.remaining_fault_counts[method_name] = count

    def inject_normalized_fault(
        self,
        method_name: str,
        fault_kind: str,
        count: int = 1,
        message: str | None = None,
    ) -> None:
        """Inject a normalized SRS FocusListError by canonical fault kind."""
        if fault_kind not in NORMALIZED_FAULT_MAP:
            valid = ", ".join(sorted(NORMALIZED_FAULT_MAP))
            raise ValueError(f"Unknown fault_kind '{fault_kind}'. Expected one of: {valid}")
        exc = NORMALIZED_FAULT_MAP[fault_kind](message or None)
        counts_as_attempt = fault_kind not in _PREFLIGHT_FAULT_KINDS
        self.inject_fault(method_name, exc, count=count, counts_as_attempt=counts_as_attempt)

    def clear_faults(self) -> None:
        """Clear all active fault injection rules."""
        self.fault_rules.clear()
        self.remaining_fault_counts.clear()

    def _before_call(self, method_name: str, *, is_write: bool = False) -> None:
        self.requests += 1
        if method_name in self.fault_rules and self.remaining_fault_counts.get(method_name, 0) > 0:
            self.remaining_fault_counts[method_name] -= 1
            exc, counts_as_attempt = self.fault_rules[method_name]
            if counts_as_attempt:
                self.network_attempts += 1
            self.faulted_calls += 1
            if self.remaining_fault_counts[method_name] <= 0:
                del self.fault_rules[method_name]
                del self.remaining_fault_counts[method_name]
            raise exc
        self.network_attempts += 1
        if is_write:
            self.writes += 1

    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        self._before_call("get_video_details")
        return self.target.get_video_details(video_ids)

    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        self._before_call("search_candidates")
        return self.target.search_candidates(query, max_results=max_results)

    def search_video_ids(self, query: str, max_results: int = 50) -> list[str]:
        self._before_call("search_video_ids")
        return self.target.search_video_ids(query, max_results=max_results)

    def search_channel_ids(self, query: str, max_results: int = 50) -> list[str]:
        self._before_call("search_channel_ids")
        return self.target.search_channel_ids(query, max_results=max_results)

    def get_channel_upload_ids(self, channel_id: str, max_results: int = 50) -> list[str]:
        self._before_call("get_channel_upload_ids")
        return self.target.get_channel_upload_ids(channel_id, max_results=max_results)

    def get_channel_details(
        self,
        channel_id: str | None = None,
        handle: str | None = None,
    ) -> ChannelRecord | None:
        self._before_call("get_channel_details")
        return self.target.get_channel_details(channel_id=channel_id, handle=handle)

    def get_channels_details(self, channel_ids: list[str]) -> list[ChannelRecord]:
        self._before_call("get_channels_details")
        return self.target.get_channels_details(channel_ids)

    def get_channel_recent_uploads(
        self,
        channel_id: str,
        max_results: int = 20,
    ) -> list[VideoRecord]:
        self._before_call("get_channel_recent_uploads")
        return self.target.get_channel_recent_uploads(channel_id, max_results=max_results)

    def get_user_likes(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self._before_call("get_user_likes")
        return self.target.get_user_likes(account_id, max_results=max_results)

    def get_user_subscriptions(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self._before_call("get_user_subscriptions")
        return self.target.get_user_subscriptions(account_id, max_results=max_results)

    def get_user_playlists(
        self,
        account_id: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        self._before_call("get_user_playlists")
        return self.target.get_user_playlists(account_id, max_results=max_results)

    def get_playlist_items(
        self,
        playlist_id: str,
        max_results: int = 100,
    ) -> list[AccountActivityRecord]:
        self._before_call("get_playlist_items")
        return self.target.get_playlist_items(playlist_id, max_results=max_results)

    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        self._before_call("get_categories")
        return self.target.get_categories(region_code=region_code)

    def check_channel_eligibility(self, account_id: str) -> bool:
        self._before_call("check_channel_eligibility")
        return self.target.check_channel_eligibility(account_id)

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
        *,
        write_context: WriteAuthorizationContext | None = None,
    ) -> str:
        self._before_call("create_playlist", is_write=True)
        return self.target.create_playlist(
            title, description, privacy=privacy, write_context=write_context,
        )

    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
        *,
        write_context: WriteAuthorizationContext | None = None,
    ) -> str:
        self._before_call("insert_playlist_item", is_write=True)
        return self.target.insert_playlist_item(
            playlist_id, video_id, position=position, write_context=write_context,
        )

    def delete_playlist(
        self, playlist_id: str, *, write_context: WriteAuthorizationContext | None = None,
    ) -> bool:
        self._before_call("delete_playlist", is_write=True)
        return self.target.delete_playlist(playlist_id, write_context=write_context)

    def list_playlist_items_for_reconciliation(
        self, playlist_id: str, max_results: int = 50,
    ) -> list[str]:
        self._before_call("list_playlist_items_for_reconciliation")
        return self.target.list_playlist_items_for_reconciliation(playlist_id, max_results)

    def find_created_playlist(self, title: str, description: str, privacy: str) -> str | None:
        self._before_call("find_created_playlist")
        return self.target.find_created_playlist(title, description, privacy)
