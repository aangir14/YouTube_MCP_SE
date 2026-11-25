"""ST-FR1: drive video facts and ranking over actual MCP stdio with offline fixtures."""

import json
from pathlib import Path

from tests.mcp_harness import McpStdioTestClient


def _id(number: int) -> str:
    return f"v{number:010}"


def _video(number: int, **overrides) -> dict:
    return {
        "video_id": _id(number),
        "canonical_url": f"https://www.youtube.com/watch?v={_id(number)}",
        "channel_id": "UC" + "a" * 22,
        "channel_title": "Synthetic Channel",
        "title": "Graph algebra",
        "tags": ["paths"],
        "category_id": "27",
        "language": "en",
        "duration_iso": "PT1M",
        "published_at": "2025-01-01T00:00:00Z",
        "visibility": "public",
        "is_live": False,
        "is_upcoming": False,
        "is_age_restricted": False,
        **overrides,
    }


def _client(tmp_path: Path, videos: list[dict], pages: dict, **env: str) -> McpStdioTestClient:
    (tmp_path / "sample_videos.json").write_text(json.dumps(videos), encoding="utf-8")
    (tmp_path / "c14_pages.json").write_text(json.dumps(pages), encoding="utf-8")
    return McpStdioTestClient(
        extra_env=env,
        server_args=[
            str(Path(__file__).resolve().parents[1] / "c14_stdio_probe.py"),
            str(tmp_path),
            str(tmp_path / "counters.json"),
        ],
    )


def _counters(root: Path) -> dict:
    return json.loads((root / "counters.json").read_text(encoding="utf-8"))


async def test_c14_stdio_facts_happy_and_failure_paths(tmp_path: Path) -> None:
    videos = [
        _video(0, description="H\u200bid\u0000den " + "x" * 540, view_count=0),
        _video(1),
        _video(2, published_at="2026-01-01T00:00:00Z"),
        _video(3, published_at="2026-01-01T00:00:00Z"),
        _video(4, tags=None, language=None, published_at=None),
        _video(5, visibility="private"),
        _video(6, is_live=True),
        _video(7, is_upcoming=True),
        _video(8, is_age_restricted=True),
        _video(9, duration_iso="PT59S"),
        _video(10, visibility=None),
        _video(11, is_live=None),
    ]
    pages = {
        "graph algebra": [_id(x) for x in (0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 99)],
        "paths": [_id(2), _id(3)],
        "uploads": [_id(0), _id(1), _id(3)],
    }
    client = _client(tmp_path, videos, pages)
    try:
        async with client:
            assert {"get_video_details", "similar_videos"} <= set(await client.list_tool_names())
            for tool, arguments, error in (
                ("get_video_details", {"video_url_or_id": "bad"}, "INVALID_VIDEO_ID"),
                ("similar_videos", {"video_url_or_id": "bad"}, "INVALID_VIDEO_ID"),
                ("similar_videos", {"video_url_or_id": _id(0), "limit": 51}, "INVALID_ARGUMENTS"),
            ):
                response = await client.call_tool_json(tool, arguments)
                assert response["error"]["code"] == error
                assert response["meta"]["quota_used"] == response["meta"]["search_calls"] == 0
            invalid_counts = _counters(tmp_path)
            assert invalid_counts["provider_requests"] == invalid_counts["simulated_attempts"] == 0

            for missing_or_private in (_id(99), _id(5)):
                missing = await client.call_tool_json(
                    "similar_videos", {"video_url_or_id": missing_or_private}
                )
                assert missing["error"]["code"] == "VIDEO_UNAVAILABLE"
                assert missing["meta"]["quota_used"] == 1 and missing["meta"]["search_calls"] == 0
            unavailable_counts = _counters(tmp_path)
            assert unavailable_counts["calls"] == {"get_video_details": 2}

            facts = await client.call_tool_json(
                "get_video_details", {"video_url_or_id": f"https://youtu.be/{_id(0)}"}
            )
            fact_counts = _counters(tmp_path)
            assert fact_counts["calls"] == {"get_video_details": 3}
            assert facts["result"]["untrusted_metadata"] is True
            assert facts["result"]["duration_iso"] == "PT1M"
            assert facts["result"]["view_count"] == 0
            assert len(facts["result"]["description"]) == 500
            assert facts["result"]["description"].startswith("Hidden ")

            ranked = await client.call_tool_json("similar_videos", {"video_url_or_id": _id(0)})
            result = ranked["result"]
            assert result["candidate_count"] == 12 and result["eligible_count"] == 4
            assert [item["video_id"] for item in result["videos"]] == [_id(x) for x in (2, 3, 1, 4)]
            assert result["warnings"]
            assert {"tags", "language", "published_at"} <= set(
                result["videos"][-1]["missing_fields"]
            )
            assert result["videos"][-1]["low_confidence"]
            assert ranked["meta"]["quota_used"] == 3 and ranked["meta"]["search_calls"] == 2
            for item in result["videos"]:
                assert len(item["shared_terms"]) <= 5 and len(item["reason"]) <= 200
                assert (
                    abs(
                        sum(x["contribution"] for x in item["feature_trace"].values())
                        - item["score"]
                    )
                    <= 0.000001
                )
            happy_counts = _counters(tmp_path)
            assert happy_counts == {
                "provider_requests": 8,
                "simulated_attempts": 8,
                "writes": 0,
                "calls": {
                    "get_video_details": 5,
                    "search_video_ids": 2,
                    "get_channel_upload_ids": 1,
                },
                "detail_batch_sizes": [1, 1, 1, 1, 12],
            }
            again = await client.call_tool_json(
                "similar_videos", {"video_url_or_id": f"https://youtube.com/shorts/{_id(0)}"}
            )
            assert again["result"] == result
            print(
                "C14_COUNTS",
                json.dumps(
                    {
                        "invalid": invalid_counts,
                        "unavailable": unavailable_counts,
                        "facts": fact_counts,
                        "happy": happy_counts,
                    },
                    sort_keys=True,
                ),
            )
        assert client.closed
    finally:
        client.cleanup_stderr()


