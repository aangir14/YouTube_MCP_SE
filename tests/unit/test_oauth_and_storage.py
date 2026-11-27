"""Unit and integration tests for Workstream 3: Google OAuth PKCE and credential storage (C16)."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from focuslist.clock import FakeClock
from focuslist.config import Settings
from focuslist.errors import (
    AuthCancelledError,
    AuthExpiredError,
    AuthRequiredError,
    InvalidArgumentsError,
)
from focuslist.platform.auth import (
    READONLY_SCOPE,
    WRITE_SCOPE,
    AuthManager,
    MemoryCredentialStore,
    SecretRedactingFilter,
    StoredOAuthCredentials,
    UserOnlyFileCredentialStore,
    load_oauth_client_config,
    redact_secrets,
)
from focuslist.platform.storage import FocusListStorage


def _write_external_client_secret(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "test-client-id.apps.googleusercontent.com",
                    "client_secret": "GOCSPX-synthetic-test-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_oauth_config_rejects_in_repo_path_and_user_file_store_isolates_db(tmp_path: Path) -> None:
    """Client secret inside repo is rejected; file store keeps keys/tokens separate from SQLite."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    in_repo_secret = _write_external_client_secret(repo_dir / "client_secret.json")

    with pytest.raises(InvalidArgumentsError, match="outside the repository"):
        load_oauth_client_config(in_repo_secret, repo_root=repo_dir)

    outside_secret = _write_external_client_secret(tmp_path / "client_secret.json")
    cfg = load_oauth_client_config(outside_secret, repo_root=repo_dir)
    assert cfg.client_id == "test-client-id.apps.googleusercontent.com"

    store = UserOnlyFileCredentialStore(tmp_path / "auth_store")
    key = store.get_or_create_signing_key()
    assert len(key) == 32
    assert store.get_or_create_signing_key() == key
    assert store.signing_key_path.exists()
    if os.name != "nt":
        assert (store.signing_key_path.stat().st_mode & 0o777) == 0o600


