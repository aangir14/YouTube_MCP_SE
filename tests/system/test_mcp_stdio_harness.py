"""System tests exercising the scripted stdio MCP test harness offline (C10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.mcp_harness import McpStdioTestClient


@pytest.mark.asyncio
async def test_stdio_handshake_capabilities_and_teardown() -> None:
    """Verify real stdio subprocess startup, handshake, capability listing, and clean teardown."""
    client = McpStdioTestClient(provider="fixture")
    async with client:
        assert client.server_info is not None
        assert client.server_info.serverInfo.name == "focuslist"

        tools = await client.list_tool_names()
        assert "get_video_details" in tools
        assert "propose_playlist" in tools
        assert "confirm_playlist" in tools
        assert len(tools) >= 13

        resources = await client.list_resource_uris()
        assert "focuslist://config/scoring" in resources
        assert "focuslist://quota/status" in resources

        prompts = await client.list_prompt_names()
        assert "video-to-playlist" in prompts
        assert "playlist-audit" in prompts

        # Verify diagnostics were written to stderr while stdout stayed clean JSON-RPC
        stderr_output = client.read_stderr()
        assert "focuslist" in stderr_output.lower()

    assert client.closed is True
    client.cleanup_stderr()


@pytest.mark.asyncio
async def test_stdio_fixture_tool_calls_deterministic() -> None:
    """Verify identical fixture calls over stdio produce identical deterministic envelopes."""
    async with McpStdioTestClient(provider="fixture") as client:
        quota_res = await client.call_tool_json("get_quota_status", {})
        assert quota_res["meta"]["provider"] == "fixture"
        assert quota_res["result"]["general_units_remaining"] == 10000

        vid_res_1 = await client.call_tool_json(
            "get_video_details", {"video_url_or_id": "syn_vid0001"}
        )
        vid_res_2 = await client.call_tool_json(
            "get_video_details", {"video_url_or_id": "syn_vid0001"}
        )
        assert vid_res_1["result"] == vid_res_2["result"]
        assert vid_res_1["result"]["video_id"] == "syn_vid0001"
        assert vid_res_1["result"]["untrusted_metadata"] is True
    client.cleanup_stderr()


@pytest.mark.asyncio
async def test_stdio_custom_fixture_dir_selection(tmp_path: Path) -> None:
    """Verify FOCUSLIST_FIXTURE_DIR selects isolated synthetic fixtures over stdio."""
    custom_videos = [
        {
            "video_id": "c10_test001",
            "canonical_url": "https://www.youtube.com/watch?v=c10_test001",
            "title": "C10 Isolated Fixture Video",
            "channel_id": "UCc10_test_chan_00000001",
            "channel_title": "C10 Test Channel",
            "description": "Synthetic C10 test video.",
            "duration_seconds": 300,
            "duration_iso": "PT5M",
            "tags": ["c10", "fixture"],
            "language": "en",
        }
    ]
    (tmp_path / "sample_videos.json").write_text(json.dumps(custom_videos), encoding="utf-8")

    async with McpStdioTestClient(provider="fixture", fixture_dir=tmp_path) as client:
        res = await client.call_tool_json(
            "get_video_details", {"video_url_or_id": "c10_test001"}
        )
        assert res["result"]["video_id"] == "c10_test001"
        assert res["result"]["title"] == "C10 Isolated Fixture Video"
        assert res["result"]["duration_seconds"] == 300
    client.cleanup_stderr()
