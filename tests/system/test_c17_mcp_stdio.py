"""System tests exercising C17 tools (FR-2, FR-3, FR-4) over MCP stdio in fixture mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from focuslist.discovery.recommendations import WATCH_HISTORY_DISCLOSURE
from tests.mcp_harness import McpStdioTestClient


def _write_c17_fixtures(root: Path) -> None:
    channels = [
        {
            "channel_id": "UCsyn_chan_0000000000001",
            "canonical_url": "https://www.youtube.com/channel/UCsyn_chan_0000000000001",
            "title": "Synthetic Tech Academy",
            "handle": "@synthetic_tech",
            "description": "Algorithms and recursion tutorials.",
            "keywords": ["algorithms", "recursion"],
            "language": "en",
            "topic_categories": ["https://en.wikipedia.org/wiki/Computer_science"],
            "subscriber_count": 45000,
            "video_count": 120,
            "recent_upload_ids": ["syn_vid0001", "syn_vid0002"],
            "hidden_subscriber_count": False,
            "untrusted": True,
        },
        {
            "channel_id": "UCsyn_chan_0000000000002",
            "canonical_url": "https://www.youtube.com/channel/UCsyn_chan_0000000000002",
            "title": "Algorithms Laboratory",
            "handle": "@algorithms_lab",
            "description": "Algorithms and data structures.",
            "keywords": ["algorithms"],
            "language": "en",
            "topic_categories": ["https://en.wikipedia.org/wiki/Computer_science"],
            "subscriber_count": 0,
            "video_count": 80,
            "recent_upload_ids": ["syn_vid0003", "syn_vid0004"],
            "hidden_subscriber_count": True,
            "untrusted": True,
        },
    ]
    videos = [
        {
            "video_id": "syn_vid0001",
            "canonical_url": "https://www.youtube.com/watch?v=syn_vid0001",
            "title": "Recursion and Dynamic Programming",
            "channel_id": "UCsyn_chan_0000000000001",
            "channel_title": "Synthetic Tech Academy",
            "description": "Recursive functions and memoization.",
            "published_at": "2026-10-10T10:00:00Z",
            "duration_seconds": 900,
            "duration_iso": "PT15M",
            "tags": ["recursion", "algorithms"],
            "category_id": "28",
            "language": "en",
            "visibility": "public",
            "is_live": False,
            "is_upcoming": False,
            "is_age_restricted": False,
            "untrusted": True,
        },
        {
            "video_id": "syn_vid0003",
            "canonical_url": "https://www.youtube.com/watch?v=syn_vid0003",
            "title": "Graph Algorithms Explained",
            "channel_id": "UCsyn_chan_0000000000002",
            "channel_title": "Algorithms Laboratory",
            "description": "Shortest paths and BFS/DFS.",
            "published_at": "2026-10-20T10:00:00Z",
            "duration_seconds": 600,
            "duration_iso": "PT10M",
            "tags": ["graphs", "algorithms"],
            "category_id": "28",
            "language": "en",
            "visibility": "public",
            "is_live": False,
            "is_upcoming": False,
            "is_age_restricted": False,
            "untrusted": True,
        },
    ]
    likes = [
        {
            "item_id": "syn_vid0001",
            "activity_type": "like",
            "account_id": "fixture_learner",
            "channel_id": "UCsyn_chan_0000000000001",
            "timestamp": "2026-11-10T10:00:00Z",
            "timestamp_provenance": "genuine",
        }
    ]
    (root / "sample_channels.json").write_text(json.dumps(channels), encoding="utf-8")
    (root / "sample_videos.json").write_text(json.dumps(videos), encoding="utf-8")
    (root / "sample_likes.json").write_text(json.dumps(likes), encoding="utf-8")


@pytest.mark.asyncio
async def test_c17_tools_over_mcp_stdio(tmp_path: Path) -> None:
    _write_c17_fixtures(tmp_path)
    async with McpStdioTestClient(provider="fixture", fixture_dir=tmp_path) as client:
        # ST-FR2: equivalent forms + hidden subscriber count
        ch_id_res = await client.call_tool_json(
            "similar_channels", {"channel_url_handle_or_id": "UCsyn_chan_0000000000001"}
        )
        ch_handle_res = await client.call_tool_json(
            "similar_channels", {"channel_url_handle_or_id": "@synthetic_tech"}
        )
        assert ch_id_res["result"]["channels"] == ch_handle_res["result"]["channels"]
        assert ch_id_res["result"]["channels"][0]["hidden_subscriber_count"] is True
        assert ch_id_res["result"]["channels"][0]["subscriber_count"] is None

        # ST-FR3: recommend_videos with subset and full sources
        rec_res = await client.call_tool_json(
            "recommend_videos", {"sources": ["likes", "subscriptions"], "topic": "algorithms"}
        )
        assert rec_res["result"]["watch_history_disclosure"] == WATCH_HISTORY_DISCLOSURE
        assert [r["video_id"] for r in rec_res["result"]["recommendations"]] == ["syn_vid0003"]

        # ST-FR4: analyse_engagement with explicit comparison and 0 searches
        eng_res = await client.call_tool_json(
            "analyse_engagement",
            {
                "sources": ["likes"],
                "period": {"start": "2026-11-01", "end": "2026-11-20"},
                "comparison_period": {"start": "2026-10-01", "end": "2026-10-20"},
                "group_by": "week",
            },
        )
        assert eng_res["result"]["observation_count"] == 1
        assert eng_res["result"]["comparison"]["deltas"]["observation_count"]["absolute_delta"] == 1
        assert eng_res["meta"]["search_calls"] == 0
        assert eng_res["meta"]["quota_used"] <= 60
    client.cleanup_stderr()
