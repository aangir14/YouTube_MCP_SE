"""Fixture-only subprocess with an observable read and write call trace."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from focuslist.clock import FakeClock
from focuslist.config import get_settings
from focuslist.context import RequestContext
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.server import create_server


class RecordedProvider(FixtureVideoProvider):
    def _record_call(self, method: str, **details: Any) -> None:
        super()._record_call(method, **details)
        with Path(os.environ["C19_TEST_TRACE"]).open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(self.call_log[-1]) + "\n")


if __name__ == "__main__":
    settings = get_settings()
    assert settings.provider == "fixture"
    clock = FakeClock(datetime(2026, 11, 25, tzinfo=UTC))
    create_server(
        settings, RequestContext(settings=settings, clock=clock),
        provider_override=RecordedProvider(settings.fixture_dir),
    ).run()
