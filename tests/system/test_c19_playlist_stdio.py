"""Verify FR-6, FR-12 and all three SK-6 evaluations through real MCP stdio."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import AnyUrl

from focuslist.ranking_weights import DEFAULT_SCORING_WEIGHTS, VIDEO_WEIGHTS
from focuslist.skills.playlist_audit import run_playlist_audit
from tests.mcp_harness import McpStdioTestClient

_LARGE = "PL_c19_long_fixture"
_CLEAN = "PL_c19_clean_fixture"
_ISSUES = "PL_c19_with_issues"


def _id(number: int) -> str:
    return f"vid{number:08d}"


@pytest.fixture
def audit_fixture(tmp_path: Path):
    trace = tmp_path / "provider.jsonl"
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    rows = [
        {
            "video_id": _id(i), "canonical_url": f"https://www.youtube.com/watch?v={_id(i)}",
            "channel_id": f"UC{i % 5:022d}", "channel_title": f"Synthetic Channel {i % 5}",
            "title": f"Recursion lesson {i}", "description": "A synthetic recursion lesson.",
            "category_id": str(i % 2 + 27), "language": "en" if i % 2 == 0 else "en-US",
            "duration_seconds": 300, "published_at": "2024-08-15T00:00:00Z",
            "visibility": "public", "is_live": False, "is_upcoming": False,
            "is_age_restricted": False,
        }
        for i in range(498)
    ]
    prefix = "Recursion frames stack proof recursion tracing language loops arrays depth examples"
    rows[0]["title"] = prefix + " version"
    rows[1].update(title=prefix + " edition", duration_seconds=1200, published_at="2021-11-24T00:00:00Z")
    rows[2]["is_live"] = True
    rows[3].update(is_upcoming=True, duration_seconds=None, published_at=None)
    rows[-1]["duration_seconds"] = 3600  # Uninspected sentinel at position 501.
    entries = [
        {"video_id": _id(0)}, {"video_id": _id(0)}, {"video_id": _id(1)},
        {"availability_hint": "deleted"}, {"video_id": _id(999), "availability_hint": "private"},
        {"video_id": _id(2)}, {"video_id": _id(3)}, {"video_id": _id(4)},
    ]
    data = {
        _LARGE: [*entries, *({"video_id": _id(i)} for i in range(5, 498))],
        _ISSUES: entries, _CLEAN: [{"video_id": _id(i)} for i in (5, 6, 7)],
        "PL_c19_empty_fixture": [],
    }
    (fixture_dir / "sample_videos.json").write_text(json.dumps(rows), encoding="utf-8")
    (fixture_dir / "sample_playlist_audit.json").write_text(json.dumps(data), encoding="utf-8")

    def events():
        if not trace.exists():
            return []
        return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]

    def connect(*, units=10000, weights=None):
        return McpStdioTestClient(
            fixture_dir=fixture_dir, server_args=["-m", "tests.c19_stdio_probe"],
            extra_env={
                "C19_TEST_TRACE": str(trace), "FOCUSLIST_DAILY_GENERAL_QUOTA": str(units),
                "FOCUSLIST_DB_PATH": str(tmp_path / "ledger.db"),
                "FOCUSLIST_AUTH_STORE_DIR": str(tmp_path / "auth"),
                "FOCUSLIST_SCORING_WEIGHTS": json.dumps(weights or {}),
            },
        )

    return connect, events


async def test_st_fr12_counts_runtime_bounds_and_placeholders(audit_fixture):
    connect, events = audit_fixture
    async with connect() as client:
        args = {"playlist_url_or_id": f"https://www.youtube.com/playlist?list={_LARGE}"}
        invalid = await client.call_tool_json("analyse_playlist", {
            "playlist_url_or_id": "https://example.invalid/playlist?list=PL_c19_long_fixture",
        })
        bad_threshold = await client.call_tool_json("audit_playlist", {
            **args, "stale_after_years": 0,
        })
        assert invalid["error"]["code"] == bad_threshold["error"]["code"] == "INVALID_ARGUMENTS"
        assert events() == []
        for tool in ("analyse_playlist", "audit_playlist"):
            start = len(events())
            response = await client.call_tool_json(tool, args)
            result = response["result"]
            calls = events()[start:]
            assert result["total_items"] == 500 and result["reported_item_count"] == 501
            assert result["truncated"] and result["unavailable_items"] == 2
            assert result["total_duration_seconds"] == 150000
            assert result["duration"]["known_items"] == 497
            assert result["duration"]["unknown_items"] == 1
            assert sum(row["count"] for row in result["duration"]["histogram"]) == 497
            assert len(result["top_channels"]) == 5
            assert result["languages"] == [{"language": "en", "count": 498}]
            assert result["publication_year_range"] == {"min": 2021, "max": 2024}
            assert result["categories"] == [
                {"category_id": "27", "count": 250}, {"category_id": "28", "count": 248},
            ]
            assert response["meta"]["quota_used"] == 21
            assert response["meta"]["search_calls"] == 0
            assert [call["method"] for call in calls] == [
                "get_playlist_info", *(["get_playlist_page"] * 10), *(["get_video_details"] * 10),
            ]
            assert all(call["args"]["page_size"] == 50 for call in calls[1:11])
            assert all(_id(497) not in call["args"]["video_ids"] for call in calls[11:])
            assert all(not call["is_write"] for call in calls)
        assert result["issue_counts"] == {
            "duplicate_id": 1, "duplicate_title": 1, "live": 1, "stale": 1,
            "unavailable": 2, "upcoming": 1,
        }
        explicit = (await client.call_tool_json("audit_playlist", {
            "playlist_url_or_id": _LARGE, "max_item_length_minutes": 10,
            "stale_after_years": 6, "item_limit": 8,
        }))["result"]
        assert explicit["truncated"] and explicit["total_items_scanned"] == 8
        assert explicit["issue_counts"] == {
            "duplicate_id": 1, "duplicate_title": 1, "live": 1, "over_length": 1,
            "unavailable": 2, "upcoming": 1,
        }
        missing = [row for row in explicit["issues"] if row["code"] == "unavailable"]
        assert [(row["position"], row["reason"]) for row in missing] == [(4, "deleted"), (5, "private")]
        assert all("title" not in row for row in missing)
        assert next(row for row in explicit["issues"] if row["code"] == "duplicate_id")["duplicate_of"] == 1
        similar = next(row for row in explicit["issues"] if row["code"] == "duplicate_title")
        assert similar["duplicate_of"] == 1 and 0.9 <= similar["title_cosine"] < 1

        before = len(events())
        empty = await client.call_tool_json("analyse_playlist", {
            "playlist_url_or_id": "PL_c19_empty_fixture",
        })
        assert empty["result"]["total_items"] == 0 and empty["meta"]["quota_used"] == 1
        assert [call["method"] for call in events()[before:]] == ["get_playlist_info"]
    client.cleanup_stderr()


@pytest.mark.parametrize("case", ["clean", "findings", "quota_denied"])
async def test_ske_sk6_estimate_audit_render_and_stop(audit_fixture, case):
    connect, events = audit_fixture
    async with connect(units=20 if case == "quota_denied" else 10000) as client:
        skill = await client.session.read_resource(AnyUrl("focuslist://skills/playlist-audit"))
        assert "estimate_quota" in skill.contents[0].text and events() == []
        prompt = await client.session.get_prompt("playlist-audit", {"playlist_id": _ISSUES})
        assert "Suggested fix" in prompt.messages[0].content.text
        called = []

        async def invoke(tool, args):
            called.append(tool)
            if tool == "audit_playlist":
                assert events() == []
            return await client.call_tool_json(tool, args)

        reply = await run_playlist_audit(
            invoke, _CLEAN if case == "clean" else _ISSUES, max_item_length_minutes=10,
        )
        if case == "quota_denied":
            assert reply["error"]["code"] == "QUOTA_BUDGET_EXCEEDED"
            assert reply["estimate"]["estimated_general_units"] == 21
            assert called == ["estimate_quota"] and events() == []
            direct = await client.call_tool_json("audit_playlist", {"playlist_url_or_id": _ISSUES})
            assert direct["error"]["code"] == "QUOTA_BUDGET_EXCEEDED" and events() == []
        else:
            assert reply["status"] == "AUDITED"
            assert called == ["estimate_quota", "audit_playlist"]
            assert [call["method"] for call in events()] == [
                "get_playlist_info", "get_playlist_page", "get_video_details",
            ]
            table = reply["findings_table"]
            if case == "clean":
                assert "No issues found" in table and reply["audit"]["flagged_count"] == 0
            else:
                assert "duplicate title" in table and "Compare the similar videos" in table
                assert "unavailable" in table and "over length" in table
        assert all(not row["is_write"] for row in events())
    client.cleanup_stderr()


async def test_st_fr6_active_resource_and_proposal_explanations(audit_fixture):
    connect, events = audit_fixture
    weights = {name: float(name == "text_cosine") for name in VIDEO_WEIGHTS}
    async with connect(weights={"similar_videos": weights}) as client:
        proposals = await client.call_tool_json("propose_playlist", {
            "topic": "Recursion", "target_duration": "PT10M", "max_item_duration": "PT15M",
        })
        ordered = proposals["result"]["items"]
        assert len(ordered) == 2 and all(row["untrusted"] for row in ordered)
        for item in ordered:
            assert item["components"] == DEFAULT_SCORING_WEIGHTS["propose_playlist"]
            assert math.isclose(sum(row["contribution"] for row in item["feature_trace"].values()),
                                item["score"], rel_tol=0.0, abs_tol=1e-6)
            assert len(item["reason"]) <= 200 and len(item["shared_terms"]) <= 5
        before = events()
        resource = await client.session.read_resource(AnyUrl("focuslist://config/scoring"))
        active = json.loads(resource.contents[0].text)
        assert active == {**DEFAULT_SCORING_WEIGHTS, "similar_videos": weights}
        assert events() == before
        ranked = await client.call_tool_json("similar_videos", {"video_url_or_id": _id(5)})
        assert ranked["result"]["videos"]
        assert all(row["components"] == weights for row in ranked["result"]["videos"])
        assert all(not row["is_write"] for row in events())
    client.cleanup_stderr()