def test_mocked_oauth_pkce_login_readonly_and_incremental_write_scope(tmp_path: Path) -> None:
    """Initial read login requests only youtube.readonly; write scope requires confirmed write."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    client_secret = _write_external_client_secret(tmp_path / "client_secret.json")
    storage = FocusListStorage(tmp_path / "focuslist.db", clock=clock)
    store = UserOnlyFileCredentialStore(tmp_path / "creds")

    token_calls: list[dict[str, str]] = []

    def _mock_transport(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/token":
            body = parse_qs(request.content.decode("utf-8"))
            flat = {k: v[0] for k, v in body.items()}
            token_calls.append(flat)
            scope = READONLY_SCOPE if len(token_calls) == 1 else f"{READONLY_SCOPE} {WRITE_SCOPE}"
            return httpx.Response(
                200,
                json={
                    "access_token": "ya29.synthetic_access_token_value",
                    "refresh_token": "1//synthetic_refresh_token_value",
                    "expires_in": 3600,
                    "scope": scope,
                },
            )
        return httpx.Response(404)

    http_client = httpx.Client(transport=httpx.MockTransport(_mock_transport))
    cfg = Settings(provider="live", db_path=tmp_path / "focuslist.db", oauth_client_file=client_secret)
    auth = AuthManager(
        settings=cfg,
        storage=storage,
        credential_store=store,
        clock=clock,
        http_client=http_client,
    )

    explained: list[str] = []

    def _simulate_browser_consent(auth_url: str) -> None:
        parsed = urlsplit(auth_url)
        qs = parse_qs(parsed.query)
        assert qs["code_challenge_method"] == ["S256"]
        assert len(qs["code_challenge"][0]) >= 40
        redirect_uri = qs["redirect_uri"][0]
        assert redirect_uri.startswith("http://127.0.0.1:")
        # Simulate user browser hitting the loopback listener with valid code + state
        with httpx.Client() as browser_client:
            cb_resp = browser_client.get(
                redirect_uri,
                params={"code": "auth_code_123", "state": qs["state"][0]},
            )
            assert cb_resp.status_code == 200

    status = auth.login(
        explain_callback=explained.append,
        browser_opener=_simulate_browser_consent,
        callback_timeout=5.0,
    )
    assert len(explained) == 1 and READONLY_SCOPE in explained[0]
    assert status.authenticated is True
    assert status.scopes == [READONLY_SCOPE]
    assert status.has_write_scope is False
    # Verify status dict never leaks access_token or refresh_token
    serialized_status = json.dumps(status.to_tool_dict())
    assert "ya29.synthetic" not in serialized_status
    assert "1//synthetic" not in serialized_status
    assert "GOCSPX-" not in serialized_status

    # Attempting write credentials before confirmed write consent fails closed
    with pytest.raises(AuthRequiredError, match="read-only"):
        auth.ensure_valid_session(require_write=True)

    # Incremental write consent blocked unless confirmed_write_intent=True
    with pytest.raises(AuthRequiredError):
        auth.request_write_consent(confirmed_write_intent=False)

    write_status = auth.request_write_consent(
        confirmed_write_intent=True,
        browser_opener=_simulate_browser_consent,
        callback_timeout=5.0,
    )
    assert write_status.has_write_scope is True
    assert WRITE_SCOPE in write_status.scopes
    assert "code_verifier" in token_calls[0]


def test_oauth_state_mismatch_and_declined_consent_close_listener(tmp_path: Path) -> None:
    """Loopback state mismatch and user consent decline fail cleanly and close listener."""
    clock = FakeClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))
    client_secret = _write_external_client_secret(tmp_path / "client_secret.json")
    cfg = Settings(provider="live", oauth_client_file=client_secret)
    auth = AuthManager(settings=cfg, credential_store=MemoryCredentialStore(), clock=clock)

    def _bad_state_browser(auth_url: str) -> None:
        qs = parse_qs(urlsplit(auth_url).query)
        with httpx.Client() as c:
            resp = c.get(qs["redirect_uri"][0], params={"code": "c1", "state": "wrong_state"})
            assert resp.status_code == 400

    with pytest.raises(AuthCancelledError, match="state validation"):
        auth.login(browser_opener=_bad_state_browser, callback_timeout=5.0)

    def _decline_browser(auth_url: str) -> None:
        qs = parse_qs(urlsplit(auth_url).query)
        with httpx.Client() as c:
            resp = c.get(qs["redirect_uri"][0], params={"error": "access_denied", "state": qs["state"][0]})
            assert resp.status_code == 200

    with pytest.raises(AuthCancelledError, match="declined"):
        auth.login(browser_opener=_decline_browser, callback_timeout=5.0)


def test_token_refresh_day5_warning_invalid_grant_and_logout_purge(tmp_path: Path) -> None:
    """Verify day-5 warning, auto-refresh, invalid_grant purge, and logout revocation."""
    clock = FakeClock(datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    storage = FocusListStorage(tmp_path / "auth.db", clock=clock)
    storage.set_cache("user_likes", {}, "user", ["v1"], account_id="learner_1")
    storage.set_cache("categories", {"region": "US"}, "category", [{"id": "27"}])

    initial_creds = StoredOAuthCredentials(
        account_id="learner_1",
        access_token="ya29.old_access",
        refresh_token="1//valid_refresh",
        scopes=[READONLY_SCOPE],
        client_id="cid",
        expires_at=clock.now() + timedelta(hours=1),
        refresh_token_issued_at=clock.now(),
        testing_mode=True,
    )
    store = MemoryCredentialStore(initial=initial_creds)

    refresh_behavior = {"mode": "ok", "revoked": False}

    def _mock_transport(request: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com/token" in str(request.url):
            if refresh_behavior["mode"] == "ok":
                return httpx.Response(
                    200, json={"access_token": "ya29.new_access", "expires_in": 3600}
                )
            return httpx.Response(400, json={"error": "invalid_grant"})
        if "oauth2.googleapis.com/revoke" in str(request.url):
            refresh_behavior["revoked"] = True
            return httpx.Response(200, json={})
        return httpx.Response(404)

    auth = AuthManager(
        settings=Settings(provider="live", db_path=tmp_path / "auth.db"),
        storage=storage,
        credential_store=store,
        clock=clock,
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_transport)),
    )

    # Day 4 -> no testing-mode warning
    clock.advance(timedelta(days=4))
    st4 = auth.get_status()
    assert st4.token_age_days == 4
    assert st4.testing_mode_warning is False

    # Access token expired -> refreshes automatically
    refreshed = auth.ensure_valid_session()
    assert refreshed.access_token == "ya29.new_access"

    # Day 5 -> proactive testing-mode warning
    clock.advance(timedelta(days=1))
    st5 = auth.get_status()
    assert st5.token_age_days == 5
    assert st5.testing_mode_warning is True
    assert st5.warning_message and "7 days" in st5.warning_message

    # Logout revokes upstream and purges account cache without touching public category cache (7d TTL)
    logout_res = auth.logout()
    assert logout_res["revoked_remote"] is True
    assert logout_res["purged_cache_entries"] == 1
    assert store.load_credentials() is None
    assert storage.get_cache("user_likes", {}, account_id="learner_1") is None
    assert storage.get_cache("categories", {"region": "US"}) == [{"id": "27"}]

    # Re-seed creds and user cache, force invalid_grant on expired token -> AUTH_EXPIRED + purge
    storage.set_cache("user_likes", {}, "user", ["v2"], account_id="learner_1")
    store.save_credentials(
        StoredOAuthCredentials(
            account_id="learner_1",
            access_token="ya29.expired",
            refresh_token="1//revoked",
            scopes=[READONLY_SCOPE],
            client_id="cid",
            expires_at=clock.now() - timedelta(minutes=5),
            refresh_token_issued_at=clock.now() - timedelta(days=7),
        )
    )
    refresh_behavior["mode"] = "invalid_grant"
    with pytest.raises(AuthExpiredError, match="focuslist auth login"):
        auth.ensure_valid_session()
    assert store.load_credentials() is None
    assert storage.get_cache("user_likes", {}, account_id="learner_1") is None


def test_secret_redacting_filter_scrubs_tokens_from_logs() -> None:
    """Ensure OAuth tokens and secrets are scrubbed before hitting diagnostic logs."""
    raw = "Auth header Bearer ya29.secretToken123 refresh_token=1//refreshXYZ client_secret=GOCSPX-abc"
    cleaned = redact_secrets(raw)
    assert "ya29.secretToken123" not in cleaned
    assert "1//refreshXYZ" not in cleaned
    assert "GOCSPX-abc" not in cleaned

    rec = logging.LogRecord("focuslist", logging.INFO, __file__, 1, raw, (), None)
    assert SecretRedactingFilter().filter(rec) is True
    assert "ya29.secretToken123" not in rec.msg
