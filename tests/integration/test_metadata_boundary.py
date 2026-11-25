"""C11 validation runs before the instrumented fixture provider or quota charge."""

import json
from typing import Any

import pytest

from focuslist import server as server_module
from focuslist.config import Settings
from focuslist.platform.fixture_provider import FixtureVideoProvider


@pytest.fixture
def server_with_spy(
    monkeypatch: pytest.MonkeyPatch, fixture_provider: FixtureVideoProvider, test_settings: Settings
) -> Any:
    monkeypatch.setattr(server_module, "create_provider", lambda settings: fixture_provider)
    return server_module.create_server(settings=test_settings)


async def _call(server: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    response = await server.call_tool(tool, args)
    content = response[0] if isinstance(response, tuple) else response
    return json.loads(content[0].text)


@pytest.mark.parametrize(
    ("tool", "arguments", "code"),
    [
        (
            "get_video_details",
            {"video_url_or_id": "https://example.test/watch?v=syn_vid0001"},
            "INVALID_VIDEO_ID",
        ),
        ("similar_videos", {"video_url_or_id": "too-short"}, "INVALID_VIDEO_ID"),
        (
            "similar_channels",
            {"channel_url_handle_or_id": "https://youtube.com/c/Synthetic"},
            "INVALID_CHANNEL_ID",
        ),
        (
            "analyse_playlist",
            {"playlist_url_or_id": "https://youtube.com/playlist?list="},
            "INVALID_ARGUMENTS",
        ),
        (
            "audit_playlist",
            {"playlist_url_or_id": "https://example.test/playlist?list=PLfixture_01"},
            "INVALID_ARGUMENTS",
        ),
        (
            "propose_playlist",
            {"topic": "graphs", "target_duration": "P1M", "max_item_duration": "PT20M"},
            "INVALID_ARGUMENTS",
        ),
        (
            "propose_playlist",
            {"topic": "graphs", "target_duration": "PT2H", "max_item_duration": "PT0S"},
            "INVALID_ARGUMENTS",
        ),
        (
            "propose_playlist",
            {
                "topic": "graphs",
                "target_duration": "PT2H",
                "max_item_duration": "PT20M",
                "language": "und",
            },
            "INVALID_ARGUMENTS",
        ),
    ],
)
async def test_malformed_input_costs_zero(
    server_with_spy: Any,
    fixture_provider: FixtureVideoProvider,
    tool: str,
    arguments: dict[str, Any],
    code: str,
) -> None:
    result = await _call(server_with_spy, tool, arguments)
    assert result["error"]["code"] == code
    assert result["meta"]["quota_used"] == 0
    assert (
        fixture_provider.requests
        == fixture_provider.network_attempts
        == fixture_provider.writes
        == 0
    )
    assert fixture_provider.call_log == []


async def test_equivalent_video_forms_query_same_fixture(
    server_with_spy: Any, fixture_provider: FixtureVideoProvider
) -> None:
    raw = await _call(server_with_spy, "get_video_details", {"video_url_or_id": "syn_vid0001"})
    short = await _call(
        server_with_spy,
        "get_video_details",
        {"video_url_or_id": "https://youtu.be/syn_vid0001?t=10"},
    )
    assert raw["result"] == short["result"]
    assert raw["result"]["canonical_url"] == "https://www.youtube.com/watch?v=syn_vid0001"
    assert [row["args"]["video_ids"] for row in fixture_provider.call_log] == [
        ["syn_vid0001"],
        ["syn_vid0001"],
    ]
    assert fixture_provider.writes == 0


async def test_unknown_video_does_not_return_unrelated_fixture(
    server_with_spy: Any, fixture_provider: FixtureVideoProvider
) -> None:
    result = await _call(server_with_spy, "get_video_details", {"video_url_or_id": "syn_missing"})
    assert result["error"]["code"] == "VIDEO_UNAVAILABLE"
    assert fixture_provider.call_counts == {"get_video_details": 1}


async def test_channel_reference_uses_correct_provider_key(
    server_with_spy: Any, fixture_provider: FixtureVideoProvider
) -> None:
    channel_id = "UCsyn_chan_" + "1".zfill(13)
    direct = await _call(
        server_with_spy, "similar_channels", {"channel_url_handle_or_id": channel_id}
    )
    handle = await _call(
        server_with_spy,
        "similar_channels",
        {"channel_url_handle_or_id": "https://www.youtube.com/@synthetic_tech"},
    )
    assert direct["result"] == handle["result"]
    assert [row["args"] for row in fixture_provider.call_log] == [
        {"channel_id": channel_id, "handle": None},
        {"channel_id": None, "handle": "@synthetic_tech"},
    ]


async def test_unavailable_channel_does_not_return_unrelated_fixture(
    server_with_spy: Any, fixture_provider: FixtureVideoProvider
) -> None:
    result = await _call(
        server_with_spy, "similar_channels", {"channel_url_handle_or_id": "@missing_fixture"}
    )
    assert result["error"]["code"] == "CHANNEL_UNAVAILABLE"
    assert fixture_provider.call_counts == {"get_channel_details": 1}
