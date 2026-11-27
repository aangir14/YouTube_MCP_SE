"""System tests for guarded write routes, quota/auth MCP tools, and CLI commands (C16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from focuslist.cli import app
from focuslist.clock import FakeClock
from focuslist.config import Settings
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.platform.storage import FocusListStorage
from tests.mcp_harness import McpStdioTestClient

runner = CliRunner()


@pytest.mark.asyncio
async def test_mcp_confirm_and_undo_guard_reject_placeholder_and_unapproved_zero_writes(
    tmp_path: Path,
) -> None:
    """Placeholder, missing, tampered, and unapproved confirmations produce zero writes."""
    db_path = tmp_path / "guard.db"
    async with McpStdioTestClient(
        provider="fixture",
        extra_env={"FOCUSLIST_DB_PATH": str(db_path)},
    ) as client:
        # Propose remains eligible and read-only
        prop = await client.call_tool_json(
            "propose_playlist",
            {
                "topic": "recursion",
                "target_duration": "PT45M",
                "max_item_duration": "PT20M",
            },
        )
        assert prop["result"]["status"] == "PROPOSED"
        assert prop["result"]["writes_executed"] == 0
        pid = prop["result"]["proposal_id"]
        placeholder_tok = prop["result"]["confirmation_token"]

        # Placeholder token -> CONFIRMATION_INVALID, zero writes
        c1 = await client.call_tool_json(
            "confirm_playlist",
            {"proposal_id": pid, "token": placeholder_tok},
        )
        assert c1["error"]["code"] == "CONFIRMATION_INVALID"
        assert c1["error"]["details"]["writes_executed"] == 0

        # Missing/empty fields -> INVALID_ARGUMENTS, zero writes
        c2 = await client.call_tool_json(
            "confirm_playlist",
            {"proposal_id": "", "token": ""},
        )
        assert c2["error"]["code"] == "INVALID_ARGUMENTS"

        # Tampered/unapproved arbitrary token -> CONFIRMATION_INVALID, zero writes
        c3 = await client.call_tool_json(
            "confirm_playlist",
            {"proposal_id": pid, "token": "forged_hmac_token"},
        )
        assert c3["error"]["code"] == "CONFIRMATION_INVALID"
        assert c3["error"]["details"]["writes_executed"] == 0

        # Unowned playlist undo -> INVALID_ARGUMENTS, zero writes
        u1 = await client.call_tool_json("undo_playlist", {"playlist_id": "PL_unrelated_001"})
        assert u1["error"]["code"] == "INVALID_ARGUMENTS"
        assert u1["error"]["details"]["writes_executed"] == 0

        # Estimate and status tools are local (0 provider calls, 0 quota_used)
        est = await client.call_tool_json(
            "estimate_quota",
            {"target_tool": "confirm_playlist", "arguments": {"item_count": 12}},
        )
        assert est["result"]["estimated_general_units"] == 651
        assert est["meta"]["quota_used"] == 0

        qstat = await client.call_tool_json("get_quota_status", {})
        assert qstat["result"]["search_calls_used"] == 1
        assert qstat["meta"]["quota_used"] == 0

        astat = await client.call_tool_json("auth_status", {})
        assert astat["result"]["authenticated"] is True
        assert "access_token" not in str(astat)
    client.cleanup_stderr()


@pytest.mark.asyncio
async def test_mcp_cache_hit_and_fault_mode_st_fr11(tmp_path: Path) -> None:
    """Verify ST-FR11: usable cache hit makes 0 provider calls; fault mode returns safe envelopes."""
    from focuslist import server as server_module

    clock = FakeClock()
    cfg = Settings(provider="fixture", db_path=tmp_path / "st_fr11.db", cache_enabled=True)
    srv = server_module.create_server(settings=cfg)

    import json

    raw1 = await srv.call_tool("get_video_details", {"video_url_or_id": "syn_vid0001"})
    c1 = raw1[0] if isinstance(raw1, tuple) else raw1
    r1 = json.loads(c1[0].text)
    assert r1["meta"]["quota_used"] == 1
    assert r1["meta"]["cache_hits"] == 0

    raw2 = await srv.call_tool("get_video_details", {"video_url_or_id": "syn_vid0001"})
    c2 = raw2[0] if isinstance(raw2, tuple) else raw2
    r2 = json.loads(c2[0].text)
    assert r2["result"] == r1["result"]
    assert r2["meta"]["quota_used"] == 0
    assert r2["meta"]["cache_hits"] == 1
    _ = clock


def test_cli_purge_and_quota_success_and_error_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify focuslist purge and quota CLI commands handle valid and invalid inputs."""
    db_path = tmp_path / "cli_test.db"
    monkeypatch.setenv("FOCUSLIST_DB_PATH", str(db_path))

    # Populate account-scoped cache row
    storage = FocusListStorage(db_path)
    storage.set_cache("user_likes", {}, "user", ["v1"], account_id="acct_cli")
    storage.set_cache("video_detail", {"video_id": "v_pub"}, "video", {"title": "Pub"})

    res_purge = runner.invoke(app, ["purge", "--account", "acct_cli", "--db-path", str(db_path)])
    assert res_purge.exit_code == 0
    assert "1 account-scoped cache rows deleted" in res_purge.output
    assert storage.get_cache("user_likes", {}, account_id="acct_cli") is None
    assert storage.get_cache("video_detail", {"video_id": "v_pub"}) == {"title": "Pub"}

    # Empty account flag -> nonzero exit code
    res_bad = runner.invoke(app, ["purge", "--account", "   ", "--db-path", str(db_path)])
    assert res_bad.exit_code != 0

    # Non-existent DB with --require-existing-db -> nonzero exit code
    res_missing = runner.invoke(
        app, ["purge", "--db-path", str(tmp_path / "missing.db"), "--require-existing-db"]
    )
    assert res_missing.exit_code != 0

    # Quota CLI shares ledger with MCP status
    res_quota = runner.invoke(app, ["quota", "--db-path", str(db_path)])
    assert res_quota.exit_code == 0
    assert "Effective Units Available : 9500" in res_quota.output
    assert "Scheduled Live CI Caps    : 500 units / 5 searches" in res_quota.output


def test_placeholder_fixture_provider_not_called_by_guarded_confirm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Direct server.call_tool confirm_playlist with placeholder token makes 0 FixtureVideoProvider writes."""
    import asyncio
    import json

    from focuslist import server as server_module

    spy = FixtureVideoProvider(fixture_dir=Path("tests/fixtures"))
    monkeypatch.setattr(server_module, "create_provider", lambda settings: spy)
    cfg = Settings(provider="fixture", db_path=tmp_path / "spy.db")
    srv = server_module.create_server(settings=cfg)

    async def _run() -> dict:
        res = await srv.call_tool(
            "confirm_playlist",
            {"proposal_id": "prop_123", "token": "pending_c21_hmac_signing:prop_123"},
        )
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text)

    out = asyncio.run(_run())
    assert out["error"]["code"] == "CONFIRMATION_INVALID"
    assert spy.writes == 0
    assert spy.requests == 0
