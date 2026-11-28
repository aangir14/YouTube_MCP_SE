"""System tests for C15 propose_playlist through real MCP stdio harness (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.mcp_harness import McpStdioTestClient


@pytest.mark.asyncio
async def test_mcp_propose_playlist_valid_infeasible_and_invalid_zero_writes(
    tmp_path: Path,
) -> None:
    """Exercise valid, infeasible, unknown-language, and invalid propose_playlist via MCP stdio."""
    # Create an isolated synthetic fixture set with 12 x 10m English + 1 unknown-lang + 1 live
    videos = [
        {
            "video_id": f"c15_vid_{i:02d}",
            "canonical_url": f"https://www.youtube.com/watch?v=c15_vid_{i:02d}",
            "title": f"Recursion Lecture {i}",
            "channel_id": f"UC_c15_chan_{(i - 1) // 3:010d}",
            "channel_title": "C15 Academy",
            "description": "Detailed recursion lesson with examples.",
            "published_at": "2026-05-01T10:00:00Z",
            "duration_seconds": 600,
            "duration_iso": "PT10M",
            "tags": ["recursion", "python", "cs"],
            "category_id": "27",
            "language": "en",
            "has_captions": True,
            "untrusted": True,
        }
        for i in range(1, 13)
    ]
    videos.append(
        {
            "video_id": "c15_unk_001",
            "canonical_url": "https://www.youtube.com/watch?v=c15_unk_001",
            "title": "Recursion Unknown Language",
            "channel_id": "UC_c15_chan_0000000001",
            "channel_title": "C15 Academy",
            "duration_seconds": 600,
            "duration_iso": "PT10M",
            "language": None,
            "untrusted": True,
        }
    )
    videos.append(
        {
            "video_id": "c15_live_01",
            "canonical_url": "https://www.youtube.com/watch?v=c15_live_01",
            "title": "Recursion Live Stream",
            "channel_id": "UC_c15_chan_0000000001",
            "channel_title": "C15 Academy",
            "duration_seconds": 600,
            "duration_iso": "PT10M",
            "language": "en",
            "is_live": True,
            "untrusted": True,
        }
    )
    (tmp_path / "sample_videos.json").write_text(json.dumps(videos), encoding="utf-8")

    async with McpStdioTestClient(provider="fixture", fixture_dir=tmp_path) as client:
        # 1. Valid 2h / 20m English request -> 12 items, 7200s, private, cost 651, 0 writes
        valid_res = await client.call_tool_json(
            "propose_playlist",
            {
                "topic": "recursion",
                "target_duration": "PT2H",
                "max_item_duration": "PT20M",
                "language": "en",
            },
        )
        r = valid_res["result"]
        assert r["status"] == "PROPOSED"
        assert r["item_count"] == 12
        assert r["total_duration_seconds"] == 7200
        assert r["privacy_status"] == "private"
        assert r["estimated_write_cost"] == 651
        assert r["writes_executed"] == 0
        assert r["filtered_out_counts"]["live_or_upcoming"] == 1
        assert r["filtered_out_counts"]["language_mismatch"] == 1
        assert all(item["untrusted"] is True for item in r["items"])

        # 2. Infeasible 5h request -> nearest achievable 7200s, no token, 0 writes
        infeasible_res = await client.call_tool_json(
            "propose_playlist",
            {
                "topic": "recursion",
                "target_duration": "PT5H",
                "max_item_duration": "PT20M",
            },
        )
        inf = infeasible_res["result"]
        assert inf["status"] == "INFEASIBLE"
        assert inf["confirmation_token"] is None
        assert inf["nearest_achievable_seconds"] == 7200
        assert inf["writes_executed"] == 0
        assert inf["unmet_constraints"][0]["constraint"] == "target_duration"

        # 3. Invalid contradictory arguments -> INVALID_ARGUMENTS, 0 quota charged
        bad_res = await client.call_tool_json(
            "propose_playlist",
            {
                "topic": "recursion",
                "target_duration": "PT1H",
                "min_item_duration": "PT25M",
                "max_item_duration": "PT15M",
            },
        )
        assert bad_res["error"]["code"] == "INVALID_ARGUMENTS"
        assert bad_res["meta"]["quota_used"] == infeasible_res["meta"]["quota_used"]
    client.cleanup_stderr()
