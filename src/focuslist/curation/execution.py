"""Confirmed playlist mutations and reconciliation-first recovery."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import Any, TypeVar, cast

from focuslist.context import RequestContext
from focuslist.curation.approval import Action, PlaylistApprovals, VerifiedAction
from focuslist.errors import (
    AuthRequiredError,
    ConfirmationInvalidError,
    ErrorCode,
    FocusListError,
    InvalidArgumentsError,
    NoYouTubeChannelError,
)
from focuslist.metadata import parse_playlist_id
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.write_contracts import (
    AmbiguousWriteError,
    PrivacyStatus,
    WriteAuthorizationContext,
)
from focuslist.types import format_duration_display

_T = TypeVar("_T")


class PlaylistExecution:
    def __init__(
        self, approvals: PlaylistApprovals, provider: ProviderGateway,
        *, sleep: Callable[[float], Any] = time.sleep,
        explain_scopes: Callable[[str], None] | None = None,
    ) -> None:
        self.approvals = approvals
        self.provider = provider
        self.storage = approvals.storage
        self.auth = approvals.auth
        self.clock = approvals.ctx.clock
        self.sleep = sleep
        self.explain_scopes = explain_scopes

    def _mutate(self, operation: Callable[[], _T]) -> _T:
        delay = self.storage.next_playlist_write_at() - self.clock.now().timestamp()
        if delay > 0:
            self.sleep(delay)
        self.storage.set_next_playlist_write_at(self.clock.now().timestamp() + 1)
        try:
            return operation()
        finally:
            self.storage.set_next_playlist_write_at(self.clock.now().timestamp() + 1)

    def _preflight_auth(self, action: Action, upgrade: bool) -> tuple[bytes | None, str | None]:
        if action.provider_mode != "live":
            if action.kind == "create" and not self.provider.check_channel_eligibility(action.owner):
                raise NoYouTubeChannelError()
            return None, None

        current = self.auth.ensure_valid_session(require_write=not upgrade)
        if action.grant != self.auth.grant_binding():
            raise AuthRequiredError("The authorized YouTube account changed. Obtain a new proposal.")
        if upgrade:
            previous_channels = self.provider.owned_channel_ids(action.owner)
            if not previous_channels:
                raise NoYouTubeChannelError()
            try:
                self.auth.request_write_consent(
                    confirmed_write_intent=True, explain_callback=self.explain_scopes,
                )
                renewed = self.auth.ensure_valid_session(require_write=True)
                channels = self.provider.owned_channel_ids(action.owner)
                if (
                    not channels or channels != previous_channels
                    or renewed.access_token != self.auth.ensure_valid_session(
                        require_write=True
                    ).access_token
                ):
                    raise AuthRequiredError("Write consent must use the originally approved channel.")
                current = renewed
            except FocusListError:
                self.auth.credential_store.save_credentials(current)
                raise
        elif action.kind == "create" and not self.provider.check_channel_eligibility(action.owner):
            raise NoYouTubeChannelError()
        if current.access_token != self.auth.ensure_valid_session(require_write=True).access_token:
            raise AuthRequiredError("YouTube authorization changed before the write.")
        return hashlib.sha256(current.access_token.encode()).digest(), self.auth.grant_binding()

    def confirm(self, verified: VerifiedAction, token: str, context: RequestContext) -> dict[str, Any]:
        """Reverify after the human turn, reserve quota, and atomically claim."""
        with self.storage.playlist_execution_lock():
            verified = self.approvals.load(verified.action.proposal_id, token=token)
            action, record = verified.action, verified.record
            if record.state == "completed":
                if action.kind == "undo" or record.result is None:
                    raise ConfirmationInvalidError("This action was already used.")
                return record.result
            if not self.approvals.is_approved(verified):
                raise ConfirmationInvalidError("A separate human approval is required.")
            if action.kind != "create" and not self.storage.is_playlist_undo_eligible(
                action.target or "", action.owner,
            ):
                raise ConfirmationInvalidError("This playlist is no longer eligible for the action.")
            upgrade = (
                action.kind == "create" and action.provider_mode == "live"
                and not self.auth.get_status().has_write_scope
            )
            units = 50 * len(action.video_ids)
            if action.kind == "create":
                units += 51 + int(upgrade)
            elif action.kind == "resume":
                units += 1  # Fresh reconciliation before applying the reviewed remainder.
            else:
                units = 50
            with self.provider.operation_budget(units, context=context):
                self.storage.claim_proposal(
                    action.proposal_id, owner_account_id=action.owner,
                    expected_action_kind=action.kind, expected_hash=record.canonical_hash,
                    expected_approval=verified.approval_hash,
                )
                self.approvals.audit(record, "confirmation_claimed")
                try:
                    fingerprint, grant = self._preflight_auth(action, upgrade)
                except FocusListError as exc:
                    self._fail_before_write(action, exc)
                    raise
                self.storage.update_proposal_execution(
                    action.proposal_id, authorized_grant=grant,
                )
                write_context = WriteAuthorizationContext(
                    proposal_id=action.proposal_id, account_id=action.owner, action_kind=action.kind,
                    approved_title=action.title, approved_privacy=action.privacy,
                    approved_video_ids=tuple(action.video_ids), target_playlist_id=action.target,
                    start_position=action.position, credential_fingerprint=fingerprint,
                )
                if action.kind == "undo":
                    assert action.target is not None
                    return self._undo(action, action.target, write_context)
                if action.kind == "create":
                    target = self._create(action, write_context, grant)
                    root = action.proposal_id
                else:
                    assert action.target is not None and action.original is not None
                    root, target = action.original, action.target
                    try:
                        original = self.approvals.load(root, for_recovery=True)
                        if original.record.state == "completed":
                            raise ConfirmationInvalidError("The original creation is already complete.")
                        expected = original.action.video_ids
                        if (
                            original.record.target_playlist_id != target
                            or expected[action.position:] != action.video_ids
                            or self.provider.list_playlist_items_for_reconciliation(target)
                            != expected[:action.position]
                        ):
                            raise ConfirmationInvalidError(
                                "The playlist changed after review. Obtain a fresh resume proposal."
                            )
                    except FocusListError as exc:
                        self._fail_before_write(action, exc)
                        raise
                return self._insert(
                    action, root, target, replace(write_context, target_playlist_id=target),
                )

    def _fail_before_write(self, action: Action, exc: FocusListError) -> None:
        self.storage.update_proposal_execution(
            action.proposal_id, state="invalidated", execution_status="rejected",
            failed_step_code=exc.code.value, audit_outcome="failed",
        )

    def _create(
        self, action: Action, write_context: WriteAuthorizationContext, grant: str | None,
    ) -> str:
        self.storage.update_proposal_execution(action.proposal_id, execution_status="creating")
        try:
            playlist_id = self._mutate(lambda: self.provider.create_playlist(
                action.title, action.description, privacy=action.privacy, write_context=write_context,
            ))
            try:
                target = parse_playlist_id(playlist_id)
            except FocusListError as exc:
                raise AmbiguousWriteError("playlists.insert") from exc
        except AmbiguousWriteError as exc:
            raise self._partial(action.proposal_id, None, "create", exc) from None
        except FocusListError as exc:
            self._fail_before_write(action, exc)
            raise
        self._record_created(action, target, grant)
        return target

    def _record_created(self, action: Action, target: str, grant: str | None) -> None:
        self.storage.update_proposal_execution(
            action.proposal_id, execution_status="inserting", target_playlist_id=target,
            audit_outcome="created", audit_result={
                "privacy": action.privacy,
                "creation_proof": self.approvals.ownership_proof(
                    target, action.privacy, owner=action.owner, grant=grant,
                ),
            },
        )

    def _insert(
        self, action: Action, root: str, target: str, write_context: WriteAuthorizationContext,
    ) -> dict[str, Any]:
        for index, video_id in enumerate(action.video_ids, start=action.position):
            self.storage.record_write_progress(
                proposal_id=root, item_index=index, video_id=video_id, status="pending",
            )
            try:
                item_id = self._mutate(partial(
                    self.provider.insert_playlist_item, target, video_id,
                    position=index, write_context=write_context,
                ))
            except FocusListError as exc:
                self.storage.record_write_progress(
                    proposal_id=root, item_index=index, video_id=video_id,
                    status="ambiguous" if isinstance(exc, AmbiguousWriteError) else "failed",
                )
                error = self._partial(root, target, f"insert_{index + 1}", exc)
                if root != action.proposal_id:
                    self.storage.update_proposal_execution(
                        action.proposal_id, execution_status="partially_created",
                        failed_step_code=exc.code.value, audit_outcome="failed",
                    )
                raise error from None
            self.storage.record_write_progress(
                proposal_id=root, item_index=index, video_id=video_id,
                playlist_item_id=item_id, status="inserted",
            )
            self.storage.update_proposal_execution(
                root, inserted_count=index + 1, audit_outcome="item_inserted",
            )
        return self._complete(
            root, action.proposal_id, target, action.position + len(action.video_ids),
        )

    def _partial(
        self, root: str, target: str | None, step: str, failure: FocusListError,
    ) -> FocusListError:
        outcome = self.storage.update_proposal_execution(
            root, execution_status="partially_created", failed_step_code=failure.code.value,
            audit_outcome="partially_created" if target else "create_unresolved",
        )
        return FocusListError(
            ErrorCode.PARTIALLY_CREATED,
            "Playlist execution stopped. Review the recorded progress before requesting a resume.",
            retryable=False,
            details={
                "proposal_id": root, "playlist_id": target, "playlist_url": _playlist_url(target),
                "failed_step": step, "failure_code": failure.code.value,
                "inserted_count": outcome.inserted_count,
                "ambiguous": isinstance(failure, AmbiguousWriteError),
                "next_tool": "resume_playlist",
            },
        )

    def _complete(self, root: str, current: str, target: str, count: int) -> dict[str, Any]:
        root_result = {
            "status": "CREATED", "playlist_id": target, "playlist_url": _playlist_url(target),
            "item_count": count,
        }
        self.storage.update_proposal_execution(
            root, state="completed", execution_status="completed",
            inserted_count=count, result=root_result, audit_outcome="completed",
        )
        if current == root:
            return root_result
        resumed_result = {**root_result, "status": "RESUMED"}
        self.storage.update_proposal_execution(
            current, state="completed", execution_status="completed", inserted_count=count,
            result=resumed_result, audit_outcome="resumed",
        )
        return resumed_result

    def _undo(
        self, action: Action, target: str, write_context: WriteAuthorizationContext,
    ) -> dict[str, Any]:
        self.storage.update_proposal_execution(
            action.proposal_id, execution_status="deleting", audit_outcome="undo_started",
        )
        try:
            deleted = self._mutate(lambda: self.provider.delete_playlist(
                target, write_context=write_context,
            ))
            if not deleted:
                raise AmbiguousWriteError("playlists.delete", playlist_id=target)
        except FocusListError as exc:
            self.storage.update_proposal_execution(
                action.proposal_id, state="invalidated", execution_status="delete_failed",
                failed_step_code=exc.code.value,
                audit_outcome="undo_unresolved" if isinstance(exc, AmbiguousWriteError) else "undo_rejected",
            )
            raise
        result = {"status": "UNDONE", "playlist_id": target}
        self.storage.update_proposal_execution(
            action.proposal_id, state="completed", execution_status="undone",
            result=result, audit_outcome="undone",
        )
        return result

    def propose_resume(self, proposal_id: str, context: RequestContext) -> dict[str, Any]:
        with self.storage.playlist_execution_lock():
            original = self.approvals.load(proposal_id, for_recovery=True)
            action, record = original.action, original.record
            if action.kind != "create" or record.state != "confirmed" or record.execution_status not in {
                "creating", "inserting", "partially_created",
            }:
                raise ConfirmationInvalidError("Only an interrupted original creation can be resumed.")
            target = record.target_playlist_id
            if target is not None and not self.storage.is_playlist_undo_eligible(target, action.owner):
                raise ConfirmationInvalidError("The stored playlist is no longer eligible for recovery.")
            with self.provider.operation_budget(1 if target else 2, context=context):
                if target is None:
                    target = self.provider.find_created_playlist(
                        action.title, action.description, action.privacy,
                    )
                    if target is None:
                        raise ConfirmationInvalidError(
                            "The remote creation could not be verified. No mutation will be retried."
                        )
                    target = parse_playlist_id(target)
                    self._record_created(action, target, record.authorized_grant)
                remote = self.provider.list_playlist_items_for_reconciliation(target)
            count = self._reconcile_progress(original, remote)
            if count == len(action.video_ids):
                return self._complete(action.proposal_id, action.proposal_id, target, count)
            items = action.review["items"][count:]
            remaining = action.video_ids[count:]
            seconds = sum(item["duration_seconds"] for item in items)
            return self.approvals.issue(
                "resume", {
                    "status": "PROPOSED", "items": items, "item_count": len(remaining),
                    "total_duration": format_duration_display(seconds),
                    "total_duration_seconds": seconds, "estimated_write_cost": 50 * len(remaining),
                    "estimated_reconciliation_cost": 1,
                },
                title=action.title, privacy=action.privacy, video_ids=remaining, target=target,
                original=action.proposal_id, position=count,
            )

    def _reconcile_progress(self, original: VerifiedAction, remote: list[str]) -> int:
        action = original.action
        progress = self.storage.get_write_progress(action.proposal_id)
        inserted = [step.video_id for step in progress if step.status == "inserted"]
        count = len(inserted)
        if remote[:count] != inserted or remote != action.video_ids[:len(remote)]:
            raise ConfirmationInvalidError("Remote playlist and recorded progress do not match.")
        if len(remote) > count:
            if (
                len(remote) != count + 1 or len(progress) <= count
                or progress[count].item_index != count or progress[count].video_id != remote[count]
                or progress[count].status not in {"pending", "ambiguous"}
            ):
                raise ConfirmationInvalidError("Remote playlist contains an unrecorded change.")
            self.storage.record_write_progress(
                proposal_id=action.proposal_id, item_index=count,
                video_id=remote[count], status="inserted",
            )
            count += 1
        elif any(step.status in {"pending", "ambiguous"} for step in progress):
            raise ConfirmationInvalidError(
                "An interrupted insertion is still unverified. No mutation will be retried."
            )
        self.storage.update_proposal_execution(
            action.proposal_id, inserted_count=count, audit_outcome="reconciled",
        )
        return count

    def propose_undo(self, playlist_id: str) -> dict[str, Any]:
        target = parse_playlist_id(playlist_id)
        owner = self.approvals.owner()
        grant = self.auth.grant_binding() if self.approvals.ctx.settings.provider == "live" else None
        with self.storage.playlist_execution_lock():
            if self.storage.is_playlist_undo_eligible(target, owner):
                for entry in reversed(self.storage.list_action_history(account_id=owner)):
                    if (entry.target_playlist_id != target or entry.action_kind != "create"
                            or entry.outcome != "created" or not entry.proposal_id or not entry.result):
                        continue
                    privacy = entry.result.get("privacy")
                    proof = entry.result.get("creation_proof")
                    if privacy in ("private", "unlisted", "public") and isinstance(proof, str):
                        visibility = cast(PrivacyStatus, privacy)
                        expected = self.approvals.ownership_proof(
                            target, visibility, owner=owner, grant=grant,
                        )
                        if not hmac.compare_digest(expected.encode(), proof.encode()):
                            continue
                        original = self.storage.get_proposal(entry.proposal_id)
                        title = f"Playlist {target}"
                        if original is not None:
                            title = self.approvals.load(entry.proposal_id, for_recovery=True).action.title
                        return self.approvals.issue(
                            "undo", {"status": "PROPOSED", "estimated_write_cost": 50},
                            title=title, privacy=visibility, video_ids=[], target=target,
                            original=entry.proposal_id,
                        )
        raise InvalidArgumentsError(
            "Only a verified FocusList-created playlist within retention is eligible for undo.",
            details={"reason": "undo_ineligible", "writes_executed": 0},
        )


def _playlist_url(target: str | None) -> str | None:
    return f"https://www.youtube.com/playlist?list={target}" if target else None
