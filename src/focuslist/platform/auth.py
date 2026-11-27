"""Least-privilege Google OAuth 2.0 PKCE lifecycle and secure credential storage (C16).

Implements SRS FR-9.1–9.9, COM-2–COM-4, NFR-SEC, NFR-PRV, TQ-4, and TBD-6/ADR-003.
All Google auth imports remain strictly confined to `src/focuslist/platform/`.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import logging
import re
import secrets
import ssl
import threading
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from focuslist.clock import Clock, SystemClock
from focuslist.config import Settings, get_settings
from focuslist.errors import (
    AuthCancelledError,
    AuthExpiredError,
    AuthRequiredError,
    FocusListError,
    InvalidArgumentsError,
)
from focuslist.platform.storage import FocusListStorage, ensure_user_only_permissions

READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
WRITE_FALLBACK_SCOPE = "https://www.googleapis.com/auth/youtube"
VALID_WRITE_SCOPES = frozenset({WRITE_SCOPE, WRITE_FALLBACK_SCOPE})

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URI = "https://oauth2.googleapis.com/revoke"
TESTING_EXPIRY_DAYS = 7
TESTING_WARNING_DAY = 5

_SECRET_PATTERNS = (
    re.compile(r"ya29\.[A-Za-z0-9\-_]{8,}"),
    re.compile(r"1//[A-Za-z0-9\-_]{8,}"),
    re.compile(r"GOCSPX-[A-Za-z0-9\-_]{3,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]{12,}=*", re.IGNORECASE),
    re.compile(
        r"((?:access_token|refresh_token|client_secret|id_token)\s*[=:]\s*[\"']?)(?!<|\[REDACTED\])([^\"'\s&,}<]{6,})",
        re.IGNORECASE,
    ),
)


def redact_secrets(text: str) -> str:
    """Scrub OAuth tokens, API keys, and client secrets from diagnostic text."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 1:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class SecretRedactingFilter(logging.Filter):
    """Logging filter preventing accidental credential or token leakage on stderr."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


def build_verified_tls_context() -> ssl.SSLContext:
    """Create a certificate-verifying SSLContext enforcing TLS 1.2 or later (COM-2)."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def generate_pkce_pair() -> tuple[str, str]:
    """Generate RFC 7636 PKCE (code_verifier, S256 code_challenge)."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_oauth_state() -> str:
    """Generate a high-entropy CSRF state token for loopback OAuth callbacks."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class OAuthClientConfig:
    """Validated Google OAuth installed-application client settings loaded outside repo."""

    client_id: str
    client_secret: str | None
    auth_uri: str
    token_uri: str


