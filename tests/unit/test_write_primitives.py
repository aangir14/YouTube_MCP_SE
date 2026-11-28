"""Unit and integration tests for Workstream 4: bounded playlist write primitives (C16)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from googleapiclient.errors import HttpError

from focuslist.clock import FakeClock
from focuslist.config import Settings
from focuslist.errors import (
    AuthRequiredError,
    InvalidArgumentsError,
    NoYouTubeChannelError,
    QuotaExhaustedError,
)
from focuslist.platform.auth import READONLY_SCOPE, WRITE_SCOPE
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.live_provider import LiveVideoProvider
from focuslist.platform.storage import FocusListStorage
from focuslist.platform.write_contracts import AmbiguousWriteError, WriteAuthorizationContext


class _FakeResp:
    def __init__(self, status: int, reason: str = "") -> None:
        self.status = status
        self.reason = reason


class _FakeReq:
    def __init__(self, payload: Any = None, exc: Exception | None = None) -> None:
        self._payload = payload
        self._exc = exc

    def execute(self) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._payload


class _FakeWriteService:
    def __init__(self) -> None:
        self.playlist_inserts: list[dict[str, Any]] = []
        self.playlist_deletes: list[dict[str, Any]] = []
        self.item_inserts: list[dict[str, Any]] = []
        self.channel_items: list[dict[str, Any]] = [{"id": "UC_own_001"}]
        self.forced_exc: Exception | None = None

    def channels(self) -> Any:
        svc = self

        class _EP:
            def list(self, **kwargs: Any) -> _FakeReq:
                if svc.forced_exc is not None:
                    return _FakeReq(exc=svc.forced_exc)
                return _FakeReq(payload={"items": svc.channel_items})

        return _EP()

    def playlists(self) -> Any:
        svc = self

        class _EP:
            def insert(self, **kwargs: Any) -> _FakeReq:
                svc.playlist_inserts.append(kwargs)
                if svc.forced_exc is not None:
                    return _FakeReq(exc=svc.forced_exc)
                return _FakeReq(payload={"id": "PL_live_001"})

            def delete(self, **kwargs: Any) -> _FakeReq:
                svc.playlist_deletes.append(kwargs)
                if svc.forced_exc is not None:
                    return _FakeReq(exc=svc.forced_exc)
                return _FakeReq(payload={})

        return _EP()

    def playlistItems(self) -> Any:
        svc = self

        class _EP:
            def insert(self, **kwargs: Any) -> _FakeReq:
                svc.item_inserts.append(kwargs)
                if svc.forced_exc is not None:
                    return _FakeReq(exc=svc.forced_exc)
                idx = len(svc.item_inserts)
                return _FakeReq(payload={"id": f"PLI_live_{idx:03d}"})

            def list(self, **kwargs: Any) -> _FakeReq:
                return _FakeReq(payload={"items": [{"contentDetails": {"videoId": "vid_0000001"}}]})

        return _EP()


class _FakeCreds:
    def __init__(self, scopes: list[str]) -> None:
        self.scopes = scopes


def _http_error(status: int, reason: str) -> HttpError:
    body = json.dumps({"error": {"code": status, "errors": [{"reason": reason}]}}).encode("utf-8")
    return HttpError(_FakeResp(status, reason), body)


@pytest.mark.parametrize("visibility", ["private", "unlisted", "public"])
def test_live_write_primitives_enforce_stored_visibility_positions_and_charging(
    tmp_path, visibility: str
) -> None:
    """Verify exact create, positioned insert, delete, and 50-unit attempt accounting."""
    clock = FakeClock()
    storage = FocusListStorage(tmp_path / "writes.db", clock=clock)
    svc = _FakeWriteService()
    live = LiveVideoProvider(
        settings=Settings(provider="live", db_path=tmp_path / "writes.db"),
        service=svc,
        credentials=_FakeCreds([READONLY_SCOPE, WRITE_SCOPE]),
    )
    gateway = ProviderGateway(live, storage=storage, clock=clock, sleep_fn=lambda _: None)

    assert gateway.check_channel_eligibility("acc_1") is True  # 1 unit

    create_ctx = WriteAuthorizationContext(
        proposal_id="prop_1",
        account_id="acc_1",
        action_kind="create",
        approved_title="Approved Algorithms List",
        approved_privacy=visibility,  # type: ignore[arg-type]
        approved_video_ids=("vid_0000001", "vid_0000002"),
    )
    # Provider receives ONLY stored approved title and visibility, ignoring caller override
    pid = gateway.create_playlist(
        "Unapproved Title Override",
        "Created by FocusList",
        privacy="public" if visibility == "private" else "private",
        write_context=create_ctx,
    )
    assert pid == "PL_live_001"
    assert svc.playlist_inserts[0]["body"]["snippet"]["title"] == "Approved Algorithms List"
    assert svc.playlist_inserts[0]["body"]["status"]["privacyStatus"] == visibility

    item1 = gateway.insert_playlist_item(pid, "vid_0000001", position=0, write_context=create_ctx)
    item2 = gateway.insert_playlist_item(pid, "vid_0000002", position=1, write_context=create_ctx)
    assert item1 == "PLI_live_001"
    assert item2 == "PLI_live_002"
    assert svc.item_inserts[0]["body"]["snippet"]["position"] == 0
    assert svc.item_inserts[1]["body"]["snippet"]["position"] == 1

    undo_ctx = WriteAuthorizationContext(
        proposal_id="prop_undo_1",
        account_id="acc_1",
        action_kind="undo",
        approved_title="Approved Algorithms List",
        approved_privacy=visibility,  # type: ignore[arg-type]
        target_playlist_id=pid,
    )
    assert gateway.delete_playlist(pid, write_context=undo_ctx) is True
    assert svc.playlist_deletes == [{"id": pid}]

    # 1 (channel check) + 50 (create) + 50*2 (inserts) + 50 (delete) = 201 units
    assert gateway.quota_manager.get_status().general_units_used == 201
    assert gateway.writes == 4


def test_live_write_requires_context_and_write_scope() -> None:
    """Missing WriteAuthorizationContext or read-only token must fail closed before API call."""
    svc = _FakeWriteService()
    live_ro = LiveVideoProvider(service=svc, credentials=_FakeCreds([READONLY_SCOPE]))

    with pytest.raises(AuthRequiredError):
        live_ro.create_playlist("T", "D")
    assert svc.playlist_inserts == []

    ctx = WriteAuthorizationContext(
        proposal_id="prop_1",
        account_id="acc_1",
        action_kind="create",
        approved_title="T",
    )
    with pytest.raises(AuthRequiredError, match="write scope"):
        live_ro.create_playlist("T", "D", write_context=ctx)
    assert svc.playlist_inserts == []


def test_live_write_error_mappings_and_ambiguous_timeout_no_duplicate_retry(tmp_path) -> None:
    """Test missing channel, insufficient perm, quota exhaustion, and ambiguous timeout."""
    clock = FakeClock()
    storage = FocusListStorage(tmp_path / "errs.db", clock=clock)
    svc = _FakeWriteService()
    live = LiveVideoProvider(service=svc, credentials=_FakeCreds([READONLY_SCOPE, WRITE_SCOPE]))
    gateway = ProviderGateway(live, storage=storage, clock=clock, sleep_fn=lambda _: None)

    # Empty channel list -> NO_YOUTUBE_CHANNEL on require_channel_eligibility
    svc.channel_items = []
    with pytest.raises(NoYouTubeChannelError):
        live.require_channel_eligibility("acc_1")

    # Upstream youtubeSignupRequired -> NO_YOUTUBE_CHANNEL
    svc.forced_exc = _http_error(403, "youtubeSignupRequired")
    with pytest.raises(NoYouTubeChannelError):
        live.check_channel_eligibility("acc_1")

    create_ctx = WriteAuthorizationContext(
        proposal_id="p1",
        account_id="acc_1",
        action_kind="create",
        approved_title="Study",
        approved_video_ids=("vid_1",),
    )

    # Insufficient permission (403 forbidden) -> AuthRequiredError
    svc.forced_exc = _http_error(403, "insufficientPermissions")
    with pytest.raises(AuthRequiredError):
        gateway.create_playlist("Study", "Desc", write_context=create_ctx)
    assert len(svc.playlist_inserts) == 1

    # Timeout during create_playlist -> AmbiguousWriteError with ZERO blind retries!
    svc.forced_exc = TimeoutError("socket timed out")
    with pytest.raises(AmbiguousWriteError) as exc_info:
        gateway.create_playlist("Study", "Desc", write_context=create_ctx)
    assert exc_info.value.details["ambiguous"] is True
    assert exc_info.value.details["reconcile_required"] is True
    assert len(svc.playlist_inserts) == 2  # Exactly 1 attempt for this call (no blind replay)

    # Wrong undo target rejected locally before any API call
    wrong_undo = WriteAuthorizationContext(
        proposal_id="p_undo",
        account_id="acc_1",
        action_kind="undo",
        approved_title="Study",
        target_playlist_id="PL_other",
    )
    with pytest.raises(InvalidArgumentsError):
        gateway.delete_playlist("PL_live_001", write_context=wrong_undo)
    assert svc.playlist_deletes == []

    # Quota exhaustion marks bucket exhausted
    svc.forced_exc = _http_error(403, "quotaExceeded")
    with pytest.raises(QuotaExhaustedError):
        gateway.insert_playlist_item("PL_live_001", "vid_1", position=0, write_context=create_ctx)
    assert gateway.quota_manager.get_status().general_exhausted is True
