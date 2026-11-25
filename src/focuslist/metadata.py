"""Shared, offline normalisation for FocusList request inputs and provider records."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal
from urllib.parse import SplitResult, parse_qs, quote, unquote, urlsplit

from focuslist.errors import (
    InvalidArgumentsError,
    InvalidChannelIdError,
    InvalidVideoIdError,
)
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    LanguageProvenance,
    VideoRecord,
    sanitize_untrusted_text,
)

_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
_SHORT_HOST = "youtu.be"
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_PLAYLIST_ID = re.compile(r"(?:[A-Za-z0-9_-]{10,128}|WL|LL)")
_DURATION = re.compile(
    r"P(?:(?P<weeks>[0-9]+)W|(?:(?P<days>[0-9]+)D)?"
    r"(?:T(?:(?P<hours>[0-9]+)H)?(?:(?P<minutes>[0-9]+)M)?"
    r"(?:(?P<seconds>[0-9]+)S)?)?)"
)
_DURATION_UNITS = {"weeks": 604800, "days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}
_MAX_DURATION = 2**63 - 1
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,6})?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
# Modern langtag syntax from RFC 5646. Registry and grandfathered aliases are out of scope.
_LANGUAGE_TAG = re.compile(
    r"(?:[a-z]{2,3}(?:-[a-z]{3}){0,3}|[a-z]{4}|[a-z]{5,8})"
    r"(?:-[a-z]{4})?(?:-(?:[a-z]{2}|[0-9]{3}))?"
    r"(?:-(?:[a-z0-9]{5,8}|[0-9][a-z0-9]{3}))*"
    r"(?:-[0-9a-wy-z](?:-[a-z0-9]{2,8})+)*(?:-x(?:-[a-z0-9]{1,8})+)?"
)


def _clean_reference(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Expected an identifier or URL up to 2048 characters.")
    value = value.strip(" ")
    if not value or any(ch.isspace() or unicodedata.category(ch)[0] == "C" for ch in value):
        raise ValueError("The identifier must be nonempty and contain no whitespace or controls.")
    if "\\" in value:
        raise ValueError("Backslashes are unsupported in identifiers and URLs.")
    return value


def _youtube_url(value: str, *, allow_short: bool = False) -> SplitResult:
    url = urlsplit(value)
    host = url.netloc.lower()
    if url.scheme != "https" or (
        host not in _YOUTUBE_HOSTS and not (allow_short and host == _SHORT_HOST)
    ):
        raise ValueError("Use HTTPS with an exact supported YouTube host and no port or userinfo.")
    return url


def _one_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    if len(values) != 1:
        raise ValueError(f"The URL must contain exactly one {key} parameter.")
    return values[0]


def parse_video_id(value: str) -> str:
    """Return the case-sensitive ID for a raw ID or approved YouTube video URL."""
    try:
        value = _clean_reference(value)
        if _VIDEO_ID.fullmatch(value):
            return value
        url = _youtube_url(value, allow_short=True)
        query = parse_qs(url.query, keep_blank_values=True)
        if url.netloc.lower() != _SHORT_HOST and url.path == "/watch":
            video_id = _one_query_value(query, "v")
        else:
            path_pattern = (
                r"/([^/]+)/?"
                if url.netloc.lower() == _SHORT_HOST
                else r"/(?:shorts|embed)/([^/]+)/?"
            )
            path = re.fullmatch(path_pattern, url.path)
            if path is None or "v" in query:
                raise ValueError("Use a supported video URL with one unambiguous video ID.")
            video_id = path[1]
        if _VIDEO_ID.fullmatch(video_id):
            return video_id
        raise ValueError("A video ID must contain exactly 11 URL-safe ASCII characters.")
    except ValueError as exc:
        raise InvalidVideoIdError(str(exc)) from None


def video_watch_url(video_id: str) -> str:
    """Produce the canonical watch URL for a validated ID or supported URL."""
    return f"https://www.youtube.com/watch?v={parse_video_id(video_id)}"


@dataclass(frozen=True, slots=True)
class ChannelReference:
    """A provider lookup key resolved by ID or handle."""

    kind: Literal["id", "handle"]
    value: str

    @property
    def canonical_url(self) -> str:
        path = f"channel/{self.value}" if self.kind == "id" else quote(self.value, safe="@")
        return f"https://www.youtube.com/{path}"

    @property
    def cache_key(self) -> str:
        value = self.value if self.kind == "id" else self.value.casefold()
        return f"{self.kind}:{value}"

    def provider_arguments(self) -> dict[str, str]:
        key = "channel_id" if self.kind == "id" else "handle"
        return {key: self.value}


def _channel_handle(value: str) -> ChannelReference:
    body = value[1:]
    if _clean_reference(body) != body or any(ch in "/\\?#%@" for ch in body):
        raise ValueError("A handle must be a single nonempty segment starting with @.")
    return ChannelReference("handle", value)


def parse_channel_reference(value: str) -> ChannelReference:
    """Parse an ID, bare handle or channel URL without resolving it over the network."""
    try:
        value = _clean_reference(value)
        if _CHANNEL_ID.fullmatch(value):
            return ChannelReference("id", value)
        if value.startswith("@"):
            return _channel_handle(value)
        url = _youtube_url(value)
        path = url.path.removesuffix("/")
        if path == "/c" or path.startswith("/c/"):
            raise InvalidChannelIdError(
                "Legacy /c/ URLs are unsupported. Provide an @handle or a canonical channel ID.",
                details={"reason": "legacy_custom_url"},
            )
        channel_id = path.removeprefix("/channel/")
        if path.startswith("/channel/") and _CHANNEL_ID.fullmatch(channel_id):
            return ChannelReference("id", channel_id)
        if path.startswith("/@"):
            return _channel_handle(unquote(path[1:], errors="strict"))
        raise ValueError("Use a channel ID, @handle, /channel/ID or /@handle URL.")
    except ValueError as exc:
        raise InvalidChannelIdError(
            "Invalid channel reference. Provide an @handle or a canonical channel ID."
        ) from exc


def parse_playlist_id(value: str) -> str:
    """Return an opaque playlist ID from a bare ID or a supported list URL."""
    try:
        value = _clean_reference(value)
        if _PLAYLIST_ID.fullmatch(value):
            return value
        url = _youtube_url(value, allow_short=True)
        query = parse_qs(url.query, keep_blank_values=True)
        if url.netloc.lower() == _SHORT_HOST:
            parse_video_id(value)
        elif url.path == "/watch":
            if "v" in query:
                parse_video_id(value)
        elif url.path != "/playlist":
            raise ValueError("Use a YouTube playlist URL or a watch URL with a list parameter.")
        playlist_id = _one_query_value(query, "list")
        if _PLAYLIST_ID.fullmatch(playlist_id):
            return playlist_id
        raise ValueError(
            "The playlist ID has an invalid length or contains unsupported characters."
        )
    except InvalidVideoIdError:
        raise InvalidArgumentsError("The video reference in the playlist URL is invalid.") from None
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None


def playlist_url(playlist_id: str) -> str:
    """Produce the canonical listing URL for a validated playlist reference."""
    return f"https://www.youtube.com/playlist?list={parse_playlist_id(playlist_id)}"


def parse_duration_seconds(value: str, *, allow_zero: bool = True) -> int:
    """Parse an ISO-8601 duration whose units have an exact whole-second length."""
    match = _DURATION.fullmatch(value) if isinstance(value, str) and len(value) <= 64 else None
    if match is None or not any(match.groups()) or value.endswith("T"):
        raise InvalidArgumentsError("Provide a whole-second ISO-8601 duration such as PT20M.")
    seconds = sum(int(match[unit] or 0) * size for unit, size in _DURATION_UNITS.items())
    if seconds > _MAX_DURATION or (seconds == 0 and not allow_zero):
        raise InvalidArgumentsError("The duration is outside the allowed range.")
    return seconds


def format_duration_iso(seconds: int) -> str:
    """Format non-negative whole seconds as a canonical ISO-8601 time duration."""
    if type(seconds) is not int or not 0 <= seconds <= _MAX_DURATION:
        raise InvalidArgumentsError("Duration seconds must be a non-negative integer in range.")
    hours, remainder = divmod(seconds, 3600)
    minutes, tail_seconds = divmod(remainder, 60)
    parts = "".join(
        f"{value}{unit}"
        for value, unit in zip((hours, minutes, tail_seconds), "HMS", strict=True)
        if value
    )
    return f"PT{parts or '0S'}"


def parse_utc_datetime(value: str, *, allow_date: bool = False) -> datetime:
    """Parse a zoned wire timestamp or an explicitly permitted UTC calendar date."""
    if isinstance(value, str):
        try:
            if allow_date and _DATE.fullmatch(value):
                return datetime.combine(date.fromisoformat(value), time.min, UTC)
            if _TIMESTAMP.fullmatch(value):
                wire = value[:-1] + "+00:00" if value[-1] in "Zz" else value
                return datetime.fromisoformat(wire).astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    hint = " or YYYY-MM-DD" if allow_date else ""
    raise InvalidArgumentsError(f"Provide an RFC 3339 timestamp with an explicit offset{hint}.")


def normalise_language_tag(value: str | None) -> str | None:
    """Return a case-insensitive modern language tag, or None for unknown language."""
    if not isinstance(value, str) or len(value) > 255:
        return None
    tag = value.strip().lower()
    if _LANGUAGE_TAG.fullmatch(tag) and tag.partition("-")[0] not in {"und", "mul", "mis", "zxx"}:
        return tag
    return None


def primary_language(value: str | None) -> str | None:
    tag = normalise_language_tag(value)
    return tag.partition("-")[0] if tag is not None else None


def same_primary_language(left: str | None, right: str | None) -> bool | None:
    """Return True/False for known languages and None where evidence is missing."""
    left_primary, right_primary = primary_language(left), primary_language(right)
    if left_primary is None or right_primary is None:
        return None
    return left_primary == right_primary


def select_video_language(
    default_audio_language: str | None, default_language: str | None
) -> tuple[str | None, LanguageProvenance]:
    """Prefer a known spoken-language tag, else preserve the metadata-language basis."""
    audio = normalise_language_tag(default_audio_language)
    if audio is not None:
        return audio, "audio"
    metadata = normalise_language_tag(default_language)
    return (metadata, "metadata") if metadata is not None else (None, "unknown")


def _known_utc(value: datetime | None) -> datetime | None:
    if value is None or value.utcoffset() is None:
        return None
    try:
        return value.astimezone(UTC)
    except OverflowError:
        return None


def _optional_text(value: str | None) -> str | None:
    return None if value is None else sanitize_untrusted_text(value)


def _optional_labels(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [clean for value in values if (clean := sanitize_untrusted_text(value))]


def normalise_video_record(record: VideoRecord) -> VideoRecord:
    """Normalise an existing provider record without replacing unknown facts with zero."""
    seconds = record.duration_seconds
    if record.duration_iso is not None:
        try:
            seconds = parse_duration_seconds(record.duration_iso)
        except InvalidArgumentsError:
            pass  # A valid numeric duration supplied independently is still usable.
    if seconds is not None and not 0 <= seconds <= _MAX_DURATION:
        seconds = None
    language = normalise_language_tag(record.language)
    return record.model_copy(
        update={
            "title": sanitize_untrusted_text(record.title),
            "channel_title": sanitize_untrusted_text(record.channel_title),
            "description": _optional_text(record.description),
            "tags": _optional_labels(record.tags),
            "duration_seconds": seconds,
            "duration_iso": format_duration_iso(seconds) if seconds is not None else None,
            "published_at": _known_utc(record.published_at),
            "language": language,
            "language_provenance": record.language_provenance
            if language is not None
            else "unknown",
            "untrusted": True,
        }
    )


def normalise_channel_record(record: ChannelRecord) -> ChannelRecord:
    """Keep an explicitly hidden subscriber count unknown, even when supplied."""
    language = normalise_language_tag(record.language)
    return record.model_copy(
        update={
            "title": sanitize_untrusted_text(record.title),
            "description": _optional_text(record.description),
            "keywords": _optional_labels(record.keywords),
            "language": language,
            "language_provenance": record.language_provenance
            if language is not None
            else "unknown",
            "subscriber_count": None if record.hidden_subscriber_count else record.subscriber_count,
            "untrusted": True,
        }
    )


def normalise_activity_record(record: AccountActivityRecord) -> AccountActivityRecord:
    """Normalise the supplied event or proxy without inferring a missing timestamp."""
    timestamp = _known_utc(record.timestamp)
    return record.model_copy(
        update={
            "timestamp": timestamp,
            "timestamp_provenance": record.timestamp_provenance
            if timestamp is not None
            else "unknown",
        }
    )
