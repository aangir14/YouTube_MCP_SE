"""Test-only MCP server that records offline provider calls against fake time."""

from __future__ import annotations

import json
import os
from pathlib import Path

from focuslist.clock import FakeClock
from focuslist.config import get_settings
from focuslist.context import RequestContext
from focuslist.errors import VideoUnavailableError
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.server import create_server


class RecordedFixture(FixtureVideoProvider):
    def __init__(self, fixture_dir, clock, trace, fail_position=None):
        super().__init__(fixture_dir)
        self.clock = clock
        self.trace = trace
        self.fail_position = fail_position
        self.remote = trace.with_suffix(".state.json")
        if self.remote.exists():
            self._created_playlists = json.loads(self.remote.read_text(encoding="utf-8"))

    def _record_call(self, method, **details):
        super()._record_call(method, **details)
        with self.trace.open("a", encoding="utf-8") as events:
            events.write(json.dumps({
                "time": self.clock.now_epoch(), "method": method, **details,
            }) + "\n")

    def _save(self):
        self.remote.write_text(json.dumps(self._created_playlists), encoding="utf-8")

    def check_channel_eligibility(self, account_id):
        super().check_channel_eligibility(account_id)
        return os.environ.get("C18_NO_CHANNEL") != "1"

    def create_playlist(self, *args, **kwargs):
        result = super().create_playlist(*args, **kwargs)
        self._save()
        return result

    def insert_playlist_item(self, playlist_id, video_id, position=None, **kwargs):
        if position == self.fail_position:
            self.fail_position = None
            self._record_call("reject_insert", position=position, is_write=True)
            raise VideoUnavailableError()
        result = super().insert_playlist_item(playlist_id, video_id, position, **kwargs)
        self._save()
        return result

    def delete_playlist(self, *args, **kwargs):
        result = super().delete_playlist(*args, **kwargs)
        self._save()
        return result


if __name__ == "__main__":
    cfg = get_settings()
    assert cfg.provider == "fixture"
    fake_clock = FakeClock()
    fake_clock.advance(int(os.environ.get("C18_CLOCK_OFFSET", "0")))
    failure = os.environ.get("C18_FAILURE")
    provider = RecordedFixture(
        cfg.fixture_dir, fake_clock, Path(os.environ["C18_TEST_TRACE"]),
        int(failure) if failure else None,
    )
    create_server(
        cfg, RequestContext(settings=cfg, clock=fake_clock),
        provider_override=provider, write_sleep=fake_clock.advance,
    ).run()