async def test_c14_stdio_full_pages_limits_and_id_order(tmp_path: Path) -> None:
    videos = [_video(number) for number in range(151)]
    pages = {
        "graph algebra": [_id(x) for x in range(1, 52)],  # fixture over-returns by one
        "paths": [_id(x) for x in range(51, 101)],
        "uploads": [_id(x) for x in range(101, 151)],
    }
    client = _client(tmp_path, videos, pages)
    try:
        async with client:
            default = await client.call_tool_json("similar_videos", {"video_url_or_id": _id(0)})
            counts = _counters(tmp_path)
            assert (
                default["result"]["candidate_count"] == default["result"]["eligible_count"] == 150
            )
            assert default["meta"]["quota_used"] == 5 and default["meta"]["search_calls"] == 2
            assert [item["video_id"] for item in default["result"]["videos"]] == [
                _id(x) for x in range(1, 11)
            ]
            assert counts == {
                "provider_requests": 7,
                "simulated_attempts": 7,
                "writes": 0,
                "calls": {
                    "get_video_details": 4,
                    "search_video_ids": 2,
                    "get_channel_upload_ids": 1,
                },
                "detail_batch_sizes": [1, 50, 50, 50],
            }
            largest = await client.call_tool_json(
                "similar_videos", {"video_url_or_id": _id(0), "limit": 50}
            )
            assert [item["video_id"] for item in largest["result"]["videos"]] == [
                _id(x) for x in range(1, 51)
            ]
            print("C14_FULL_PAGE_COUNTS", json.dumps(counts, sort_keys=True))
    finally:
        client.cleanup_stderr()


async def test_c14_stdio_over_budget_has_no_provider_calls(tmp_path: Path) -> None:
    client = _client(tmp_path, [_video(0)], {}, FOCUSLIST_REQUEST_UNIT_CAP="5")
    try:
        async with client:
            response = await client.call_tool_json("similar_videos", {"video_url_or_id": _id(0)})
            assert response["error"]["code"] == "QUOTA_BUDGET_EXCEEDED"
            assert response["meta"]["quota_used"] == response["meta"]["search_calls"] == 0
            counts = _counters(tmp_path)
            assert counts == {
                "provider_requests": 0,
                "simulated_attempts": 0,
                "writes": 0,
                "calls": {},
                "detail_batch_sizes": [],
            }
            print("C14_BUDGET_COUNTS", json.dumps(counts, sort_keys=True))
    finally:
        client.cleanup_stderr()
