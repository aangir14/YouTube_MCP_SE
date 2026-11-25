"""Offline deterministic fixture provider replaying local synthetic JSON datasets."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from focuslist.metadata import normalise_channel_record, normalise_video_record
from focuslist.platform.provider import VideoProvider
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    VideoRecord,
)


class FixtureVideoProvider(VideoProvider):
    """Deterministic offline provider reading from synthetic test datasets."""

    def __init__(self, fixture_dir: Path | str | None = None) -> None:
        if fixture_dir is None:
            self.fixture_dir = Path("tests/fixtures")
        else:
            self.fixture_dir = Path(fixture_dir)

        self.call_counts: dict[str, int] = defaultdict(int)
        self.call_log: list[dict[str, Any]] = []
        self.requests: int = 0
        self.network_attempts: int = 0
        self.writes: int = 0
        self._videos: dict[str, VideoRecord] = {}
        self._channels: dict[str, ChannelRecord] = {}
        self._categories: list[dict[str, Any]] = []
        self._created_playlists: dict[str, dict[str, Any]] = {}
        self._load_fixtures()

    def reset_counters(self) -> None:
        """Reset instrumentation counters and call log for isolated test assertions."""
        self.call_counts.clear()
        self.call_log.clear()
        self.requests = 0
        self.network_attempts = 0
        self.writes = 0

    def _record_call(
        self,
        method: str,
        *,
        is_write: bool = False,
        network_attempt: bool = True,
        **args: Any,
    ) -> None:
        self.call_counts[method] += 1
        self.requests += 1
        if network_attempt:
            self.network_attempts += 1
        if is_write:
            self.writes += 1
        self.call_log.append(
            {
                "method": method,
                "args": args,
                "is_write": is_write,
                "network_attempt": network_attempt,
            }
        )

    def _load_fixtures(self) -> None:
        """Load synthetic fixtures from JSON files if present."""
        videos_file = self.fixture_dir / "sample_videos.json"
        if videos_file.exists():
            with open(videos_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    v = normalise_video_record(VideoRecord(**item))
                    self._videos[v.video_id] = v

        channels_file = self.fixture_dir / "sample_channels.json"
        if channels_file.exists():
            with open(channels_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    c = normalise_channel_record(ChannelRecord(**item))
                    self._channels[c.channel_id] = c

        categories_file = self.fixture_dir / "sample_categories.json"
        if categories_file.exists():
            with open(categories_file, "r", encoding="utf-8") as f:
                self._categories = json.load(f)

    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        self._record_call("get_video_details", video_ids=list(video_ids))
        results: list[VideoRecord] = []
        for vid in video_ids:
            if vid in self._videos:
                results.append(self._videos[vid])
        return results

    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        self._record_call("search_candidates", query=query, max_results=max_results)
        q_lower = query.lower()
        ordered_videos = sorted(self._videos.values(), key=lambda v: v.video_id)
        matched: list[VideoRecord] = []
        for v in ordered_videos:
            if q_lower in v.title.lower() or any(q_lower in tag.lower() for tag in v.tags or ()):
                matched.append(v)
            if len(matched) >= max_results:
                break
        # Fallback to returning available candidates deterministically if search matches none
        if not matched:
            matched = ordered_videos[:max_results]
        return matched

    def get_channel_details(
        self,
        channel_id: str | None = None,
        handle: str | None = None,
    ) -> ChannelRecord | None:
        self._record_call("get_channel_details", channel_id=channel_id, handle=handle)
        if channel_id and channel_id in self._channels:
            return self._channels[channel_id]
        if handle:
            h_clean = handle.lstrip("@").casefold()
            for cid in sorted(self._channels):
                c = self._channels[cid]
                if c.handle and c.handle.lstrip("@").casefold() == h_clean:
                    return c
        return None

    def get_channel_recent_uploads(
        self,
        channel_id: str,
        max_results: int = 20,
    ) -> list[VideoRecord]:
        self._record_call(
            "get_channel_recent_uploads", channel_id=channel_id, max_results=max_results
        )
        res = sorted(
            (v for v in self._videos.values() if v.channel_id == channel_id),
            key=lambda v: v.video_id,
        )
        return res[:max_results]

    def get_user_likes(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self._record_call("get_user_likes", account_id=account_id, max_results=max_results)
        ordered_videos = sorted(self._videos.values(), key=lambda v: v.video_id)
        return [
            AccountActivityRecord(
                item_id=v.video_id,
                activity_type="like",
                account_id=account_id,
                channel_id=v.channel_id,
                timestamp_provenance="genuine",
            )
            for v in ordered_videos[:max_results]
        ]

    def get_user_subscriptions(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self._record_call(
            "get_user_subscriptions", account_id=account_id, max_results=max_results
        )
        ordered_channels = sorted(self._channels.values(), key=lambda c: c.channel_id)
        return [
            AccountActivityRecord(
                item_id=c.channel_id,
                activity_type="subscription",
                account_id=account_id,
                channel_id=c.channel_id,
                timestamp_provenance="genuine",
            )
            for c in ordered_channels[:max_results]
        ]

    def get_user_playlists(
        self,
        account_id: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        self._record_call("get_user_playlists", account_id=account_id, max_results=max_results)
        return [
            {
                "playlist_id": pid,
                "title": p["title"],
                "item_count": len(p["items"]),
                "privacy": p["privacy"],
            }
            for pid, p in sorted(self._created_playlists.items())
        ][:max_results]

    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        self._record_call("get_categories", region_code=region_code)
        if self._categories:
            return sorted(self._categories, key=lambda c: str(c.get("id", "")))
        return [
            {"id": "10", "title": "Music"},
            {"id": "27", "title": "Education"},
            {"id": "28", "title": "Science & Technology"},
        ]

    def check_channel_eligibility(self, account_id: str) -> bool:
        self._record_call("check_channel_eligibility", account_id=account_id)
        return True

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
    ) -> str:
        self._record_call(
            "create_playlist", is_write=True, title=title, privacy=privacy
        )
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
        self._record_call(
            "insert_playlist_item",
            is_write=True,
            playlist_id=playlist_id,
            video_id=video_id,
            position=position,
        )
        if playlist_id not in self._created_playlists:
            self._created_playlists[playlist_id] = {
                "title": "Ad-hoc Playlist",
                "description": "",
                "privacy": "private",
                "items": [],
            }
        items = self._created_playlists[playlist_id]["items"]
        item_id = f"PLI_syn_{len(items) + 1:04d}"
        if position is not None and 0 <= position <= len(items):
            items.insert(position, video_id)
        else:
            items.append(video_id)
        return item_id

    def delete_playlist(self, playlist_id: str) -> bool:
        self._record_call("delete_playlist", is_write=True, playlist_id=playlist_id)
        if playlist_id in self._created_playlists:
            del self._created_playlists[playlist_id]
            return True
        return False
