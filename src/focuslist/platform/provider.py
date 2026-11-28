"""Abstract interface definition for YouTube Data API operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from focuslist.platform.write_contracts import WriteAuthorizationContext
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    PlaylistInfo,
    PlaylistPage,
    VideoRecord,
)


class VideoProvider(ABC):
    """Abstract interface isolating all YouTube API operations behind a typed boundary."""

    network_attempts: int

    @abstractmethod
    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        """Fetch metadata for up to 50 videos in one batched call (costs 1 unit)."""
        ...

    @abstractmethod
    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        """Search for candidate videos matching the query (costs 100 units)."""
        ...

    @abstractmethod
    def search_video_ids(self, query: str, max_results: int = 50) -> list[str]:
        """Read at most one search page of IDs, without fetching video details."""
        ...

    @abstractmethod
    def search_channel_ids(self, query: str, max_results: int = 50) -> list[str]:
        """Read at most one search page of channel IDs, without fetching channel details."""
        ...

    @abstractmethod
    def get_channel_upload_ids(self, channel_id: str, max_results: int = 50) -> list[str]:
        """Resolve the uploads playlist and read at most one page of video IDs."""
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
    def get_channels_details(self, channel_ids: list[str]) -> list[ChannelRecord]:
        """Fetch metadata for up to 50 channels in one batched call (costs 1 unit)."""
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
    def get_playlist_items(
        self,
        playlist_id: str,
        max_results: int = 100,
    ) -> list[AccountActivityRecord]:
        """Fetch entries in a playlist (costs 1 unit per 50 items)."""
        ...

    @abstractmethod
    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        """Fetch available video categories for region (costs 1 unit, cached 7 days)."""
        ...

    def get_playlist_info(self, playlist_id: str) -> PlaylistInfo:
        """Verify readability and get the item count in one playlist lookup."""
        raise NotImplementedError

    def get_playlist_page(
        self, playlist_id: str, page_token: str | None = None, *, page_size: int = 50,
    ) -> PlaylistPage:
        """Read one page of positions, including unavailable placeholders."""
        raise NotImplementedError

    @abstractmethod
    def check_channel_eligibility(self, account_id: str) -> bool:
        """Check whether the user has an active YouTube channel for playlist creation."""
        ...

    def owned_channel_ids(self, account_id: str) -> tuple[str, ...]:
        """Return the channel identities needed to verify an incremental OAuth upgrade."""
        return ()

    def find_created_playlist(self, title: str, description: str, privacy: str) -> str | None:
        """Return a unique match for the signed creation marker, if one is visible."""
        return None

    def list_playlist_items_for_reconciliation(
        self, playlist_id: str, max_results: int = 50,
    ) -> list[str]:
        """Return a complete small playlist in confirmed position order."""
        raise NotImplementedError

    @abstractmethod
    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
        *,
        write_context: WriteAuthorizationContext | None = None,
    ) -> str:
        """Create a new playlist and return its ID (costs 50 units)."""
        ...

    @abstractmethod
    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
        *,
        write_context: WriteAuthorizationContext | None = None,
    ) -> str:
        """Insert a video into the specified playlist (costs 50 units per item)."""
        ...

    @abstractmethod
    def delete_playlist(
        self, playlist_id: str, *, write_context: WriteAuthorizationContext | None = None,
    ) -> bool:
        """Delete an owned playlist for confirmed undo (costs 50 units)."""
        ...
