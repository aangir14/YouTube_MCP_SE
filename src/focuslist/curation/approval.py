"""Immutable proposals and verification of an independent human decision."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from focuslist.context import RequestContext
from focuslist.errors import AuthRequiredError, ConfirmationExpiredError, ConfirmationInvalidError
from focuslist.platform.auth import AuthManager
from focuslist.platform.storage import FocusListStorage, StoredProposal
from focuslist.platform.write_contracts import ActionKind, PrivacyStatus

_PROPOSAL_ID = re.compile(r"prop_[0-9a-f]{32}")
_SIGNATURE = re.compile(r"[0-9a-f]{64}")
PROPOSAL_LIFETIME_SECONDS = 30 * 60


class Action(BaseModel):
    """The exact action and its review, authenticated together."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    proposal_id: str
    kind: ActionKind
    owner: str
    provider_mode: str
    grant: str | None = None
    title: str
    privacy: PrivacyStatus
    video_ids: list[str] = Field(max_length=50)
    expires_at: int
    target: str | None = None
    original: str | None = None
    position: int = 0
    description: str = ""
    review: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VerifiedAction:
    record: StoredProposal
    action: Action
    approval_hash: str


class PlaylistApprovals:
    def __init__(
        self, storage: FocusListStorage, auth: AuthManager, context: RequestContext,
    ) -> None:
        self.storage = storage
        self.auth = auth
        self.ctx = context

    def owner(self) -> str:
        if self.ctx.settings.provider != "live":
            return self.ctx.account_id or "fixture_learner"
        status = self.auth.get_status()
        if not status.authenticated or not status.account_id:
            raise AuthRequiredError()
        return status.account_id

    @staticmethod
    def _canonical(action: Action) -> bytes:
        return json.dumps(
            action.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")

    def _mac(self, domain: bytes, data: bytes) -> str:
        key = self.auth.credential_store.get_or_create_signing_key()
        return hmac.new(key, domain + data, hashlib.sha256).hexdigest()

    def issue(
        self,
        kind: ActionKind,
        review: dict[str, Any],
        *,
        title: str,
        privacy: PrivacyStatus,
        video_ids: list[str],
        target: str | None = None,
        original: str | None = None,
        position: int = 0,
    ) -> dict[str, Any]:
        proposal_id = f"prop_{uuid4().hex}"
        owner = self.owner()
        expires_at = self.ctx.clock.now_epoch() + PROPOSAL_LIFETIME_SECONDS
        expiry = datetime.fromtimestamp(expires_at, tz=UTC)
        description = f"FocusList reference: {proposal_id}" if kind == "create" else ""
        display = {
            **review,
            "proposal_id": proposal_id,
            "action_kind": kind,
            "title": title,
            "privacy_status": privacy,
            "ordered_video_ids": video_ids,
            "target_playlist_id": target,
            "start_position": position,
            "expires_at": expiry.isoformat(),
            "writes_executed": 0,
        }
        if kind == "create":
            display["description"] = description
            if self.ctx.settings.provider == "live" and not self.auth.get_status().has_write_scope:
                display["estimated_scope_upgrade_cost"] = 1
        action = Action(
            proposal_id=proposal_id, kind=kind, owner=owner,
            provider_mode=self.ctx.settings.provider, title=title, privacy=privacy,
            grant=self.auth.grant_binding() if self.ctx.settings.provider == "live" else None,
            video_ids=video_ids, expires_at=expires_at, target=target, original=original,
            position=position, description=description, review=display,
        )
        content = self._canonical(action)
        digest = hashlib.sha256(content).hexdigest()
        token = self._mac(b"focuslist proposal v1\0", content)
        stored = self.storage.save_proposal(
            proposal_id=proposal_id, action_kind=kind, owner_account_id=owner,
            title=title, privacy_status=privacy, ordered_video_ids=video_ids,
            target_playlist_id=target, expires_at=expiry, canonical_hash=digest, supersede=True,
            canonical_payload={
                "action": action.model_dump(mode="json"),
                "signature_hash": hashlib.sha256(token.encode()).hexdigest(),
            },
        )
        self.audit(stored, "proposed")
        return {**display, "confirmation_token": token}

    def load(
        self, proposal_id: str, *, token: str | None = None, for_recovery: bool = False,
    ) -> VerifiedAction:
        if not _PROPOSAL_ID.fullmatch(proposal_id):
            raise ConfirmationInvalidError("A current signed proposal ID is required.")
        if token is not None and not _SIGNATURE.fullmatch(token):
            raise ConfirmationInvalidError()
        stored = self.storage.get_proposal(proposal_id)
        if stored is None or stored.owner_account_id != self.owner():
            raise ConfirmationInvalidError()
        try:
            action = Action.model_validate(stored.canonical_payload.get("action"))
            content = self._canonical(action)
        except (ValidationError, ValueError, TypeError):
            raise ConfirmationInvalidError() from None
        if (
            action.proposal_id != stored.proposal_id
            or action.kind != stored.action_kind
            or action.owner != stored.owner_account_id
            or action.provider_mode != self.ctx.settings.provider
            or action.title != stored.title
            or action.privacy != stored.privacy_status
            or action.video_ids != stored.ordered_video_ids
            or action.expires_at != stored.expires_at
            or (action.kind != "create" and action.target != stored.target_playlist_id)
            or not hmac.compare_digest(
                stored.canonical_hash.encode(), hashlib.sha256(content).hexdigest().encode(),
            )
        ):
            raise ConfirmationInvalidError()
        expected = self._mac(b"focuslist proposal v1\0", content)
        seal = stored.canonical_payload.get("signature_hash")
        if not isinstance(seal, str) or not hmac.compare_digest(
            seal.encode(), hashlib.sha256(expected.encode()).hexdigest().encode(),
        ):
            raise ConfirmationInvalidError()
        if token is not None and not hmac.compare_digest(expected, token):
            raise ConfirmationInvalidError()
        if self.ctx.settings.provider == "live":
            expected_grant = stored.authorized_grant or action.grant
            if expected_grant is None or expected_grant != self.auth.grant_binding():
                raise ConfirmationInvalidError("The YouTube authorization used for this action changed.")
        if not for_recovery and stored.state != "completed":
            if stored.state == "expired" or self.ctx.clock.now_epoch() >= action.expires_at:
                raise ConfirmationExpiredError()
            if stored.state != "proposed":
                raise ConfirmationInvalidError("This proposal is no longer available for approval.")
        receipt = self._mac(b"focuslist human decision v1\0", content)
        return VerifiedAction(stored, action, hashlib.sha256(receipt.encode()).hexdigest())

    def record_human_decision(self, reviewed: VerifiedAction, approved: bool) -> None:
        self.storage.record_proposal_decision(
            reviewed.action.proposal_id, reviewed.record.canonical_hash,
            reviewed.approval_hash if approved else None,
        )
        self.audit(reviewed.record, "approved" if approved else "declined")

    def is_approved(self, verified: VerifiedAction) -> bool:
        return self.storage.has_proposal_approval(verified.action.proposal_id, verified.approval_hash)

    def ownership_proof(
        self, target: str, privacy: PrivacyStatus, *, owner: str, grant: str | None,
    ) -> str:
        content = json.dumps([
            target, privacy, owner, self.ctx.settings.provider, grant,
        ], separators=(",", ":")).encode()
        digest = self._mac(b"focuslist created playlist v1\0", content)
        return hashlib.sha256(digest.encode()).hexdigest()

    def audit(self, record: StoredProposal, outcome: str, *, failure: str | None = None) -> None:
        self.storage.append_action_history(
            proposal_id=record.proposal_id, proposal_hash=record.canonical_hash,
            action_kind=record.action_kind, account_id=record.owner_account_id,
            outcome=outcome, inserted_count=record.inserted_count,
            target_playlist_id=record.target_playlist_id, failed_step_code=failure,
        )

    def audit_rejection(self, proposal_id: str, failure: str) -> None:
        record = self.storage.get_proposal(proposal_id) if _PROPOSAL_ID.fullmatch(proposal_id) else None
        try:
            owner = self.owner()
        except AuthRequiredError:
            owner = "unauthenticated"
        if record is not None and record.owner_account_id != owner:
            record = None
        self.storage.append_action_history(
            proposal_id=record.proposal_id if record else None,
            proposal_hash=record.canonical_hash if record else "unknown",
            action_kind="confirm_rejected", account_id=owner, outcome="rejected",
            failed_step_code=failure,
        )
