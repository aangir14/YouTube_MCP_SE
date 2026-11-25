"""Offline deterministic fixture provider replaying local synthetic JSON datasets."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from focuslist.platform.provider import VideoProvider
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    VideoRecord,
    sanitize_untrusted_text,
)


class FixtureVideoProvider(VideoProvider):
    """Deterministic offline provider reading from synthetic test datasets."""

    def __init__(self, fixture_dir: Path | str | None = None) -> None:
        if fixture_dir is None:
            self.fixture_dir = Path("tests/fixtures")
        else:
            self.fixture_dir = Path(fixture_dir)

        self.call_counts: dict[str, int] = defaultdict(int)
        self._videos: dict[str, VideoRecord] = {}
        self._channels: dict[str, ChannelRecord] = {}
        self._categories: list[dict[str, Any]] = []
        self._created_playlists: dict[str, dict[str, Any]] = {}
        self._load_fixtures()

    def _load_fixtures(self) -> None:
        """Load synthetic fixtures from JSON files if present."""
        videos_file = self.fixture_dir / "sample_videos.json"
        if videos_file.exists():
            with open(videos_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    item["title"] = sanitize_untrusted_text(item.get("title", ""))
                    item["description"] = sanitize_untrusted_text(item.get("description", ""))
                    v = VideoRecord(**item)
                    self._videos[v.video_id] = v

        channels_file = self.fixture_dir / "sample_channels.json"
        if channels_file.exists():
            with open(channels_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    item["title"] = sanitize_untrusted_text(item.get("title", ""))
                    c = ChannelRecord(**item)
                    self._channels[c.channel_id] = c

        categories_file = self.fixture_dir / "sample_categories.json"
        if categories_file.exists():
            with open(categories_file, "r", encoding="utf-8") as f:
                self._categories = json.load(f)

    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        self.call_counts["get_video_details"] += 1
        results: list[VideoRecord] = []
        for vid in video_ids:
            if vid in self._videos:
                results.append(self._videos[vid])
        return results

    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        self.call_counts["search_candidates"] += 1
        q_lower = query.lower()
        matched: list[VideoRecord] = []
        for v in self._videos.values():
            if q_lower in v.title.lower() or any(q_lower in tag.lower() for tag in v.tags):
                matched.append(v)
            if len(matched) >= max_results:
                break
        # Fallback to returning available candidates if search matches none
        if not matched:
            matched = list(self._videos.values())[:max_results]
        return matched

    def get_channel_details(
        self,
        channel_id: str | None = None,
        handle: str | None = None,
    ) -> ChannelRecord | None:
        self.call_counts["get_channel_details"] += 1
        if channel_id and channel_id in self._channels:
            return self._channels[channel_id]
        if handle:
            h_clean = handle.lstrip("@").lower()
            for c in self._channels.values():
                if c.handle and c.handle.lstrip("@").lower() == h_clean:
                    return c
        # If any channel exists, return first as mock fallback
        if self._channels:
            return next(iter(self._channels.values()))
        return None

    def get_channel_recent_uploads(
        self,
        channel_id: str,
        max_results: int = 20,
    ) -> list[VideoRecord]:
        self.call_counts["get_channel_recent_uploads"] += 1
        res = [v for v in self._videos.values() if v.channel_id == channel_id]
        return res[:max_results]

    def get_user_likes(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self.call_counts["get_user_likes"] += 1
        return [
            AccountActivityRecord(
                item_id=v.video_id,
                activity_type="like",
                account_id=account_id,
                channel_id=v.channel_id,
                timestamp_provenance="genuine",
            )
            for v in list(self._videos.values())[:max_results]
        ]

    def get_user_subscriptions(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self.call_counts["get_user_subscriptions"] += 1
        return [
            AccountActivityRecord(
                item_id=c.channel_id,
                activity_type="subscription",
                account_id=account_id,
                channel_id=c.channel_id,
                timestamp_provenance="genuine",
            )
            for c in list(self._channels.values())[:max_results]
        ]

    def get_user_playlists(
        self,
        account_id: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        self.call_counts["get_user_playlists"] += 1
        return [
            {
                "playlist_id": pid,
                "title": p["title"],
                "item_count": len(p["items"]),
                "privacy": p["privacy"],
            }
            for pid, p in self._created_playlists.items()
        ][:max_results]

    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        self.call_counts["get_categories"] += 1
        if self._categories:
            return self._categories
        return [
            {"id": "10", "title": "Music"},
            {"id": "27", "title": "Education"},
            {"id": "28", "title": "Science & Technology"},
        ]

    def check_channel_eligibility(self, account_id: str) -> bool:
        self.call_counts["check_channel_eligibility"] += 1
        return True

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
    ) -> str:
        self.call_counts["create_playlist"] += 1
        pid = f"PL_syn_{len(self._created_playlists) + 1:04d}"
        self._created_playlists[pid] = {
            "title": title,
            "description": description,
            "privacy": privacy,
            "items": [],
        }
        return pid

    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
    ) -> str:
        self.call_counts["insert_playlist_item"] += 1
        if playlist_id not in self._created_playlists:
            self._created_playlists[playlist_id] = {
                "title": "Ad-hoc Playlist",
                "description": "",
                "privacy": "private",
                "items": [],
            }
        item_id = f"PLI_syn_{len(self._created_playlists[playlist_id]['items']) + 1:04d}"
        self._created_playlists[playlist_id]["items"].append(video_id)
        return item_id

    def delete_playlist(self, playlist_id: str) -> bool:
        self.call_counts["delete_playlist"] += 1
        if playlist_id in self._created_playlists:
            del self._created_playlists[playlist_id]
            return True
        return False
