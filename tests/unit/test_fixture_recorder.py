"""Unit tests for developer-only sanitized fixture recorder (C13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from focuslist.errors import InvalidArgumentsError
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.platform.recorder import record_public_fixtures, scrub_video_to_fixture
from focuslist.types import VideoRecord


def test_record_public_fixtures_writes_sanitized_files(
    tmp_path: Path, fixture_provider: FixtureVideoProvider
) -> None:
    counts = record_public_fixtures(
        fixture_provider, tmp_path, query="recursion", max_videos=5
    )
    assert counts["videos"] >= 1
    assert counts["channels"] >= 1
    assert counts["categories"] >= 1

    videos_data = json.loads((tmp_path / "sample_videos.json").read_text(encoding="utf-8"))
    assert all(item["untrusted"] is True for item in videos_data)
    assert (tmp_path / "sample_channels.json").exists()
    assert (tmp_path / "sample_categories.json").exists()


def test_scrub_video_rejects_raw_authorization_data() -> None:
    bad_video = VideoRecord(
        video_id="bad_auth_01",
        canonical_url="https://www.youtube.com/watch?v=bad_auth_01",
        title="Leak Bearer ya29.secret_token_value",
        channel_id="UC_test_01",
        channel_title="Test",
        duration_seconds=300,
    )
    with pytest.raises(InvalidArgumentsError):
        scrub_video_to_fixture(bad_video)
