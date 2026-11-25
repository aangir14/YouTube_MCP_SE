"""Shared data models, records, and response envelopes for FocusList."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

LanguageProvenance = Literal["audio", "metadata", "public_uploads", "unknown"]


def sanitize_untrusted_text(text: str | None, max_length: int = 500) -> str:
    """Sanitize untrusted YouTube text: strip control chars and zero-width spaces, and truncate."""
    if not text:
        return ""
    cleaned = "".join(
        char for char in text if unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    ).strip()
    if len(cleaned) > max_length:
        if max_length <= 3:
            return cleaned[:max(0, max_length)]
        return cleaned[:max_length - 3].rstrip() + "..."
    return cleaned


def format_duration_display(seconds: int) -> str:
    """Format integer seconds into human-readable display string (mm:ss or h:mm:ss per UI-5)."""
    seconds = max(seconds, 0)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# ==============================================================================
# Domain Record Models
# ==============================================================================


class VideoRecord(BaseModel):
    """Canonical video metadata record."""

    model_config = ConfigDict(extra="ignore")

    video_id: str = Field(description="Canonical 11-character YouTube video ID")
    canonical_url: str = Field(description="Canonical watch URL")
    title: str = Field(description="Sanitized video title")
    channel_id: str = Field(description="Owning channel ID")
    channel_title: str = Field(description="Sanitized owning channel name")
    description: str | None = Field(default=None, description="Untrusted description excerpt")
    published_at: datetime | None = Field(default=None, description="UTC publication timestamp")
    duration_seconds: int | None = Field(default=None, ge=0, description="Known duration in seconds")
    duration_iso: str | None = Field(default=None, description="Known ISO-8601 duration on wire")
    tags: list[str] | None = Field(default=None, description="Sanitized video tags when supplied")
    category_id: str | None = Field(default=None, description="YouTube numeric category ID")
    language: str | None = Field(default=None, description="BCP-47 language tag")
    language_provenance: LanguageProvenance = "unknown"
    visibility: Literal["public", "unlisted", "private"] | None = None
    is_live: bool | None = Field(default=None, description="True if currently live broadcast")
    is_upcoming: bool | None = Field(default=None, description="True if scheduled upcoming broadcast")
    is_age_restricted: bool | None = Field(default=None, description="True if marked age restricted")
    has_captions: bool | None = Field(default=None, description="True if captions are present")
    view_count: int | None = Field(default=None, ge=0, description="Public view count")
    like_count: int | None = Field(default=None, ge=0, description="Public like count")
    untrusted: bool = Field(default=True, description="Marker indicating external metadata")

    @property
    def duration_display(self) -> str | None:
        if self.duration_seconds is None:
            return None
        return format_duration_display(self.duration_seconds)


class ChannelRecord(BaseModel):
    """Canonical channel metadata record."""

    model_config = ConfigDict(extra="ignore")

    channel_id: str = Field(description="Canonical YouTube channel ID ('UC...')")
    canonical_url: str = Field(description="Canonical channel URL")
    title: str = Field(description="Sanitized channel title")
    handle: str | None = Field(default=None, description="Channel @handle if present")
    description: str | None = Field(default=None, description="Untrusted channel description")
    keywords: list[str] | None = None
    language: str | None = None
    language_provenance: LanguageProvenance = "unknown"
    topic_categories: list[str] = Field(default_factory=list, description="Topic taxonomy URLs")
    subscriber_count: int | None = Field(default=None, ge=0, description="Subscriber count")
    video_count: int | None = Field(default=None, ge=0, description="Total video count")
    recent_upload_ids: list[str] = Field(default_factory=list, description="IDs of recent uploads")
    hidden_subscriber_count: bool = Field(default=False, description="True if count is private")
    untrusted: bool = Field(default=True, description="Marker indicating external metadata")


class AccountActivityRecord(BaseModel):
    """Personalized user activity event (likes, subscriptions, playlist items)."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(description="Associated video ID or channel ID")
    activity_type: Literal["like", "subscription", "playlist_entry"]
    account_id: str = Field(description="Scoped authorized user account ID")
    timestamp: datetime | None = Field(default=None, description="Event occurrence timestamp")
    timestamp_provenance: Literal["genuine", "publication_fallback", "unknown"] = "unknown"
    channel_id: str | None = Field(default=None, description="Channel ID associated with event")


