"""Reusable write authorization, ambiguity, and reconciliation contracts for C18 (C16)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from focuslist.errors import ErrorCode, FocusListError

PrivacyStatus = Literal["private", "unlisted", "public"]
ActionKind = Literal["create", "resume", "undo"]


@dataclass(frozen=True, slots=True)
class WriteAuthorizationContext:
    """Verified approval context required before LiveVideoProvider executes any playlist write.

    Constructed exclusively after C18 verifies proposal hash, HMAC-SHA-256 signature,
    expiration, unused claim state, account match, and explicit human confirmation.
    """

    proposal_id: str
    account_id: str
    action_kind: ActionKind
    approved_title: str
    approved_privacy: PrivacyStatus = "private"
    approved_video_ids: tuple[str, ...] = ()
    target_playlist_id: str | None = None
    verified_by: str = "c18_confirmation_gate"

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.account_id:
            raise ValueError("WriteAuthorizationContext requires proposal_id and account_id.")
        if self.approved_privacy not in {"private", "unlisted", "public"}:
            raise ValueError(f"Unsupported privacy status: {self.approved_privacy}")
        if self.action_kind in {"resume", "undo"} and not self.target_playlist_id:
            raise ValueError(f"Action kind '{self.action_kind}' requires target_playlist_id.")


class AmbiguousWriteError(FocusListError):
    """Raised when a mutation encounters a timeout or uncertain upstream outcome.

    C18 must reconcile account playlist state before issuing any resume or retry
    to guarantee zero duplicate playlist creations or duplicate item insertions.
    """

    def __init__(
        self,
        operation: str,
        *,
        playlist_id: str | None = None,
        video_id: str | None = None,
        position: int | None = None,
        message: str | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "ambiguous": True,
            "operation": operation,
            "reconcile_required": True,
        }
        if playlist_id is not None:
            details["playlist_id"] = playlist_id
        if video_id is not None:
            details["video_id"] = video_id
        if position is not None:
            details["position"] = position

        super().__init__(
            code=ErrorCode.NETWORK_TIMEOUT,
            message=message
            or (
                f"YouTube write '{operation}' timed out or returned an ambiguous outcome; "
                "reconcile playlist state before retrying."
            ),
            remediation=(
                "Reconcile account playlist state before resuming; do not blindly replay this write."
            ),
            retryable=False,
            details=details,
        )


@dataclass(frozen=True, slots=True)
class WriteOperationResult:
    """Normalized outcome of a bounded playlist mutation for C18 orchestration."""

    operation: Literal["create_playlist", "insert_playlist_item", "delete_playlist"]
    status: Literal["succeeded", "ambiguous", "rejected"]
    playlist_id: str | None = None
    playlist_item_id: str | None = None
    video_id: str | None = None
    position: int | None = None
    privacy_status: PrivacyStatus | None = None
    quota_units_charged: int = 0
    error_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
