"""System tests verifying FastMCP server tool registration and stdio handshake."""

import pytest

from focuslist.server import create_server


def test_mcp_server_initialization() -> None:
    """Verify FastMCP server initializes with expected name and instructions."""
    server = create_server()
    assert server.name == "focuslist"
    assert "YouTube Video Intelligence" in server.instructions


@pytest.mark.asyncio
async def test_mcp_tools_registration() -> None:
    """Verify all 13 planned MCP tools are registered in FastMCP tool registry."""
    server = create_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "get_video_details",
        "similar_videos",
        "similar_channels",
        "recommend_videos",
        "analyse_engagement",
        "propose_playlist",
        "confirm_playlist",
        "undo_playlist",
        "analyse_playlist",
        "audit_playlist",
        "estimate_quota",
        "get_quota_status",
        "auth_status",
    }
    assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"


@pytest.mark.asyncio
async def test_mcp_resources_registration() -> None:
    """Verify scoring weights and quota status resources are registered."""
    server = create_server()
    resources = await server.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    assert "focuslist://config/scoring" in resource_uris
    assert "focuslist://quota/status" in resource_uris


@pytest.mark.asyncio
async def test_mcp_prompts_registration() -> None:
    """Verify product skill prompts are registered."""
    server = create_server()
    prompts = await server.list_prompts()
    prompt_names = {p.name for p in prompts}
    assert "video-to-playlist" in prompt_names
    assert "playlist-audit" in prompt_names


@pytest.mark.asyncio
async def test_mcp_tool_execution_envelope() -> None:
    """Verify tool call returns valid ResultEnvelope with result and meta blocks."""
    import json

    server = create_server()
    # Call get_quota_status tool directly via call_tool
    res = await server.call_tool("get_quota_status", {})
    content_list = res[0] if isinstance(res, tuple) else res
    assert len(content_list) >= 1
    content_text = content_list[0].text
    data = json.loads(content_text)
    assert "result" in data
    assert "meta" in data
    assert data["meta"]["provider"] == "fixture"
    assert data["result"]["general_units_remaining"] == 10000


@pytest.mark.asyncio
async def test_mcp_get_video_details_call() -> None:
    """Verify get_video_details tool executes cleanly in fixture mode."""
    import json

    server = create_server()
    res = await server.call_tool("get_video_details", {"video_url_or_id": "syn_vid0001"})
    content_list = res[0] if isinstance(res, tuple) else res
    assert len(content_list) >= 1
    data = json.loads(content_list[0].text)
    assert "result" in data
    assert data["result"]["video_id"] == "syn_vid0001"
    assert data["meta"]["quota_used"] == 1
