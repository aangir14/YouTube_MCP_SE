"""Scripted stdio MCP test client harness for offline end-to-end verification (C10)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Self

from mcp.client.session import ClientSession, ElicitationFnT
from mcp.client.stdio import StdioServerParameters, stdio_client


class McpStdioTestClient:
    """Async context manager launching FocusList over stdio and verifying JSON-RPC traffic."""

    def __init__(
        self,
        provider: str = "fixture",
        fixture_dir: Path | str | None = None,
        extra_env: dict[str, str] | None = None,
        server_args: list[str] | None = None,
        elicitation_callback: ElicitationFnT | None = None,
    ) -> None:
        self.provider = provider
        self.fixture_dir = Path(fixture_dir) if fixture_dir else None
        self.extra_env = extra_env or {}
        self.server_args = server_args
        self.elicitation_callback = elicitation_callback
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._init_result: Any = None
        self._stderr_file: Any = None
        self._stderr_path: Path | None = None
        self.closed: bool = False

    async def __aenter__(self) -> Self:
        env = os.environ.copy()
        env["FOCUSLIST_PROVIDER"] = self.provider
        env["PYTHONIOENCODING"] = "utf-8"
        if self.fixture_dir is not None:
            env["FOCUSLIST_FIXTURE_DIR"] = str(self.fixture_dir)
        env.update(self.extra_env)

        # Use a real temp file for stderr so subprocess piping works portably on Windows/POSIX
        tmp = self._stack.enter_context(
            tempfile.NamedTemporaryFile(  # noqa: SIM115
                mode="w+", encoding="utf-8", prefix="focuslist_stderr_", suffix=".log", delete=False
            )
        )
        self._stderr_file = tmp
        self._stderr_path = Path(tmp.name)

        server_params = StdioServerParameters(
            command=sys.executable,
            args=self.server_args or ["-m", "focuslist.cli", "serve", "--provider", self.provider],
            env=env,
        )

        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_client(server_params, errlog=self._stderr_file)
        )
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream, elicitation_callback=self.elicitation_callback)
        )
        self._init_result = await self._session.initialize()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        try:
            await self._stack.aclose()
        finally:
            self.closed = True

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("McpStdioTestClient is not connected.")
        return self._session

    @property
    def server_info(self) -> Any:
        return self._init_result

    def read_stderr(self) -> str:
        """Read captured stderr diagnostic output."""
        if self._stderr_path is None or not self._stderr_path.exists():
            return ""
        return self._stderr_path.read_text(encoding="utf-8", errors="replace")

    def cleanup_stderr(self) -> None:
        """Remove temporary stderr capture file."""
        if self._stderr_path is not None and self._stderr_path.exists():
            try:
                self._stderr_path.unlink()
            except OSError:
                pass

    async def list_tool_names(self) -> list[str]:
        res = await self.session.list_tools()
        return [t.name for t in res.tools]

    async def list_resource_uris(self) -> list[str]:
        res = await self.session.list_resources()
        return [str(r.uri) for r in res.resources]

    async def list_prompt_names(self) -> list[str]:
        res = await self.session.list_prompts()
        return [p.name for p in res.prompts]

    async def call_tool_json(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Invoke a tool over stdio and parse its JSON envelope."""
        result = await self.session.call_tool(name, arguments or {})
        assert not result.isError, f"MCP protocol-level error calling {name}: {result.content}"
        assert len(result.content) >= 1, f"Empty content returned from {name}"
        text = result.content[0].text
        return json.loads(text)
