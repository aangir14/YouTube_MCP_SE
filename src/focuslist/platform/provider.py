"""Abstract interface definition for YouTube Data API operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from focuslist.types import AccountActivityRecord, ChannelRecord, VideoRecord


class VideoProvider(ABC):
    """Abstract interface isolating all YouTube API operations behind a typed boundary."""

    @abstractmethod
    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        """Fetch metadata for up to 50 videos in one batched call (costs 1 unit)."""
        ...

    @abstractmethod
    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        """Search for candidate videos matching the query (costs 100 units)."""
        ...

    @abstractmethod
    def get_channel_details(
        self,
        channel_id: str | None = None,
        handle: str | None = None,
    ) -> ChannelRecord | None:
        """Resolve channel metadata and public statistics (costs 1 unit)."""
        ...

    @abstractmethod
    def get_channel_recent_uploads(
        self,
        channel_id: str,
        max_results: int = 20,
    ) -> list[VideoRecord]:
        """Fetch recent uploads from the given channel (costs 1 unit per 50 items)."""
        ...

    @abstractmethod
    def get_user_likes(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        """Fetch authorized learner's liked videos (costs 1 unit per 50 items)."""
        ...

    @abstractmethod
    def get_user_subscriptions(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        """Fetch authorized learner's subscribed channels (costs 1 unit per 50 items)."""
        ...

    @abstractmethod
    def get_user_playlists(
        self,
        account_id: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch authorized learner's owned playlists (costs 1 unit per 50 items)."""
        ...

    @abstractmethod
    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        """Fetch available video categories for region (costs 1 unit, cached 7 days)."""
        ...

    @abstractmethod
    def check_channel_eligibility(self, account_id: str) -> bool:
        """Check whether the user has an active YouTube channel for playlist creation."""
        ...

    @abstractmethod
    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
    ) -> str:
        """Create a new playlist and return its ID (costs 50 units)."""
        ...

    @abstractmethod
    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
    ) -> str:
        """Insert a video into the specified playlist (costs 50 units per item)."""
        ...

    @abstractmethod
    def delete_playlist(self, playlist_id: str) -> bool:
        """Delete an owned playlist for confirmed undo (costs 50 units)."""
        ...