class RankedItemRecord(BaseModel):
    """Scored item in a similarity or recommendation result set."""

    model_config = ConfigDict(extra="ignore")

    item_id: str
    title: str
    score: float = Field(ge=0.0, le=1.0, description="Normalized score [0.0, 1.0]")
    rank: int = Field(ge=1, description="1-based rank position")
    reason: str = Field(description="Deterministic reason explanation (<=200 chars)")
    components: dict[str, float] = Field(default_factory=dict, description="Factor weights")
    shared_terms: list[str] = Field(default_factory=list, description="Shared TF-IDF terms (<=5)")
    missing_fields: list[str] = Field(default_factory=list, description="Missing attribute names")
    low_confidence: bool = Field(
        default=False, description="True if sparse metadata lowered confidence"
    )


class ProposalRecord(BaseModel):
    """Immutable playlist proposal record requiring separate confirmation."""

    model_config = ConfigDict(extra="ignore")

    proposal_id: str = Field(description="Unique UUID identifying the proposal")
    action_kind: Literal["create", "resume", "undo"] = "create"
    title: str = Field(description="Proposed playlist title")
    ordered_video_ids: list[str] = Field(description="Deterministic sequence of video IDs")
    total_duration_seconds: int = Field(ge=0, description="Summed runtime in seconds")
    item_count: int = Field(ge=0, description="Number of items in proposed list")
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    estimated_units: int = Field(ge=0, description="Projected write quota units")
    expires_at: datetime = Field(description="Expiration timestamp (default 30 min)")
    canonical_hash: str = Field(description="SHA-256 hash of canonical action content")
    token: str = Field(description="HMAC-SHA-256 signature binding the proposal")
    state: Literal["proposed", "confirmed", "completed", "expired", "invalidated"] = "proposed"
    constraint_status: dict[str, Any] = Field(
        default_factory=dict, description="Constraint validation report"
    )


class QuotaStatusRecord(BaseModel):
    """Local ledger snapshot of quota consumption and remaining allowances."""

    model_config = ConfigDict(extra="ignore")

    pacific_date: str = Field(description="Current Pacific Date (YYYY-MM-DD)")
    units_used: int = Field(ge=0, description="General units used today")
    units_remaining: int = Field(ge=0, description="General units available today")
    searches_used: int = Field(ge=0, description="Search calls used today")
    searches_remaining: int = Field(ge=0, description="Search calls available today")
    cache_hits: int = Field(ge=0, description="Number of zero-quota cache hits")
    is_exhausted: bool = Field(default=False, description="True if budget is depleted")
    reset_time_utc: datetime = Field(description="UTC timestamp of next midnight Pacific rollover")


# ==============================================================================
# Common Response Envelopes (SRS COM-1 to COM-4, UI-4, UI-5)
# ==============================================================================


class MetaEnvelope(BaseModel):
    """Standard metadata block attached to all tool responses."""

    model_config = ConfigDict(extra="ignore")

    quota_used: int = Field(default=0, ge=0, description="Quota units consumed by this invocation")
    quota_remaining: int = Field(default=10000, ge=0, description="Remaining daily quota units")
    cache_hits: int = Field(default=0, ge=0, description="Number of items served from cache")
    provider: str = Field(
        default="fixture", description="Active provider name ('fixture', 'live', 'fault')"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Operational warnings or low-confidence notices"
    )


class ResultEnvelope(BaseModel):
    """Top-level success envelope returning result payload and operational metadata."""

    model_config = ConfigDict(extra="ignore")

    result: Any = Field(description="Tool-specific structured result payload")
    meta: MetaEnvelope = Field(default_factory=MetaEnvelope, description="Operational metadata")


class ErrorInfo(BaseModel):
    """Structured error descriptor fulfilling SRS UI-4."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(description="Stable error code from ErrorCode enum")
    message: str = Field(description="Human-readable safe error message")
    remediation: str = Field(description="Actionable guidance to resolve the failure")
    retryable: bool = Field(description="True if the request may succeed on retry")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional context")


class ErrorEnvelope(BaseModel):
    """Top-level failure envelope returning structured error and operational metadata."""

    model_config = ConfigDict(extra="ignore")

    error: ErrorInfo = Field(description="Structured error descriptor")
    meta: MetaEnvelope = Field(default_factory=MetaEnvelope, description="Operational metadata")
