"""Central tool error registry, domain exceptions, and error envelopes."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable error codes pinned per SRS UI-4, UI-5, COM-4, and Section 3."""

    INVALID_VIDEO_ID = "INVALID_VIDEO_ID"
    INVALID_CHANNEL_ID = "INVALID_CHANNEL_ID"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
    CHANNEL_UNAVAILABLE = "CHANNEL_UNAVAILABLE"
    QUOTA_BUDGET_EXCEEDED = "QUOTA_BUDGET_EXCEEDED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    AUTH_CANCELLED = "AUTH_CANCELLED"
    NO_YOUTUBE_CHANNEL = "NO_YOUTUBE_CHANNEL"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    PARTIALLY_CREATED = "PARTIALLY_CREATED"
    UPSTREAM_FAILURE = "UPSTREAM_FAILURE"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"


# Pinned error specifications: (default_message, remediation, retryable)
ERROR_REGISTRY: dict[ErrorCode, tuple[str, str, bool]] = {
    ErrorCode.INVALID_VIDEO_ID: (
        "The supplied video identifier or URL is invalid.",
        "Provide an 11-character YouTube video ID or a standard watch/short URL.",
        False,
    ),
    ErrorCode.INVALID_CHANNEL_ID: (
        "The supplied channel identifier, handle, or URL is invalid.",
        "Provide a canonical channel ID ('UC...'), handle ('@handle'), or valid channel URL.",
        False,
    ),
    ErrorCode.INVALID_ARGUMENTS: (
        "Tool input arguments failed schema validation.",
        "Check parameter types, string lengths, and required fields against tool schema.",
        False,
    ),
    ErrorCode.VIDEO_UNAVAILABLE: (
        "The requested video is private, deleted, or geographically restricted.",
        "Verify video availability on YouTube or choose an accessible alternative.",
        False,
    ),
    ErrorCode.CHANNEL_UNAVAILABLE: (
        "The requested channel does not exist or has no public content.",
        "Check channel handle or ID for accessibility and public uploads.",
        False,
    ),
    ErrorCode.QUOTA_BUDGET_EXCEEDED: (
        "The requested workflow exceeds the allowable quota allowance or request ceiling.",
        "Reduce candidate limits or target duration, or await daily quota reset at midnight Pacific.",
        False,
    ),
    ErrorCode.QUOTA_EXHAUSTED: (
        "YouTube API daily quota allocation has been completely exhausted.",
        "Operations will resume automatically following the midnight Pacific reset.",
        False,
    ),
    ErrorCode.RATE_LIMITED: (
        "YouTube API rate limit reached due to burst concurrency.",
        "Wait a moment before retrying; requests will back off exponentially.",
        True,
    ),
    ErrorCode.AUTH_REQUIRED: (
        "This tool requires an authenticated Google account with YouTube permissions.",
        "Run 'focuslist auth login' in your terminal to complete authorization.",
        False,
    ),
    ErrorCode.AUTH_EXPIRED: (
        "OAuth credentials have expired, revoked, or encountered invalid_grant.",
        "Run 'focuslist auth login' to re-authenticate with Google.",
        False,
    ),
    ErrorCode.AUTH_CANCELLED: (
        "Consent was cancelled or declined on the Google authentication screen.",
        "Authorize the requested read/write scopes to enable personalized discovery.",
        False,
    ),
    ErrorCode.NO_YOUTUBE_CHANNEL: (
        "The authenticated Google account does not have an active YouTube channel.",
        "Create a YouTube channel for this account at youtube.com to enable playlist creation.",
        False,
    ),
    ErrorCode.CONFIRMATION_INVALID: (
        "The confirmation token or proposal hash does not match the reviewed action.",
        "Obtain a fresh proposal before confirming; proposals cannot be modified once signed.",
        False,
    ),
    ErrorCode.CONFIRMATION_EXPIRED: (
        "The playlist creation proposal has exceeded its 30-minute validity window.",
        "Generate a new proposal with 'propose_playlist' and confirm within 30 minutes.",
        False,
    ),
    ErrorCode.PARTIALLY_CREATED: (
        "Playlist creation partially succeeded but experienced a transient error.",
        "Use the returned proposal ID to resume insertion of remaining items without duplicate creates.",
        True,
    ),
    ErrorCode.UPSTREAM_FAILURE: (
        "YouTube API returned an unexpected upstream server error (500).",
        "Retry the operation after exponential backoff.",
        True,
    ),
    ErrorCode.UPSTREAM_UNAVAILABLE: (
        "YouTube API service is temporarily unavailable or undergoing maintenance (503).",
        "Wait a few moments and retry.",
        True,
    ),
    ErrorCode.NETWORK_TIMEOUT: (
        "The network request timed out after 15 seconds.",
        "Check your network connectivity and retry.",
        True,
    ),
}


class FocusListError(Exception):
    """Base domain exception carrying structured metadata per SRS UI-4."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        remediation: str | None = None,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        default_msg, default_rem, default_ret = ERROR_REGISTRY.get(
            code,
            ("An unexpected error occurred.", "Review logs and retry.", False),
        )
        self.message = message or default_msg
        self.remediation = remediation or default_rem
        self.retryable = retryable if retryable is not None else default_ret
        self.details = details or {}
        super().__init__(f"[{self.code.value}] {self.message}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to stable dictionary matching ErrorInfo schema."""
        res: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "remediation": self.remediation,
            "retryable": self.retryable,
        }
        if self.details:
            res["details"] = self.details
        return res


# Domain Exception Subclasses
class InvalidVideoIdError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.INVALID_VIDEO_ID, message, details=details)


class InvalidChannelIdError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.INVALID_CHANNEL_ID, message, details=details)


class InvalidArgumentsError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.INVALID_ARGUMENTS, message, details=details)


class VideoUnavailableError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.VIDEO_UNAVAILABLE, message, details=details)


class ChannelUnavailableError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.CHANNEL_UNAVAILABLE, message, details=details)


class QuotaBudgetExceededError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.QUOTA_BUDGET_EXCEEDED, message, details=details)


class QuotaExhaustedError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.QUOTA_EXHAUSTED, message, details=details)


class RateLimitedError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.RATE_LIMITED, message, details=details)


class AuthRequiredError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.AUTH_REQUIRED, message, details=details)


class AuthExpiredError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.AUTH_EXPIRED, message, details=details)


class AuthCancelledError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.AUTH_CANCELLED, message, details=details)


class NoYouTubeChannelError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.NO_YOUTUBE_CHANNEL, message, details=details)


class ConfirmationInvalidError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.CONFIRMATION_INVALID, message, details=details)


class ConfirmationExpiredError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.CONFIRMATION_EXPIRED, message, details=details)


class PartiallyCreatedError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.PARTIALLY_CREATED, message, details=details)


class UpstreamFailureError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.UPSTREAM_FAILURE, message, details=details)


class UpstreamUnavailableError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.UPSTREAM_UNAVAILABLE, message, details=details)


class NetworkTimeoutError(FocusListError):
    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.NETWORK_TIMEOUT, message, details=details)