def _is_within_directory(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def load_oauth_client_config(
    config_path: Path | str | None,
    *,
    repo_root: Path | None = None,
) -> OAuthClientConfig:
    """Load and validate external Google OAuth client configuration outside the repository."""
    if config_path is None or not str(config_path).strip():
        raise AuthRequiredError(
            "OAuth client configuration path is not set. Set FOCUSLIST_OAUTH_CLIENT_FILE "
            "to an external client_secret.json outside the repository."
        )
    path = Path(config_path).expanduser()
    if repo_root is not None and _is_within_directory(path, repo_root):
        raise InvalidArgumentsError(
            "OAuth client configuration must reside outside the repository working tree."
        )
    if not path.exists() or not path.is_file():
        raise AuthRequiredError(
            f"OAuth client configuration file was not found at '{path.name}'."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidArgumentsError("OAuth client configuration file is not valid JSON.") from exc

    block = raw.get("installed") or raw.get("web") or raw
    if not isinstance(block, dict):
        raise InvalidArgumentsError("OAuth client configuration JSON has an unexpected structure.")
    client_id = block.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise InvalidArgumentsError("OAuth client configuration is missing 'client_id'.")

    return OAuthClientConfig(
        client_id=client_id.strip(),
        client_secret=block.get("client_secret"),
        auth_uri=str(block.get("auth_uri") or GOOGLE_AUTH_URI),
        token_uri=str(block.get("token_uri") or GOOGLE_TOKEN_URI),
    )


class StoredOAuthCredentials(BaseModel):
    """Persisted OAuth token bundle stored strictly outside SQLite and logs."""

    model_config = ConfigDict(extra="ignore")

    account_id: str = Field(default="default_learner")
    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    scopes: list[str] = Field(default_factory=lambda: [READONLY_SCOPE])
    token_uri: str = GOOGLE_TOKEN_URI
    client_id: str = ""
    client_secret: str | None = Field(default=None, repr=False)
    expires_at: datetime
    refresh_token_issued_at: datetime
    testing_mode: bool = True

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_write_scope(self) -> bool:
        return any(s in VALID_WRITE_SCOPES for s in self.scopes)


@dataclass(frozen=True, slots=True)
class AuthStatusSnapshot:
    """Safe, credential-free authorization status summary (FR-9.6)."""

    authenticated: bool
    provider_mode: str
    account_id: str | None
    scopes: list[str]
    has_write_scope: bool
    expires_at: datetime | None
    token_age_days: int | None
    testing_mode_warning: bool
    storage_backend: str
    warning_message: str | None = None

    def to_tool_dict(self) -> dict[str, Any]:
        return {
            "authenticated": self.authenticated,
            "provider_mode": self.provider_mode,
            "account_id": self.account_id,
            "scopes": list(self.scopes),
            "has_write_scope": self.has_write_scope,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "token_age_days": self.token_age_days,
            "testing_mode_warning": self.testing_mode_warning,
            "storage_backend": self.storage_backend,
            "warning": self.warning_message,
            "notice": (
                "Credentials and signing keys are stored outside SQLite and never exposed in output."
            ),
        }


@runtime_checkable
class CredentialStore(Protocol):
    """Protocol abstracting OS credential store, user-only file fallback, and test fakes."""

    backend_name: str

    def load_credentials(self) -> StoredOAuthCredentials | None: ...

    def save_credentials(self, creds: StoredOAuthCredentials) -> None: ...

    def delete_credentials(self) -> None: ...

    def get_or_create_signing_key(self) -> bytes: ...


class UserOnlyFileCredentialStore:
    """Fallback user-only credential and key store (~/.focuslist/) with 0600 permissions."""

    backend_name = "user_only_file"

    def __init__(self, store_dir: Path | str | None = None) -> None:
        self.store_dir = Path(store_dir) if store_dir else (Path.home() / ".focuslist")
        self.credentials_path = self.store_dir / "credentials.json"
        self.signing_key_path = self.store_dir / "signing_key.bin"

    def _ensure_dir(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        ensure_user_only_permissions(self.store_dir, is_dir=True)

    def load_credentials(self) -> StoredOAuthCredentials | None:
        if not self.credentials_path.exists():
            return None
        raw = json.loads(self.credentials_path.read_text(encoding="utf-8"))
        return StoredOAuthCredentials(**raw)

    def save_credentials(self, creds: StoredOAuthCredentials) -> None:
        self._ensure_dir()
        payload = creds.model_dump(mode="json")
        self.credentials_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        ensure_user_only_permissions(self.credentials_path, is_dir=False)

    def delete_credentials(self) -> None:
        if self.credentials_path.exists():
            self.credentials_path.unlink()

    def get_or_create_signing_key(self) -> bytes:
        self._ensure_dir()
        if self.signing_key_path.exists():
            data = self.signing_key_path.read_bytes()
            if len(data) >= 32:
                return data
        key = secrets.token_bytes(32)
        self.signing_key_path.write_bytes(key)
        ensure_user_only_permissions(self.signing_key_path, is_dir=False)
        return key


class OSKeyringCredentialStore:
    """Primary OS keyring credential store with automatic fallback to user-only file store."""

    def __init__(
        self,
        *,
        service_name: str = "focuslist-youtube-mcp",
        fallback: UserOnlyFileCredentialStore | None = None,
    ) -> None:
        self.service_name = service_name
        self.fallback = fallback or UserOnlyFileCredentialStore()
        self._keyring, self._keyring_errors = self._probe_keyring()
        self.backend_name = "os_keyring" if self._keyring is not None else self.fallback.backend_name

    @staticmethod
    def _probe_keyring() -> tuple[Any | None, tuple[type[BaseException], ...]]:
        base_errors: tuple[type[BaseException], ...] = (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            ImportError,
        )
        try:
            kr = importlib.import_module("keyring")
            kr_errs = importlib.import_module("keyring.errors")
            err_cls = getattr(kr_errs, "KeyringError", None)
            if isinstance(err_cls, type) and issubclass(err_cls, BaseException):
                base_errors = (*base_errors, err_cls)
            backend = kr.get_keyring()
            if backend is None or "fail" in type(backend).__name__.lower():
                return None, base_errors
            return kr, base_errors
        except base_errors:
            return None, base_errors

    def load_credentials(self) -> StoredOAuthCredentials | None:
        if self._keyring is not None:
            try:
                raw = self._keyring.get_password(self.service_name, "oauth_credentials")
                if raw:
                    return StoredOAuthCredentials(**json.loads(raw))
            except self._keyring_errors:
                self.backend_name = self.fallback.backend_name
        return self.fallback.load_credentials()

    def save_credentials(self, creds: StoredOAuthCredentials) -> None:
        if self._keyring is not None:
            try:
                self._keyring.set_password(
                    self.service_name,
                    "oauth_credentials",
                    json.dumps(creds.model_dump(mode="json")),
                )
                return
            except self._keyring_errors:
                self.backend_name = self.fallback.backend_name
        self.fallback.save_credentials(creds)

    def delete_credentials(self) -> None:
        if self._keyring is not None:
            try:
                self._keyring.delete_password(self.service_name, "oauth_credentials")
            except self._keyring_errors:
                self.backend_name = self.fallback.backend_name
        self.fallback.delete_credentials()

    def get_or_create_signing_key(self) -> bytes:
        if self._keyring is not None:
            try:
                encoded = self._keyring.get_password(self.service_name, "hmac_signing_key")
                if encoded:
                    return base64.b64decode(encoded.encode("ascii"))
                key = secrets.token_bytes(32)
                self._keyring.set_password(
                    self.service_name,
                    "hmac_signing_key",
                    base64.b64encode(key).decode("ascii"),
                )
                return key
            except self._keyring_errors:
                self.backend_name = self.fallback.backend_name
        return self.fallback.get_or_create_signing_key()


class MemoryCredentialStore:
    """In-memory fake credential store for offline unit and MCP system tests."""

    backend_name = "memory_mock"

    def __init__(self, initial: StoredOAuthCredentials | None = None) -> None:
        self._creds = initial
        self._signing_key: bytes = secrets.token_bytes(32)

    def load_credentials(self) -> StoredOAuthCredentials | None:
        return self._creds

    def save_credentials(self, creds: StoredOAuthCredentials) -> None:
        self._creds = creds

    def delete_credentials(self) -> None:
        self._creds = None

    def get_or_create_signing_key(self) -> bytes:
        return self._signing_key


class LoopbackOAuthListener:
    """Temporary 127.0.0.1 ephemeral-port HTTP callback listener with CSRF state check."""

    def __init__(self, expected_state: str) -> None:
        self.expected_state = expected_state
        self.code: str | None = None
        self.error: FocusListError | None = None
        self._done = threading.Event()
        outer = self

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                params = parse_qs(parsed.query, keep_blank_values=True)
                err = (params.get("error") or [None])[0]
                state = (params.get("state") or [None])[0]
                code = (params.get("code") or [None])[0]

                if err == "access_denied":
                    outer.error = AuthCancelledError(
                        "Google consent was declined by the user."
                    )
                    self._send_html(200, "Consent declined. You may close this window.")
                elif state != outer.expected_state:
                    outer.error = AuthCancelledError(
                        "OAuth callback failed state validation (CSRF protection)."
                    )
                    self._send_html(400, "Invalid OAuth state parameter.")
                elif not code:
                    outer.error = AuthCancelledError(
                        "OAuth callback did not include an authorization code."
                    )
                    self._send_html(400, "Missing authorization code.")
                else:
                    outer.code = code
                    self._send_html(200, "Authorization successful. You may close this window.")
                outer._done.set()

            def _send_html(self, status: int, body: str) -> None:
                data = f"<html><body><p>{body}</p></body></html>".encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: Any) -> None:
                # Never emit callback URLs/codes to stdout or stderr
                return

        self._server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self.host, self.port = self._server.server_address
        self.redirect_uri = f"http://127.0.0.1:{self.port}/callback"
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self.closed = False

    def _serve_loop(self) -> None:
        self._server.timeout = 0.5
        while not self._done.is_set() and not self.closed:
            self._server.handle_request()

    def start(self) -> None:
        self._thread.start()

    def wait_for_code(self, timeout_seconds: float = 120.0) -> str:
        if not self._done.wait(timeout=timeout_seconds):
            raise AuthCancelledError("Timed out waiting for browser OAuth callback.")
        if self.error is not None:
            raise self.error
        if not self.code:
            raise AuthCancelledError("Authorization did not return a code.")
        return self.code

    def close(self) -> None:
        self.closed = True
        self._done.set()
        try:
            self._server.server_close()
        except OSError:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)


class AuthManager:
    """Manages OAuth login, incremental write consent, refresh, status, and logout purge."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage: FocusListStorage | None = None,
        credential_store: CredentialStore | None = None,
        clock: Clock | None = None,
        http_client: httpx.Client | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage
        self.clock: Clock = clock or (storage.clock if storage else SystemClock())
        if credential_store is not None:
            self.credential_store: CredentialStore = credential_store
        elif self.settings.auth_store_dir is not None:
            self.credential_store = UserOnlyFileCredentialStore(self.settings.auth_store_dir)
        else:
            self.credential_store = OSKeyringCredentialStore()
        self._http_client = http_client
        self._repo_root = repo_root

    def _client(self) -> tuple[httpx.Client, bool]:
        if self._http_client is not None:
            return self._http_client, False
        client = httpx.Client(
            verify=build_verified_tls_context(),
            timeout=self.settings.request_timeout_seconds,
        )
        return client, True

    @staticmethod
    def explain_scopes(scopes: Sequence[str]) -> str:
        """Produce clear pre-consent scope explanation for the learner (UI-3, FR-9.3)."""
        lines = ["FocusList is requesting the following Google OAuth 2.0 permissions:"]
        for scope in scopes:
            if scope == READONLY_SCOPE:
                lines.append(
                    f"  - {scope} (read-only access to public videos, likes, subscriptions, playlists)"
                )
            elif scope in VALID_WRITE_SCOPES:
                lines.append(
                    f"  - {scope} (playlist creation, item insertion, and confirmed deletion)"
                )
            else:
                lines.append(f"  - {scope}")
        return "\n".join(lines)

    def login(
        self,
        scopes: Sequence[str] | None = None,
        *,
        explain_callback: Callable[[str], None] | None = None,
        browser_opener: Callable[[str], Any] | None = None,
        callback_timeout: float = 120.0,
        account_id: str = "authorized_learner",
    ) -> AuthStatusSnapshot:
        """Run Authorization Code + PKCE loopback flow with least-privilege scope defaults."""
        requested_scopes = list(scopes) if scopes is not None else [READONLY_SCOPE]
        if not requested_scopes:
            raise InvalidArgumentsError("At least one OAuth scope must be requested.")

        client_cfg = load_oauth_client_config(
            self.settings.oauth_client_file,
            repo_root=self._repo_root,
        )
        explanation = self.explain_scopes(requested_scopes)
        if explain_callback is not None:
            explain_callback(explanation)

        verifier, challenge = generate_pkce_pair()
        state = generate_oauth_state()
        listener = LoopbackOAuthListener(expected_state=state)
        listener.start()
        try:
            auth_params = {
                "client_id": client_cfg.client_id,
                "redirect_uri": listener.redirect_uri,
                "response_type": "code",
                "scope": " ".join(requested_scopes),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
            auth_url = f"{client_cfg.auth_uri}?{urlencode(auth_params)}"
            opener = browser_opener or webbrowser.open
            opener(auth_url)
            code = listener.wait_for_code(timeout_seconds=callback_timeout)
        finally:
            listener.close()

        token_payload: dict[str, str] = {
            "client_id": client_cfg.client_id,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": listener.redirect_uri,
        }
        if client_cfg.client_secret:
            token_payload["client_secret"] = client_cfg.client_secret

        client, should_close = self._client()
        try:
            resp = client.post(client_cfg.token_uri, data=token_payload)
        except httpx.TimeoutException as exc:
            raise AuthCancelledError("Timed out exchanging OAuth authorization code.") from exc
        finally:
            if should_close:
                client.close()

        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            err_code = str(data.get("error") or "")
            if err_code == "access_denied":
                raise AuthCancelledError("Google consent was declined.")
            if err_code == "invalid_grant":
                raise AuthExpiredError("Authorization code expired or rejected (invalid_grant).")
            raise AuthCancelledError(f"OAuth token exchange failed (HTTP {resp.status_code}).")

        now = self.clock.now()
        expires_in = int(data.get("expires_in") or 3600)
        granted_scopes = (
            str(data["scope"]).split()
            if isinstance(data.get("scope"), str) and data["scope"].strip()
            else requested_scopes
        )
        creds = StoredOAuthCredentials(
            account_id=account_id,
            access_token=str(data["access_token"]),
            refresh_token=data.get("refresh_token"),
            scopes=granted_scopes,
            token_uri=client_cfg.token_uri,
            client_id=client_cfg.client_id,
            client_secret=client_cfg.client_secret,
            expires_at=now + timedelta(seconds=expires_in),
            refresh_token_issued_at=now,
            testing_mode=True,
        )
        self.credential_store.save_credentials(creds)
        return self.get_status()

    def request_write_consent(
        self,
        *,
        confirmed_write_intent: bool,
        explain_callback: Callable[[str], None] | None = None,
        browser_opener: Callable[[str], Any] | None = None,
        callback_timeout: float = 120.0,
    ) -> AuthStatusSnapshot:
        """Incrementally request the single write scope ONLY after explicit confirmed write intent."""
        if not confirmed_write_intent:
            raise AuthRequiredError(
                "Write scope consent cannot be requested without an explicitly confirmed playlist write."
            )
        existing = self.credential_store.load_credentials()
        account_id = existing.account_id if existing else "authorized_learner"
        return self.login(
            scopes=[READONLY_SCOPE, WRITE_SCOPE],
            explain_callback=explain_callback,
            browser_opener=browser_opener,
            callback_timeout=callback_timeout,
            account_id=account_id,
        )

    def _refresh_credentials(self, creds: StoredOAuthCredentials) -> StoredOAuthCredentials:
        if not creds.refresh_token:
            raise AuthExpiredError(
                "Stored OAuth session has expired and has no refresh token. Run 'focuslist auth login'."
            )
        payload: dict[str, str] = {
            "client_id": creds.client_id,
            "refresh_token": creds.refresh_token,
            "grant_type": "refresh_token",
        }
        if creds.client_secret:
            payload["client_secret"] = creds.client_secret

        client, should_close = self._client()
        try:
            resp = client.post(creds.token_uri or GOOGLE_TOKEN_URI, data=payload)
        except httpx.TimeoutException as exc:
            raise AuthExpiredError("OAuth token refresh timed out.") from exc
        finally:
            if should_close:
                client.close()

        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            err_name = str(data.get("error") or "")
            if err_name == "invalid_grant":
                self._purge_on_revocation(creds.account_id)
                raise AuthExpiredError(
                    "OAuth refresh token expired or was revoked (invalid_grant). "
                    "Run 'focuslist auth login' to re-authenticate."
                )
            raise AuthExpiredError(
                f"Failed to refresh OAuth access token (HTTP {resp.status_code}). "
                "Run 'focuslist auth login'."
            )

        now = self.clock.now()
        expires_in = int(data.get("expires_in") or 3600)
        updated = StoredOAuthCredentials(
            account_id=creds.account_id,
            access_token=str(data["access_token"]),
            refresh_token=data.get("refresh_token") or creds.refresh_token,
            scopes=creds.scopes,
            token_uri=creds.token_uri,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            expires_at=now + timedelta(seconds=expires_in),
            refresh_token_issued_at=creds.refresh_token_issued_at,
            testing_mode=creds.testing_mode,
        )
        self.credential_store.save_credentials(updated)
        return updated

    def _purge_on_revocation(self, account_id: str) -> None:
        self.credential_store.delete_credentials()
        if self.storage is not None and account_id:
            self.storage.purge_account_data(account_id)

    def ensure_valid_session(self, *, require_write: bool = False) -> StoredOAuthCredentials:
        """Load, scope-check, and automatically refresh credentials when expired."""
        creds = self.credential_store.load_credentials()
        if creds is None:
            raise AuthRequiredError()
        if require_write and not creds.has_write_scope():
            raise AuthRequiredError(
                "Playlist writes require incremental write consent; current session is read-only."
            )
        if not require_write and not creds.has_scope(READONLY_SCOPE) and not creds.has_write_scope():
            raise AuthRequiredError("Stored session lacks required YouTube read permission.")

        now = self.clock.now()
        exp = (
            creds.expires_at.replace(tzinfo=UTC)
            if creds.expires_at.tzinfo is None
            else creds.expires_at.astimezone(UTC)
        )
        if now >= exp - timedelta(seconds=60):
            creds = self._refresh_credentials(creds)
        return creds

    def build_google_credentials(self, *, require_write: bool = False) -> Any:
        """Construct a google.oauth2.credentials.Credentials instance (platform-confined)."""
        from google.oauth2.credentials import Credentials as GoogleCredentials

        creds = self.ensure_valid_session(require_write=require_write)
        return GoogleCredentials(
            token=creds.access_token,
            refresh_token=creds.refresh_token,
            token_uri=creds.token_uri,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            scopes=list(creds.scopes),
        )

    def get_status(self) -> AuthStatusSnapshot:
        """Report current authorization status, scopes, and token age without token values."""
        if self.settings.provider == "fixture" and self.credential_store.load_credentials() is None:
            return AuthStatusSnapshot(
                authenticated=True,
                provider_mode=self.settings.provider,
                account_id="fixture_learner",
                scopes=[READONLY_SCOPE],
                has_write_scope=False,
                expires_at=None,
                token_age_days=0,
                testing_mode_warning=False,
                storage_backend=f"{self.credential_store.backend_name} (fixture)",
                warning_message=None,
            )

        creds = self.credential_store.load_credentials()
        if creds is None:
            return AuthStatusSnapshot(
                authenticated=False,
                provider_mode=self.settings.provider,
                account_id=None,
                scopes=[],
                has_write_scope=False,
                expires_at=None,
                token_age_days=None,
                testing_mode_warning=False,
                storage_backend=self.credential_store.backend_name,
                warning_message="Not authenticated. Run 'focuslist auth login'.",
            )

        issued = (
            creds.refresh_token_issued_at.replace(tzinfo=UTC)
            if creds.refresh_token_issued_at.tzinfo is None
            else creds.refresh_token_issued_at.astimezone(UTC)
        )
        age_days = max(0, (self.clock.now() - issued).days)
        warn = creds.testing_mode and age_days >= TESTING_WARNING_DAY
        warning_msg: str | None = None
        if warn:
            warning_msg = (
                f"Testing-mode refresh token is {age_days} days old (expires after "
                f"{TESTING_EXPIRY_DAYS} days). Run 'focuslist auth login' to re-authenticate."
            )

        return AuthStatusSnapshot(
            authenticated=True,
            provider_mode=self.settings.provider,
            account_id=creds.account_id,
            scopes=list(creds.scopes),
            has_write_scope=creds.has_write_scope(),
            expires_at=creds.expires_at,
            token_age_days=age_days,
            testing_mode_warning=warn,
            storage_backend=self.credential_store.backend_name,
            warning_message=warning_msg,
        )

    def logout(self) -> dict[str, Any]:
        """Revoke OAuth token upstream (when present) and purge stored tokens & account cache."""
        creds = self.credential_store.load_credentials()
        revoked_remote = False
        purged_cache_rows = 0
        account_id: str | None = None

        if creds is not None:
            account_id = creds.account_id
            token_to_revoke = creds.refresh_token or creds.access_token
            if token_to_revoke and self.settings.provider != "fixture":
                client, should_close = self._client()
                try:
                    resp = client.post(GOOGLE_REVOKE_URI, params={"token": token_to_revoke})
                    revoked_remote = resp.status_code == 200
                except httpx.HTTPError:
                    revoked_remote = False
                finally:
                    if should_close:
                        client.close()
            self.credential_store.delete_credentials()
            if self.storage is not None and account_id:
                counts = self.storage.purge_account_data(account_id)
                purged_cache_rows = counts["cache_entries"]

        return {
            "logged_out": True,
            "account_id": account_id,
            "revoked_remote": revoked_remote,
            "purged_cache_entries": purged_cache_rows,
        }
