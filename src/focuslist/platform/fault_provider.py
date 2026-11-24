"""Configurable fault-injection wrapper for simulating upstream YouTube API failures."""

from __future__ import annotations

from typing import Any

from focuslist.platform.provider import VideoProvider
from focuslist.types import AccountActivityRecord, ChannelRecord, VideoRecord


class FaultInjectionProvider(VideoProvider):
    """Wraps any VideoProvider to inject configurable simulated failures (SRS FR-11.3)."""

    def __init__(self, target_provider: VideoProvider) -> None:
        self.target = target_provider
        self.fault_rules: dict[str, Exception] = {}
        self.remaining_fault_counts: dict[str, int] = {}

    def inject_fault(self, method_name: str, exception: Exception, count: int = 1) -> None:
        """Inject an exception to be raised on the next `count` invocations of `method_name`."""
        self.fault_rules[method_name] = exception
        self.remaining_fault_counts[method_name] = count

    def clear_faults(self) -> None:
        """Clear all active fault injection rules."""
        self.fault_rules.clear()
        self.remaining_fault_counts.clear()

    def _check_and_raise(self, method_name: str) -> None:
        if method_name in self.fault_rules and self.remaining_fault_counts.get(method_name, 0) > 0:
            self.remaining_fault_counts[method_name] -= 1
            exc = self.fault_rules[method_name]
            if self.remaining_fault_counts[method_name] <= 0:
                del self.fault_rules[method_name]
                del self.remaining_fault_counts[method_name]
            raise exc

    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        self._check_and_raise("get_video_details")
        return self.target.get_video_details(video_ids)

    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        self._check_and_raise("search_candidates")
        return self.target.search_candidates(query, max_results=max_results)

    def get_channel_details(
        self,
        channel_id: str | None = None,
        handle: str | None = None,
    ) -> ChannelRecord | None:
        self._check_and_raise("get_channel_details")
        return self.target.get_channel_details(channel_id=channel_id, handle=handle)

    def get_channel_recent_uploads(
        self,
        channel_id: str,
        max_results: int = 20,
    ) -> list[VideoRecord]:
        self._check_and_raise("get_channel_recent_uploads")
        return self.target.get_channel_recent_uploads(channel_id, max_results=max_results)

    def get_user_likes(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self._check_and_raise("get_user_likes")
        return self.target.get_user_likes(account_id, max_results=max_results)

    def get_user_subscriptions(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self._check_and_raise("get_user_subscriptions")
        return self.target.get_user_subscriptions(account_id, max_results=max_results)

    def get_user_playlists(
        self,
        account_id: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        self._check_and_raise("get_user_playlists")
        return self.target.get_user_playlists(account_id, max_results=max_results)

    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        self._check_and_raise("get_categories")
        return self.target.get_categories(region_code=region_code)

    def check_channel_eligibility(self, account_id: str) -> bool:
        self._check_and_raise("check_channel_eligibility")
        return self.target.check_channel_eligibility(account_id)

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
    ) -> str:
        self._check_and_raise("create_playlist")
        return self.target.create_playlist(title, description, privacy=privacy)

    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
    ) -> str:
        self._check_and_raise("insert_playlist_item")
        return self.target.insert_playlist_item(playlist_id, video_id, position=position)

    def delete_playlist(self, playlist_id: str) -> bool:
        self._check_and_raise("delete_playlist")
        return self.target.delete_playlist(playlist_id)
