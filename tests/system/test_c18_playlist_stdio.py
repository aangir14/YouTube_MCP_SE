"""ST-FR5, ST-FR7 and SEC-APPROVAL through actual MCP stdio."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
from mcp import types
from pydantic import AnyUrl
from typer.testing import CliRunner

from focuslist import cli
from focuslist.clock import FakeClock
from tests.mcp_harness import McpStdioTestClient

ARGS = {"topic": "recursion", "target_duration": "PT30M", "max_item_duration": "PT20M"}


@pytest.fixture
def scripted(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    videos = [
        {"video_id": f"rec_{n:07d}", "canonical_url": f"https://www.youtube.com/watch?v=rec_{n:07d}",
         "title": f"Recursion Lecture {n}", "channel_id": f"UC_group_{n // 3}",
         "channel_title": f"Academy {n // 3}", "duration_seconds": 600,
         "visibility": "public", "language": "en"}
        for n in range(12)
    ]
    (fixture_dir / "sample_videos.json").write_text(json.dumps(videos), encoding="utf-8")

    def events():
        return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()] \
            if trace.exists() else []

    def connect(callback=None, *, failure="", time_offset=0, units=10000, no_channel=False):
        return McpStdioTestClient(
            server_args=["-m", "tests.c18_stdio_probe"],
            fixture_dir=fixture_dir,
            extra_env={
                "C18_TEST_TRACE": str(trace), "C18_FAILURE": failure,
                "C18_CLOCK_OFFSET": str(time_offset), "FOCUSLIST_DAILY_GENERAL_QUOTA": str(units),
                "C18_NO_CHANNEL": str(int(no_channel)),
                "FOCUSLIST_DB_PATH": str(tmp_path / "actions.db"),
                "FOCUSLIST_AUTH_STORE_DIR": str(tmp_path / "auth"),
            },
            elicitation_callback=callback,
        )

    return connect, events


def _confirmation(proposal):
    return {"proposal_id": proposal["proposal_id"], "token": proposal["confirmation_token"]}


async def test_decline_and_expire_then_create_exact_action_and_replay(scripted):
    connect, events = scripted
    visible = []
    approve = False

    async def decision(_context, params):
        visible.append(json.loads(params.message.split("\n", 1)[1]))
        return types.ElicitResult(action="accept", content={"approved": approve})

    async with connect(decision) as client:
        proposal = (await client.call_tool_json("propose_playlist", ARGS))["result"]
        assert proposal["writes_executed"] == 0
        before = events()
        declined = await client.call_tool_json("confirm_playlist", _confirmation(proposal))
        assert declined["error"]["code"] == "CONFIRMATION_INVALID"
        assert events() == before
        stale = (await client.call_tool_json("propose_playlist", ARGS))["result"]
    client.cleanup_stderr()

    approve = True
    async with connect(decision, time_offset=1800) as client:
        before = events()
        expired = await client.call_tool_json("confirm_playlist", _confirmation(stale))
        assert expired["error"]["code"] == "CONFIRMATION_EXPIRED"
        assert events() == before
        opts = {**ARGS, "target_duration": "PT2H", "title": "Reviewed Recursion",
                "privacy_status": "unlisted"}
        reviewed = (await client.call_tool_json("propose_playlist", opts))["result"]
        before = events()
        edited = _confirmation(reviewed)
        edited["token"] = "0" * 64
        assert (await client.call_tool_json("confirm_playlist", edited))["error"]["code"] == "CONFIRMATION_INVALID"
        assert events() == before
        out = await client.call_tool_json("confirm_playlist", _confirmation(reviewed))
        assert out["result"]["status"] == "CREATED"
        assert reviewed["item_count"] == 12 and reviewed["estimated_write_cost"] == 651
        assert visible[-1] == {k: v for k, v in reviewed.items() if k != "confirmation_token"}
        assert out["meta"]["quota_used"] == reviewed["estimated_write_cost"]
        writes = [call for call in events() if call.get("is_write")]
        assert [call["method"] for call in writes] == [
            "create_playlist", *(["insert_playlist_item"] * reviewed["item_count"]),
        ]
        assert writes[0]["title"] == reviewed["title"] and writes[0]["privacy"] == "unlisted"
        assert [item["video_id"] for item in writes[1:]] == reviewed["ordered_video_ids"]
        assert [item["position"] for item in writes[1:]] == list(range(reviewed["item_count"]))
        assert all(second["time"] - first["time"] >= 1 for first, second in pairwise(writes))
    client.cleanup_stderr()

    async with connect(time_offset=1820) as client:
        before = events()
        replay = await client.call_tool_json("confirm_playlist", _confirmation(reviewed))
        assert replay["result"] == out["result"]
        assert replay["meta"]["quota_used"] == 0 and events() == before
    client.cleanup_stderr()


async def test_partial_restart_resume_and_scoped_undo_are_separate_approvals(scripted):
    connect, events = scripted
    review_messages = []

    async def consent(_context, params):
        review_messages.append(json.loads(params.message.split("\n", 1)[1]))
        return types.ElicitResult(action="accept", content={"approved": True})

    async with connect(consent, failure="1") as client:
        original = (await client.call_tool_json("propose_playlist", ARGS))["result"]
        result = await client.call_tool_json("confirm_playlist", _confirmation(original))
        assert result["error"]["code"] == "PARTIALLY_CREATED"
        partial = result["error"]["details"]
        assert partial["inserted_count"] == 1 and partial["failed_step"] == "insert_2"
    client.cleanup_stderr()

    async with connect(time_offset=10) as client:
        resumed = await client.call_tool_json("resume_playlist", {"proposal_id": original["proposal_id"]})
        resume = resumed["result"]
        assert resume["ordered_video_ids"] == original["ordered_video_ids"][1:]
        before = events()
        assert (await client.call_tool_json(
            "confirm_playlist", _confirmation(resume),
        ))["error"]["code"] == "CONFIRMATION_INVALID"
        assert events() == before
    client.cleanup_stderr()

    async with connect(consent, time_offset=10) as client:
        done = await client.call_tool_json("confirm_playlist", _confirmation(resume))
        assert done["result"]["status"] == "RESUMED"
        assert review_messages[-1]["ordered_video_ids"] == resume["ordered_video_ids"]
        target = done["result"]["playlist_id"]
        before = events()
        undo = (await client.call_tool_json("undo_playlist", {"playlist_id": target}))["result"]
        assert events() == before and undo["ordered_video_ids"] == []
        wrong = {**_confirmation(undo), "token": resume["confirmation_token"]}
        assert (await client.call_tool_json("confirm_playlist", wrong))["error"]["code"] == "CONFIRMATION_INVALID"
        assert events() == before
        deleted = await client.call_tool_json("confirm_playlist", _confirmation(undo))
        assert deleted["result"] == {"status": "UNDONE", "playlist_id": target}
        assert review_messages[-1]["action_kind"] == "undo"
        assert events()[-1]["method"] == "delete_playlist"
        assert len([row for row in events() if row["method"] == "create_playlist"]) == 1
        inserted = [row["video_id"] for row in events() if row["method"] == "insert_playlist_item"]
        assert inserted == original["ordered_video_ids"]
    client.cleanup_stderr()


async def test_mcp_over_budget_makes_zero_provider_calls(scripted):
    connect, events = scripted

    async def consent(_context, _params):
        return types.ElicitResult(action="accept", content={"approved": True})

    async with connect(consent, units=100) as client:
        proposal = (await client.call_tool_json("propose_playlist", ARGS))["result"]
        before = events()
        output = await client.call_tool_json("confirm_playlist", _confirmation(proposal))
        assert output["error"]["code"] == "QUOTA_BUDGET_EXCEEDED"
        assert output["meta"]["quota_used"] == 0 and events() == before
    client.cleanup_stderr()

    async with connect(consent, no_channel=True) as client:
        proposal = (await client.call_tool_json("propose_playlist", ARGS))["result"]
        before = len(events())
        output = await client.call_tool_json("confirm_playlist", _confirmation(proposal))
        assert output["error"]["code"] == "NO_YOUTUBE_CHANNEL"
        assert [record["method"] for record in events()[before:]] == ["check_channel_eligibility"]
        assert all(not record.get("is_write") for record in events())
    client.cleanup_stderr()


async def test_non_eliciting_client_needs_separate_terminal_decision(scripted, tmp_path, monkeypatch):
    connect, events = scripted
    runner = CliRunner()
    monkeypatch.setenv("FOCUSLIST_PROVIDER", "fixture")
    monkeypatch.setenv("FOCUSLIST_DB_PATH", str(tmp_path / "actions.db"))
    monkeypatch.setenv("FOCUSLIST_AUTH_STORE_DIR", str(tmp_path / "auth"))
    monkeypatch.setattr(cli, "SystemClock", FakeClock)

    async with connect() as client:
        proposal = (await client.call_tool_json("propose_playlist", ARGS))["result"]
        pid = proposal["proposal_id"]
        before = events()
        local_review = await client.session.read_resource(AnyUrl(f"focuslist://proposals/{pid}"))
        assert json.loads(local_review.contents[0].text) == {
            key: value for key, value in proposal.items() if key != "confirmation_token"
        }
        first = await client.call_tool_json("confirm_playlist", _confirmation(proposal))
        assert first["error"]["code"] == "CONFIRMATION_INVALID" and events() == before
        rejected = runner.invoke(cli.app, ["approve", pid], input=f"approve {pid}\n")
        assert rejected.exit_code == 1 and "interactive local terminal" in rejected.output
        assert events() == before

        monkeypatch.setattr(cli, "_has_local_terminal", lambda: True)
        approved = runner.invoke(cli.app, ["approve", pid], input=f"approve {pid}\n")
        assert approved.exit_code == 0 and "Approval recorded" in approved.output
        assert proposal["confirmation_token"] not in approved.output
        assert all(vid in approved.output for vid in proposal["ordered_video_ids"])
        assert events() == before
        result = await client.call_tool_json("confirm_playlist", _confirmation(proposal))
        assert result["result"]["status"] == "CREATED"
    client.cleanup_stderr()
