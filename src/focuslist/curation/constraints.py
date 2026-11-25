"""Proposal argument schema and local constraint validation for playlist curation (C12)."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from focuslist.errors import InvalidArgumentsError
from focuslist.metadata import (
    format_duration_iso,
    normalise_language_tag,
    parse_duration_seconds,
    parse_video_id,
)
from focuslist.types import sanitize_untrusted_text

DEFAULT_MIN_ITEM_DURATION_SECONDS = 120
DEFAULT_TOLERANCE = 0.05
DEFAULT_MAX_ITEMS = 30
HARD_MAX_ITEMS = 50
MAX_TOLERANCE = 0.25


def _parse_positive_duration(value: str | int, *, field_name: str, allow_zero: bool = False) -> int:
    """Parse an ISO-8601 duration string or strict integer seconds."""
    if isinstance(value, bool):
        raise InvalidArgumentsError(f"{field_name} must be an ISO-8601 duration or integer seconds.")
    if isinstance(value, int):
        if value < 0 or (value == 0 and not allow_zero):
            raise InvalidArgumentsError(f"{field_name} must be a positive number of seconds.")
        return value
    if isinstance(value, str):
        return parse_duration_seconds(value, allow_zero=allow_zero)
    raise InvalidArgumentsError(f"{field_name} must be an ISO-8601 duration string or integer.")


class PlaylistProposalRequest(BaseModel):
    """Strict validated input schema for propose_playlist (FR-5.1–5.3, FR-5.15)."""

    model_config = ConfigDict(extra="forbid", strict=False)

    topic: str = Field(description="Learning topic (1–200 characters)")
    target_duration: str | int = Field(description="Target total duration (ISO-8601 or seconds)")
    max_item_duration: str | int = Field(description="Maximum video duration (ISO-8601 or seconds)")
    min_item_duration: str | int = Field(
        default="PT2M", description="Minimum video duration (default PT2M / 120s)"
    )
    language: str = Field(default="en", description="Primary BCP-47 language code (default 'en')")
    allow_unknown_language: bool = Field(
        default=False, description="Allow videos with unknown language (flagged in proposal)"
    )
    allow_age_restricted: bool = Field(
        default=False, description="Allow age-restricted videos (excluded by default)"
    )
    tolerance: float = Field(
        default=DEFAULT_TOLERANCE,
        ge=0.0,
        le=MAX_TOLERANCE,
        description="Allowed fractional duration tolerance around target (default 0.05)",
    )
    max_items: int = Field(
        default=DEFAULT_MAX_ITEMS,
        ge=1,
        le=HARD_MAX_ITEMS,
        description="Maximum number of items (default 30, hard max 50)",
    )
    seed: str | None = Field(default=None, description="Optional seed YouTube video ID or URL")
    ordering: Literal["learning_path", "relevance", "chronological"] = Field(
        default="learning_path", description="Playlist ordering mode"
    )
    title: str | None = Field(default=None, description="Optional custom playlist title")
    privacy_status: Literal["private", "unlisted", "public"] = Field(
        default="private", description="Playlist visibility (default private)"
    )
    session_minutes: int | None = Field(
        default=None, ge=1, le=480, description="Optional study session length in minutes"
    )

    @field_validator("topic", mode="before")
    @classmethod
    def _validate_topic(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("topic must be a string between 1 and 200 characters.")
        cleaned = value.strip()
        if not 1 <= len(cleaned) <= 200:
            raise ValueError("topic must be between 1 and 200 non-whitespace characters.")
        return cleaned

    @field_validator("language", mode="before")
    @classmethod
    def _validate_language(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("language must be a valid BCP-47 language tag (e.g. 'en').")
        tag = normalise_language_tag(value)
        if tag is None:
            raise ValueError("language must be a valid known BCP-47 language tag (e.g. 'en').")
        return tag

    @field_validator("max_items", mode="before")
    @classmethod
    def _validate_max_items_strict_int(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("max_items must be an integer between 1 and 50.")
        return value

    @field_validator("session_minutes", mode="before")
    @classmethod
    def _validate_session_minutes_strict_int(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("session_minutes must be a positive integer.")
        return value

    @field_validator("tolerance", mode="before")
    @classmethod
    def _validate_tolerance(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("tolerance must be a finite number between 0.0 and 0.25.")
        val = float(value)
        if not math.isfinite(val):
            raise ValueError("tolerance must be finite.")
        return val

    @field_validator("seed", mode="before")
    @classmethod
    def _validate_seed(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("seed must be a valid YouTube video ID or URL.")
        return parse_video_id(value)

    @field_validator("title", mode="before")
    @classmethod
    def _validate_title(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("title must be a string.")
        cleaned = sanitize_untrusted_text(value, max_length=100)
        if not cleaned:
            raise ValueError("title cannot be empty when supplied.")
        return cleaned

    @model_validator(mode="after")
    def _validate_cross_constraints(self) -> PlaylistProposalRequest:
        target_sec = _parse_positive_duration(
            self.target_duration, field_name="target_duration", allow_zero=False
        )
        max_sec = _parse_positive_duration(
            self.max_item_duration, field_name="max_item_duration", allow_zero=False
        )
        min_sec = _parse_positive_duration(
            self.min_item_duration, field_name="min_item_duration", allow_zero=True
        )
        if min_sec > max_sec:
            raise ValueError(
                f"min_item_duration ({min_sec}s) cannot exceed max_item_duration ({max_sec}s)."
            )
        target_upper = math.floor(target_sec * (1.0 + self.tolerance))
        if min_sec > target_upper:
            raise ValueError(
                f"min_item_duration ({min_sec}s) exceeds maximum allowed target duration "
                f"({target_upper}s)."
            )
        return self

    def to_constraints(self) -> ValidatedPlaylistConstraints:
        """Convert validated request into normalized integer-second constraints."""
        target_sec = _parse_positive_duration(
            self.target_duration, field_name="target_duration", allow_zero=False
        )
        max_sec = _parse_positive_duration(
            self.max_item_duration, field_name="max_item_duration", allow_zero=False
        )
        min_sec = _parse_positive_duration(
            self.min_item_duration, field_name="min_item_duration", allow_zero=True
        )
        target_lower = math.ceil(target_sec * (1.0 - self.tolerance))
        target_upper = math.floor(target_sec * (1.0 + self.tolerance))
        return ValidatedPlaylistConstraints(
            topic=self.topic,
            target_duration_seconds=target_sec,
            target_lower_seconds=target_lower,
            target_upper_seconds=target_upper,
            max_item_duration_seconds=max_sec,
            min_item_duration_seconds=min_sec,
            language=self.language,
            allow_unknown_language=self.allow_unknown_language,
            allow_age_restricted=self.allow_age_restricted,
            tolerance=self.tolerance,
            max_items=self.max_items,
            seed_video_id=self.seed,
            ordering=self.ordering,
            title=self.title,
            privacy_status=self.privacy_status,
            session_minutes=self.session_minutes,
        )


class ValidatedPlaylistConstraints(BaseModel):
    """Normalized curation constraints with integer-second bounds."""

    model_config = ConfigDict(frozen=True)

    topic: str
    target_duration_seconds: int
    target_lower_seconds: int
    target_upper_seconds: int
    max_item_duration_seconds: int
    min_item_duration_seconds: int
    language: str
    allow_unknown_language: bool = False
    allow_age_restricted: bool = False
    tolerance: float = DEFAULT_TOLERANCE
    max_items: int = DEFAULT_MAX_ITEMS
    seed_video_id: str | None = None
    ordering: Literal["learning_path", "relevance", "chronological"] = "learning_path"
    title: str | None = None
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    session_minutes: int | None = None

    @property
    def target_duration_iso(self) -> str:
        return format_duration_iso(self.target_duration_seconds)

    @property
    def max_item_duration_iso(self) -> str:
        return format_duration_iso(self.max_item_duration_seconds)


def validate_proposal_arguments(raw: dict[str, Any]) -> ValidatedPlaylistConstraints:
    """Validate raw tool arguments and raise InvalidArgumentsError on any violation."""
    if not isinstance(raw, dict):
        raise InvalidArgumentsError("Playlist proposal arguments must be a JSON object.")
    try:
        req = PlaylistProposalRequest(**raw)
    except InvalidArgumentsError:
        raise
    except TypeError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    except ValidationError as exc:
        errors = exc.errors()
        first = errors[0] if errors else {"msg": "Invalid proposal arguments."}
        loc = ".".join(str(part) for part in first.get("loc", ()))
        msg = first.get("msg", "Validation failed.")
        detail = f"{loc}: {msg}" if loc else msg
        raise InvalidArgumentsError(detail, details={"validation_errors": len(errors)}) from None
    return req.to_constraints()
