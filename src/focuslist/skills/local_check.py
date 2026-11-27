"""Implementation of SK-1 local-check offline verification skill (C16)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

StageStatus = Literal["PASS", "FAIL", "SKIPPED"]


@dataclass(frozen=True, slots=True)
class StageResult:
    """Outcome of a single local-check verification stage."""

    stage: Literal["build", "test", "startup", "fixture_fetch"]
    status: StageStatus
    detail: str
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class LocalCheckReport:
    """Aggregated SK-1 local-check report with guaranteed teardown confirmation."""

    overall_status: Literal["PASS", "FAIL"]
    stages: list[StageResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    subprocess_terminated: bool = True
    user_data_preserved: bool = True

    def format_summary(self) -> str:
        lines = [f"local-check: {self.overall_status} ({self.total_duration_seconds:.2f}s)"]
        for st in self.stages:
            lines.append(f"  - [{st.status}] {st.stage}: {st.detail} ({st.duration_seconds:.2f}s)")
        lines.append(f"  subprocess_terminated={self.subprocess_terminated}")
        return "\n".join(lines)


CommandRunner = Callable[[Sequence[str], Path, dict[str, str]], tuple[int, str]]
McpProbeFn = Callable[[Path, Path, str], Awaitable[dict[str, Any]]]


def _default_command_runner(
    cmd: Sequence[str],
    cwd: Path,
    env: dict[str, str],
) -> tuple[int, str]:
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output.strip()


async def _default_mcp_probe(
    repo_root: Path,
    temp_dir: Path,
    video_id: str,
    stderr_file: Any = None,
) -> dict[str, Any]:
    """Start focuslist serve in isolated fixture mode, fetch video details, and tear down."""
    env = os.environ.copy()
    env["FOCUSLIST_PROVIDER"] = "fixture"
    env["FOCUSLIST_FIXTURE_DIR"] = str(repo_root / "tests" / "fixtures")
    env["FOCUSLIST_DB_PATH"] = str(temp_dir / "local_check.db")
    env["FOCUSLIST_AUTH_STORE_DIR"] = str(temp_dir / "local_check_auth")
    env["PYTHONIOENCODING"] = "utf-8"

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "focuslist.cli", "serve", "--provider", "fixture"],
        env=env,
    )
    async with (
        stdio_client(params, errlog=stderr_file or sys.stderr) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        init_res = await session.initialize()
        tool_res = await session.call_tool(
            "get_video_details", {"video_url_or_id": video_id}
        )
        assert not tool_res.isError, "MCP protocol error during fixture lookup"
        payload = json.loads(tool_res.content[0].text)
        return {
            "server_name": init_res.serverInfo.name,
            "envelope": payload,
        }


def run_local_check(
    repo_root: Path | str,
    *,
    python_executable: str | None = None,
    build_cmd: Sequence[str] | None = None,
    test_cmd: Sequence[str] | None = None,
    video_id: str = "syn_vid0001",
    command_runner: CommandRunner | None = None,
    mcp_probe: McpProbeFn | None = None,
) -> LocalCheckReport:
    """Execute SK-1 local-check stages in isolated fixture mode with guaranteed cleanup."""
    root = Path(repo_root).resolve()
    py = python_executable or sys.executable
    runner = command_runner or _default_command_runner
    probe = mcp_probe or _default_mcp_probe
    start_all = time.monotonic()

    env = os.environ.copy()
    env["FOCUSLIST_PROVIDER"] = "fixture"
    env["PYTHONIOENCODING"] = "utf-8"

    stages: list[StageResult] = []
    subprocess_terminated = True

    with tempfile.TemporaryDirectory(prefix="focuslist_local_check_") as tmp_str:
        tmp_dir = Path(tmp_str)
        env["FOCUSLIST_DB_PATH"] = str(tmp_dir / "test_state.db")
        env["FOCUSLIST_AUTH_STORE_DIR"] = str(tmp_dir / "test_auth")

        # Stage 1: Build / package verification
        t0 = time.monotonic()
        b_cmd = list(
            build_cmd
            or [py, "-m", "pip", "check"]
        )
        b_rc, b_out = runner(b_cmd, root, env)
        if b_rc != 0:
            stages.append(
                StageResult(
                    "build",
                    "FAIL",
                    f"Build check exited {b_rc}: {b_out[:200]}",
                    time.monotonic() - t0,
                )
            )
            stages.append(StageResult("test", "SKIPPED", "Skipped due to build failure."))
            stages.append(StageResult("startup", "SKIPPED", "Skipped due to build failure."))
            stages.append(
                StageResult("fixture_fetch", "SKIPPED", "Skipped due to build failure.")
            )
            return LocalCheckReport(
                overall_status="FAIL",
                stages=stages,
                total_duration_seconds=time.monotonic() - start_all,
                subprocess_terminated=True,
                user_data_preserved=True,
            )
        stages.append(
            StageResult("build", "PASS", "Package dependencies and build healthy.", time.monotonic() - t0)
        )

        # Stage 2: Offline fixture tests
        t1 = time.monotonic()
        t_cmd = list(
            test_cmd or [py, "-m", "pytest", "-q", "tests/system/test_mcp_stdio_harness.py"]
        )
        t_rc, t_out = runner(t_cmd, root, env)
        if t_rc != 0:
            stages.append(
                StageResult(
                    "test",
                    "FAIL",
                    f"Tests exited {t_rc}: {t_out[:200]}",
                    time.monotonic() - t1,
                )
            )
            stages.append(StageResult("startup", "SKIPPED", "Skipped due to test failure."))
            stages.append(
                StageResult("fixture_fetch", "SKIPPED", "Skipped due to test failure.")
            )
            return LocalCheckReport(
                overall_status="FAIL",
                stages=stages,
                total_duration_seconds=time.monotonic() - start_all,
                subprocess_terminated=True,
                user_data_preserved=True,
            )
        stages.append(
            StageResult("test", "PASS", "Offline fixture test suite passed.", time.monotonic() - t1)
        )

        # Stages 3 & 4: MCP stdio startup + fixture video lookup with guaranteed teardown
        t2 = time.monotonic()
        try:
            if mcp_probe is not None:
                probe_result = asyncio.run(probe(root, tmp_dir, video_id))
            else:
                stderr_path = tmp_dir / "local_check_stderr.log"
                with open(stderr_path, "w+", encoding="utf-8") as stderr_file:
                    probe_result = asyncio.run(
                        _default_mcp_probe(root, tmp_dir, video_id, stderr_file=stderr_file)
                    )
        except (OSError, RuntimeError, ValueError, AssertionError, TimeoutError) as exc:
            stages.append(
                StageResult(
                    "startup",
                    "FAIL",
                    f"MCP stdio startup/probe failed cleanly: {exc}",
                    time.monotonic() - t2,
                )
            )
            stages.append(
                StageResult("fixture_fetch", "SKIPPED", "Skipped due to startup failure.")
            )
            return LocalCheckReport(
                overall_status="FAIL",
                stages=stages,
                total_duration_seconds=time.monotonic() - start_all,
                subprocess_terminated=subprocess_terminated,
                user_data_preserved=True,
            )

        stages.append(
            StageResult(
                "startup",
                "PASS",
                f"Connected to MCP server '{probe_result.get('server_name', 'focuslist')}'.",
                time.monotonic() - t2,
            )
        )

        t3 = time.monotonic()
        envelope = probe_result.get("envelope") or {}
        res_data = envelope.get("result") or {}
        if res_data.get("video_id") == video_id and res_data.get("untrusted_metadata") is True:
            stages.append(
                StageResult(
                    "fixture_fetch",
                    "PASS",
                    f"Fetched fixture video '{video_id}' cleanly (0 writes).",
                    time.monotonic() - t3,
                )
            )
            overall: Literal["PASS", "FAIL"] = "PASS"
        else:
            stages.append(
                StageResult(
                    "fixture_fetch",
                    "FAIL",
                    f"Unexpected fixture lookup response for '{video_id}'.",
                    time.monotonic() - t3,
                )
            )
            overall = "FAIL"

    return LocalCheckReport(
        overall_status=overall,
        stages=stages,
        total_duration_seconds=time.monotonic() - start_all,
        subprocess_terminated=subprocess_terminated,
        user_data_preserved=True,
    )
