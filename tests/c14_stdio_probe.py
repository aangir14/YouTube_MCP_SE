"""Test-only fixture MCP launcher that saves actual synthetic provider counters."""

import json
import sys
from pathlib import Path
from typing import Any

from focuslist import server
from focuslist.config import Settings
from focuslist.platform.fixture_provider import FixtureVideoProvider


class ObservedFixture(FixtureVideoProvider):
    def __init__(self, directory: Path, output: Path) -> None:
        super().__init__(directory)
        self.output = output
        self.pages = json.loads((directory / "c14_pages.json").read_text(encoding="utf-8"))
        self._snapshot()

    def _snapshot(self) -> None:
        snapshot = {
            "provider_requests": self.requests,
            "simulated_attempts": self.network_attempts,
            "writes": self.writes,
            "calls": dict(self.call_counts),
            "detail_batch_sizes": [
                len(call["args"]["video_ids"])
                for call in self.call_log
                if call["method"] == "get_video_details"
            ],
        }
        self.output.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")

    def _record_call(self, method: str, **kwargs: Any) -> None:
        super()._record_call(method, **kwargs)
        self._snapshot()

    def search_video_ids(self, query: str, max_results: int = 50) -> list[str]:
        self._record_call("search_video_ids", query=query, max_results=max_results)
        return self.pages.get(query, [])

    def get_channel_upload_ids(self, channel_id: str, max_results: int = 50) -> list[str]:
        self._record_call("get_channel_upload_ids", channel_id=channel_id, max_results=max_results)
        return self.pages.get("uploads", [])


if __name__ == "__main__":
    fixture_dir, evidence = map(Path, sys.argv[1:])
    provider = ObservedFixture(fixture_dir, evidence)
    server.create_provider = lambda settings: provider
    server.create_server(settings=Settings(provider="fixture", fixture_dir=fixture_dir)).run(
        transport="stdio"
    )
