"""Developer-only sanitized fixture recorder (C13, SRS UI-2, FR-11.7)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from focuslist.errors import InvalidArgumentsError
from focuslist.platform.provider import VideoProvider
from focuslist.types import ChannelRecord, VideoRecord, sanitize_untrusted_text

# Patterns indicating raw authorization material that must never be written to fixtures
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r'"(?:access_token|refresh_token|client_secret)"\s*:', re.IGNORECASE),
    re.compile(r"ya29\.[A-Za-z0-9._\-]+"),
)


def _assert_no_raw_auth_data(payload_text: str) -> None:
    """Reject any raw authorization tokens or secrets before writing fixtures."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(payload_text):
            raise InvalidArgumentsError(
                "Refusing to write fixture containing raw authorization or credential data."
            )


def scrub_video_to_fixture(video: VideoRecord) -> dict[str, Any]:
    """Allowlist and sanitize public VideoRecord fields for offline fixture storage."""
    data = {
        "video_id": video.video_id,
        "canonical_url": f"https://www.youtube.com/watch?v={video.video_id}",
        "title": sanitize_untrusted_text(video.title, max_length=100),
        "channel_id": video.channel_id,
        "channel_title": sanitize_untrusted_text(video.channel_title, max_length=100),
        "description": sanitize_untrusted_text(video.description, max_length=500),
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "duration_seconds": video.duration_seconds,
        "duration_iso": video.duration_iso,
        "tags": [sanitize_untrusted_text(t, max_length=50) for t in (video.tags or [])],
        "category_id": video.category_id,
        "language": video.language,
        "language_provenance": video.language_provenance,
        "is_live": video.is_live,
        "is_upcoming": video.is_upcoming,
        "is_age_restricted": video.is_age_restricted,
        "has_captions": video.has_captions,
        "view_count": video.view_count,
        "like_count": video.like_count,
        "untrusted": True,
    }
    _assert_no_raw_auth_data(json.dumps(data))
    return data


def scrub_channel_to_fixture(channel: ChannelRecord) -> dict[str, Any]:
    """Allowlist and sanitize public ChannelRecord fields for offline fixture storage."""
    data = {
        "channel_id": channel.channel_id,
        "canonical_url": f"https://www.youtube.com/channel/{channel.channel_id}",
        "title": sanitize_untrusted_text(channel.title, max_length=100),
        "handle": channel.handle,
        "description": sanitize_untrusted_text(channel.description, max_length=500),
        "language": channel.language,
        "language_provenance": channel.language_provenance,
        "topic_categories": list(channel.topic_categories),
        "subscriber_count": None if channel.hidden_subscriber_count else channel.subscriber_count,
        "video_count": channel.video_count,
        "hidden_subscriber_count": channel.hidden_subscriber_count,
        "untrusted": True,
    }
    _assert_no_raw_auth_data(json.dumps(data))
    return data


def record_public_fixtures(
    provider: VideoProvider,
    output_dir: Path | str,
    *,
    query: str = "recursion",
    max_videos: int = 15,
    region_code: str = "US",
) -> dict[str, int]:
    """Fetch public read-only data from provider and write scrubbed JSON fixtures."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    videos = provider.search_candidates(query, max_results=max_videos)
    scrubbed_videos = [scrub_video_to_fixture(v) for v in videos]

    channel_ids = list(dict.fromkeys(v.channel_id for v in videos if v.channel_id))
    scrubbed_channels: list[dict[str, Any]] = []
    for cid in channel_ids:
        ch = provider.get_channel_details(channel_id=cid)
        if ch is not None:
            scrubbed_channels.append(scrub_channel_to_fixture(ch))

    categories = provider.get_categories(region_code=region_code)
    scrubbed_categories = [
        {"id": str(c.get("id", "")), "title": sanitize_untrusted_text(str(c.get("title", "")))}
        for c in categories
    ]

    (out_path / "sample_videos.json").write_text(
        json.dumps(scrubbed_videos, indent=2), encoding="utf-8"
    )
    (out_path / "sample_channels.json").write_text(
        json.dumps(scrubbed_channels, indent=2), encoding="utf-8"
    )
    (out_path / "sample_categories.json").write_text(
        json.dumps(scrubbed_categories, indent=2), encoding="utf-8"
    )

    return {
        "videos": len(scrubbed_videos),
        "channels": len(scrubbed_channels),
        "categories": len(scrubbed_categories),
    }
