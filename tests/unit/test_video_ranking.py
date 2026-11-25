"""UT-SCORE for the C08 FR-1 formula and deterministic missing-field handling."""

import pytest

from focuslist.discovery.videos import rank_similar_videos
from focuslist.types import VideoRecord


def _video(video_id: str, **overrides) -> VideoRecord:
    return VideoRecord(
        **{
            "video_id": video_id,
            "canonical_url": "",
            "title": "Algebra",
            "channel_id": "UC" + "a" * 22,
            "channel_title": "Synthetic",
            "tags": ["Algebra"],
            "category_id": "27",
            "duration_seconds": 120,
            "language": "en-gb",
            **overrides,
        }
    )


def test_c08_weighted_components() -> None:
    seed = _video("v0000000000")
    match = _video("v0000000001", category_id="28", duration_seconds=60, language="en-us")
    result = rank_similar_videos(seed, [match])[0]
    expected_raws = {
        "text_cosine": 1,
        "tag_overlap": 1,
        "category_match": 0,
        "duration_fit": 0.5,
        "language_match": 1,
        "same_channel": 1,
    }
    assert {key: trace["raw"] for key, trace in result["feature_trace"].items()} == pytest.approx(
        expected_raws
    )
    assert result["score"] == 0.85
    assert result["shared_terms"] == ["algebra"]
    assert "category_id" not in result["missing_fields"]


def test_empty_text_and_known_empty_tags_do_not_invent_overlap() -> None:
    seed = _video("v0000000000", title="", tags=[])
    same = _video("v0000000001", title="the", tags=[])
    absent = _video("v0000000002", title="", tags=None, language=None)
    present_row, absent_row = rank_similar_videos(seed, [absent, same])
    assert present_row["item_id"] == same.video_id
    assert present_row["feature_trace"]["text_cosine"]["raw"] == 0
    assert present_row["feature_trace"]["tag_overlap"]["raw"] == 0
    assert "tags" not in present_row["missing_fields"]
    assert {"text", "tags", "language"} <= set(absent_row["missing_fields"])
    assert absent_row["low_confidence"] and not absent_row["shared_terms"]
