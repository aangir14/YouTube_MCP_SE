"""C11 normalisation cases with synthetic input only (UT-PARSE and NEG-METADATA)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from focuslist.errors import InvalidArgumentsError, InvalidChannelIdError, InvalidVideoIdError
from focuslist.metadata import (
    format_duration_iso,
    normalise_activity_record,
    normalise_channel_record,
    normalise_video_record,
    parse_channel_reference,
    parse_duration_seconds,
    parse_playlist_id,
    parse_utc_datetime,
    parse_video_id,
    playlist_url,
    same_primary_language,
    select_video_language,
    video_watch_url,
)
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    VideoRecord,
    format_duration_display,
)

VIDEO_ID = "syn_vid0001"
CHANNEL_ID = "UC" + "a" * 22
PLAYLIST_ID = "PLfixture_01"


@pytest.mark.parametrize(
    "value",
    [
        VIDEO_ID,
        f" {VIDEO_ID} ",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&t=15",
        f"https://youtu.be/{VIDEO_ID}?t=2",
        f"https://youtube.com/shorts/{VIDEO_ID}",
        f"https://m.youtube.com/embed/{VIDEO_ID}",
    ],
)
def test_video_forms_canonicalise(value: str) -> None:
    assert parse_video_id(value) == VIDEO_ID
    assert video_watch_url(value) == f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 10,
        "a" * 12,
        "a" * 2049,
        "漢" * 11,
        VIDEO_ID + "\n",
        f"http://youtube.com/watch?v={VIDEO_ID}",
        f"https://example.test/watch?v={VIDEO_ID}",
        f"https://youtube.com.example.test/watch?v={VIDEO_ID}",
        f"https://www.youtube.com:443/watch?v={VIDEO_ID}",
        f"https://viewer@youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}&v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}&%76=",
        f"https://youtu.be/{VIDEO_ID}/extra",
        f"https://youtube.com/other/{VIDEO_ID}",
        "https://youtube.com/watch?v=",
        "https://youtube.com/watch?list=PLfixture_01",
    ],
)
def test_invalid_video_references(value: str) -> None:
    with pytest.raises(InvalidVideoIdError):
        parse_video_id(value)


def test_channel_lookup_forms_and_cache_keys() -> None:
    by_id = parse_channel_reference(CHANNEL_ID)
    assert by_id == parse_channel_reference(f"https://www.youtube.com/channel/{CHANNEL_ID}/")
    assert by_id.canonical_url == f"https://www.youtube.com/channel/{CHANNEL_ID}"
    assert by_id.provider_arguments() == {"channel_id": CHANNEL_ID}
    handle = parse_channel_reference("@算法")
    assert handle == parse_channel_reference("https://www.youtube.com/@%E7%AE%97%E6%B3%95")
    assert handle.provider_arguments() == {"handle": "@算法"}
    assert handle.canonical_url == "https://www.youtube.com/@%E7%AE%97%E6%B3%95"
    assert (
        parse_channel_reference("@StudyLab").cache_key
        == parse_channel_reference("https://youtube.com/@studylab").cache_key
    )


@pytest.mark.parametrize(
    "value",
    [
        "@",
        "@a/b",
        "@a?b",
        "@a#b",
        "@a%20b",
        "UCshort",
        "https://youtube.com/@one%2Ftwo",
        "https://youtube.com/@name%20",
        "https://youtube.com/@%FF",
        "https://youtube.com/@a/videos",
        "https://evil.test/@channel",
    ],
)
def test_invalid_channel_references(value: str) -> None:
    with pytest.raises(InvalidChannelIdError) as raised:
        parse_channel_reference(value)
    assert "legacy_custom_url" not in raised.value.details.values()


def test_legacy_channel_has_explicit_remediation() -> None:
    with pytest.raises(InvalidChannelIdError, match="@handle") as raised:
        parse_channel_reference("https://www.youtube.com/c/FixtureLab")
    assert raised.value.details == {"reason": "legacy_custom_url"}


@pytest.mark.parametrize(
    "value",
    [
        PLAYLIST_ID,
        f"https://youtube.com/playlist?list={PLAYLIST_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}&list={PLAYLIST_ID}",
        f"https://youtu.be/{VIDEO_ID}?list={PLAYLIST_ID}",
    ],
)
def test_playlist_reference_round_trip(value: str) -> None:
    assert parse_playlist_id(value) == PLAYLIST_ID
    assert playlist_url(value) == f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"


@pytest.mark.parametrize(
    "value",
    [
        "PL?",
        "https://youtube.com/playlist",
        "https://youtube.com/playlist?list=",
        f"https://youtube.com/playlist?list={PLAYLIST_ID}&list={PLAYLIST_ID}",
        f"https://evil.test/playlist?list={PLAYLIST_ID}",
        f"https://youtu.be/invalid?list={PLAYLIST_ID}",
        f"https://youtube.com/watch?v=invalid&list={PLAYLIST_ID}",
        f"https://youtube.com/shorts/{VIDEO_ID}?list={PLAYLIST_ID}",
    ],
)
def test_invalid_playlist_references(value: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        parse_playlist_id(value)


@pytest.mark.parametrize(
    ("value", "seconds", "display"),
    [
        ("PT0S", 0, "00:00"),
        ("PT59S", 59, "00:59"),
        ("PT60S", 60, "01:00"),
        ("PT20M", 1200, "20:00"),
        ("PT59M59S", 3599, "59:59"),
        ("PT1H", 3600, "1:00:00"),
        ("PT1H2M3S", 3723, "1:02:03"),
        ("P1DT2H", 93600, "26:00:00"),
        ("P1W", 604800, "168:00:00"),
    ],
)
def test_duration_bounds_and_round_trip(value: str, seconds: int, display: str) -> None:
    assert parse_duration_seconds(value) == seconds
    assert parse_duration_seconds(format_duration_iso(seconds)) == seconds
    assert format_duration_display(seconds) == display


@pytest.mark.parametrize(
    "value",
    [
        "",
        "P",
        "PT",
        "P1DT",
        "PT1S1M",
        "-PT1M",
        "PT-1M",
        "PT1.5S",
        "P1M",
        "P1Y",
        "P1WT1H",
        "PT١M",
        "PT9223372036854775808S",
        "PT" + "9" * 65 + "S",
    ],
)
def test_invalid_duration_is_rejected(value: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        parse_duration_seconds(value)


def test_positive_duration_boundary() -> None:
    with pytest.raises(InvalidArgumentsError):
        parse_duration_seconds("PT0S", allow_zero=False)
    assert parse_duration_seconds("PT1S", allow_zero=False) == 1


def test_utc_dates_and_offsets() -> None:
    utc = datetime(2024, 2, 29, tzinfo=UTC)
    assert parse_utc_datetime("2024-02-29", allow_date=True) == utc
    assert parse_utc_datetime("2024-02-29T05:30:00+05:30") == utc
    assert parse_utc_datetime("2024-02-28T19:00:00-05:00") == utc
    assert parse_utc_datetime("2024-02-29T00:00:00.000001Z").microsecond == 1


@pytest.mark.parametrize(
    "value",
    [
        "2024-02-29",
        "2023-02-29T00:00:00Z",
        "2024-02-29T00:00:00",
        "2024-02-29 00:00:00Z",
        "2024-02-29T24:00:00Z",
        "2024-02-29T00:00:00+01:60",
        "0001-01-01T00:00:00+01:00",
    ],
)
def test_invalid_or_unzoned_timestamp(value: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        parse_utc_datetime(value)


def test_language_metadata_and_matching() -> None:
    assert same_primary_language("EN-gb", "en-US") is True
    assert same_primary_language("zh-Hant-TW", "zh-Hans") is True
    assert same_primary_language("en", "fr-CA") is False
    for unknown in (None, "", "und", "x-test", "en_US", "en--US", "en-US-GB"):
        assert same_primary_language(unknown, "en") is None
    assert select_video_language("fr-CA", "en") == ("fr-ca", "audio")
    assert select_video_language("und", "en-US") == ("en-us", "metadata")
    assert select_video_language(None, "und") == (None, "unknown")


def test_sparse_video_preserves_absence_and_unicode() -> None:
    raw = VideoRecord(
        video_id=VIDEO_ID,
        canonical_url=video_watch_url(VIDEO_ID),
        title="算法\u200bと Café",
        channel_id=CHANNEL_ID,
        channel_title="实验室",
        published_at=datetime(2026, 1, 1),
    )
    clean = normalise_video_record(raw)
    assert clean.title == "算法と Café"
    assert clean.channel_title == "实验室"
    assert clean.duration_display is clean.duration_iso is clean.duration_seconds is None
    assert clean.description is clean.tags is clean.published_at is clean.visibility is None
    assert clean.is_live is clean.is_upcoming is clean.is_age_restricted is None
    assert clean.language_provenance == "unknown" and clean.untrusted
    assert raw.title != clean.title

    known = normalise_video_record(
        raw.model_copy(
            update={
                "duration_iso": "PT0S",
                "description": "",
                "tags": [],
                "view_count": 0,
                "is_live": False,
                "language": "en-GB",
                "language_provenance": "audio",
                "published_at": parse_utc_datetime("2024-02-29T05:30:00+05:30"),
            }
        )
    )
    assert (known.duration_seconds, known.duration_display, known.duration_iso) == (
        0,
        "00:00",
        "PT0S",
    )
    assert known.description == "" and known.tags == [] and known.view_count == 0
    assert (
        known.is_live is False
        and known.language == "en-gb"
        and known.language_provenance == "audio"
    )
    assert known.published_at == datetime(2024, 2, 29, tzinfo=UTC)


def test_channel_count_and_activity_provenance() -> None:
    raw = ChannelRecord(channel_id=CHANNEL_ID, canonical_url="", title="Café", subscriber_count=0)
    assert normalise_channel_record(raw).subscriber_count == 0
    hidden = normalise_channel_record(raw.model_copy(update={"hidden_subscriber_count": True}))
    assert hidden.subscriber_count is None and hidden.keywords is None
    event = AccountActivityRecord(
        item_id=VIDEO_ID,
        account_id="fixture",
        activity_type="like",
        timestamp=datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        timestamp_provenance="publication_fallback",
    )
    clean = normalise_activity_record(event)
    assert clean.timestamp == datetime(2026, 1, 1, tzinfo=UTC)
    assert clean.timestamp_provenance == "publication_fallback"
    unknown = normalise_activity_record(event.model_copy(update={"timestamp": None}))
    assert unknown.timestamp is None and unknown.timestamp_provenance == "unknown"
