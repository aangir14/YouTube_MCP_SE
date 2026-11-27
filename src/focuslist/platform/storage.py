"""SQLite persistence layer for cache, Pacific quota ledger, proposals, and action history.

Implements SRS FR-11.4–11.9, DB-1–DB-3, NFR-PRV, and NFR-REL (C16).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from focuslist.clock import Clock, SystemClock, pacific_date_for
from focuslist.errors import (
    ConfirmationExpiredError,
    ConfirmationInvalidError,
    InvalidArgumentsError,
)

# SRS FR-11.4 Cache TTLs & DB-3 Retention Windows (seconds)
TTL_VIDEO_SECONDS = 86_400  # 24 hours
TTL_CHANNEL_SECONDS = 86_400  # 24 hours
TTL_USER_SECONDS = 21_600  # 6 hours
TTL_CATEGORY_SECONDS = 604_800  # 7 days
MAX_CACHE_TTL_SECONDS = 2_592_000  # 30 days hard cap
ACTION_RETENTION_SECONDS = 2_592_000  # 30 days
PROPOSAL_POST_EXPIRY_RETENTION_SECONDS = 604_800  # 7 days after proposal expiry

CacheCategory = Literal["video", "channel", "user", "category", "derived_profile"]

CATEGORY_DEFAULT_TTLS: dict[str, int] = {
    "video": TTL_VIDEO_SECONDS,
    "channel": TTL_CHANNEL_SECONDS,
    "user": TTL_USER_SECONDS,
    "category": TTL_CATEGORY_SECONDS,
    "derived_profile": TTL_USER_SECONDS,
}

CACHE_ACCOUNT_SCOPED_CATEGORIES = frozenset({"user", "derived_profile"})

_SCHEMA_V1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        applied_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS storage_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cache_entries (
        cache_key TEXT PRIMARY KEY,
        category TEXT NOT NULL CHECK(
            category IN ('video', 'channel', 'user', 'category', 'derived_profile')
        ),
        account_id TEXT,
        response_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        max_expires_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_cache_account ON cache_entries(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_cache_category ON cache_entries(category)",
    """
    CREATE TABLE IF NOT EXISTS quota_ledger (
        pacific_date TEXT PRIMARY KEY,
        units_used INTEGER NOT NULL DEFAULT 0 CHECK(units_used >= 0),
        units_reserved INTEGER NOT NULL DEFAULT 0 CHECK(units_reserved >= 0),
        searches_used INTEGER NOT NULL DEFAULT 0 CHECK(searches_used >= 0),
        searches_reserved INTEGER NOT NULL DEFAULT 0 CHECK(searches_reserved >= 0),
        cache_hits INTEGER NOT NULL DEFAULT 0 CHECK(cache_hits >= 0),
        general_exhausted INTEGER NOT NULL DEFAULT 0 CHECK(general_exhausted IN (0, 1)),
        search_exhausted INTEGER NOT NULL DEFAULT 0 CHECK(search_exhausted IN (0, 1)),
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS proposals (
        proposal_id TEXT PRIMARY KEY,
        action_kind TEXT NOT NULL CHECK(action_kind IN ('create', 'resume', 'undo')),
        owner_account_id TEXT NOT NULL,
        title TEXT NOT NULL,
        privacy_status TEXT NOT NULL CHECK(privacy_status IN ('private', 'unlisted', 'public')),
        ordered_video_ids_json TEXT NOT NULL,
        target_playlist_id TEXT,
        canonical_payload_json TEXT NOT NULL,
        canonical_hash TEXT NOT NULL,
        state TEXT NOT NULL CHECK(
            state IN ('proposed', 'confirmed', 'completed', 'expired', 'invalidated', 'superseded')
        ),
        execution_status TEXT NOT NULL DEFAULT 'pending',
        claimed_at INTEGER,
        expires_at INTEGER NOT NULL,
        retain_until INTEGER NOT NULL,
        inserted_count INTEGER NOT NULL DEFAULT 0 CHECK(inserted_count >= 0),
        failed_step_code TEXT,
        result_json TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_proposals_retain ON proposals(retain_until)",
    "CREATE INDEX IF NOT EXISTS idx_proposals_owner ON proposals(owner_account_id)",
    "CREATE INDEX IF NOT EXISTS idx_proposals_expires ON proposals(expires_at)",
    """
    CREATE TABLE IF NOT EXISTS write_progress (
        proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id) ON DELETE CASCADE,
        item_index INTEGER NOT NULL CHECK(item_index >= 0),
        video_id TEXT NOT NULL,
        playlist_item_id TEXT,
        status TEXT NOT NULL CHECK(status IN ('pending', 'inserted', 'failed', 'ambiguous')),
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (proposal_id, item_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_epoch INTEGER NOT NULL,
        proposal_id TEXT,
        proposal_hash TEXT NOT NULL,
        action_kind TEXT NOT NULL CHECK(
            action_kind IN ('create', 'resume', 'undo', 'confirm_rejected', 'write_failed')
        ),
        account_id TEXT NOT NULL,
        target_playlist_id TEXT,
        inserted_count INTEGER NOT NULL DEFAULT 0 CHECK(inserted_count >= 0),
        outcome TEXT NOT NULL,
        failed_step_code TEXT,
        result_json TEXT,
        retain_until INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_action_history_retain ON action_history(retain_until)",
    (
        "CREATE INDEX IF NOT EXISTS idx_action_history_playlist "
        "ON action_history(target_playlist_id, timestamp_epoch)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_action_history_account ON action_history(account_id)",
    """
    CREATE TRIGGER IF NOT EXISTS trg_action_history_no_update
    BEFORE UPDATE ON action_history
    BEGIN
        SELECT RAISE(ABORT, 'action_history is append-only');
    END
    """,
)

SCHEMA_MIGRATIONS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (1, "Initial cache, quota ledger, proposals, write progress, and action history", _SCHEMA_V1_STATEMENTS),
)


def ensure_user_only_permissions(path: Path, *, is_dir: bool = False) -> None:
    """Restrict local storage directory or file permissions to the current user."""
    if os.name == "nt":
        return
    try:
        mode = 0o700 if is_dir else 0o600
        os.chmod(path, mode)
    except OSError:
        pass


def build_cache_key(
    method: str,
    params: dict[str, Any] | None = None,
    account_id: str | None = None,
) -> str:
    """Construct a deterministic SHA-256 cache key scoped by method, args, and account."""
    canonical = json.dumps(
        {
            "method": method,
            "params": params or {},
            "account_id": account_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def pacific_date_string(dt: datetime) -> str:
    """Return the YYYY-MM-DD date in America/Los_Angeles for a UTC/aware datetime."""
    return pacific_date_for(dt)


@dataclass(frozen=True, slots=True)
class StoredProposal:
    """Persisted proposal state returned by the SQLite repository."""

    proposal_id: str
    action_kind: str
    owner_account_id: str
    title: str
    privacy_status: str
    ordered_video_ids: list[str]
    target_playlist_id: str | None
    canonical_payload: dict[str, Any]
    canonical_hash: str
    state: str
    execution_status: str
    claimed_at: int | None
    expires_at: int
    retain_until: int
    inserted_count: int
    failed_step_code: str | None
    result: dict[str, Any] | None
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class ProposalClaimResult:
    """Outcome of attempting an atomic proposal claim."""

    status: Literal["claimed", "already_completed"]
    proposal: StoredProposal
    recorded_result: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WriteProgressEntry:
    """Per-item insertion progress for partial creation and resume."""

    proposal_id: str
    item_index: int
    video_id: str
    playlist_item_id: str | None
    status: str
    updated_at: int


@dataclass(frozen=True, slots=True)
class ActionHistoryEntry:
    """Append-only operational audit record (no tokens or private text)."""

    entry_id: int
    timestamp_epoch: int
    proposal_id: str | None
    proposal_hash: str
    action_kind: str
    account_id: str
    target_playlist_id: str | None
    inserted_count: int
    outcome: str
    failed_step_code: str | None
    result: dict[str, Any] | None
    retain_until: int


class FocusListStorage:
    """Transactional SQLite repository supporting cache, quota ledger, proposals, and history."""

    def __init__(
        self,
        db_path: Path | str,
        clock: Clock | None = None,
        *,
        auto_migrate: bool = True,
        run_startup_cleanup: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.clock: Clock = clock or SystemClock()
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            ensure_user_only_permissions(self.db_path.parent, is_dir=True)
        if auto_migrate:
            self.run_migrations()
        if run_startup_cleanup:
            self.cleanup_expired()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Execute SQL work inside an explicit transaction boundary."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def run_migrations(self) -> list[int]:
        """Apply any pending schema migrations idempotently and enable WAL mode."""
        conn = self._connect()
        applied_now: list[int] = []
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at INTEGER NOT NULL
                )
                """
            )
            existing = {
                int(row["version"])
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            now_epoch = self.clock.now_epoch()
            for version, description, statements in SCHEMA_MIGRATIONS:
                if version in existing:
                    continue
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, description, applied_at) "
                        "VALUES (?, ?, ?)",
                        (version, description, now_epoch),
                    )
                    conn.execute("COMMIT")
                    applied_now.append(version)
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        finally:
            conn.close()

        if str(self.db_path) != ":memory:" and self.db_path.exists():
            ensure_user_only_permissions(self.db_path, is_dir=False)
        return applied_now

    def schema_version(self) -> int:
        """Return the highest applied migration version."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS ver FROM schema_migrations").fetchone()
            return int(row["ver"]) if row else 0

    def journal_mode(self) -> str:
        """Return the active SQLite journal mode."""
        with closing(self._connect()) as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]).lower() if row else ""

    def foreign_keys_enabled(self) -> bool:
        """Return whether SQLite foreign key enforcement is active."""
        with closing(self._connect()) as conn:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            return bool(row[0]) if row else False

    # ==========================================================================
    # Cache Operations & Retention (FR-11.4–11.9, NFR-PRV)
    # ==========================================================================

    def set_cache(
        self,
        method: str,
        params: dict[str, Any] | None,
        category: str,
        payload: Any,
        *,
        account_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Store a JSON-serializable response in cache with SRS TTL and 30-day hard cap."""
        if not isinstance(method, str) or not method.strip():
            raise InvalidArgumentsError("Cache method must be a non-empty string.")
        if category not in CATEGORY_DEFAULT_TTLS:
            raise InvalidArgumentsError(f"Unsupported cache category '{category}'.")
        if category in CACHE_ACCOUNT_SCOPED_CATEGORIES:
            if not isinstance(account_id, str) or not account_id.strip():
                raise InvalidArgumentsError(
                    f"Account-scoped cache category '{category}' requires an account_id."
                )
        elif account_id is not None:
            raise InvalidArgumentsError(
                f"Public cache category '{category}' must not carry an account_id."
            )

        ttl = CATEGORY_DEFAULT_TTLS[category] if ttl_seconds is None else ttl_seconds
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0 or ttl > MAX_CACHE_TTL_SECONDS:
            raise InvalidArgumentsError(
                f"Cache TTL must be between 1 and {MAX_CACHE_TTL_SECONDS} seconds."
            )

        now_epoch = self.clock.now_epoch()
        expires_at = now_epoch + ttl
        max_expires_at = now_epoch + MAX_CACHE_TTL_SECONDS
        cache_key = build_cache_key(method, params, account_id=account_id)
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        with self.transaction(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO cache_entries (
                    cache_key, category, account_id, response_json,
                    created_at, expires_at, max_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    category = excluded.category,
                    account_id = excluded.account_id,
                    response_json = excluded.response_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at,
                    max_expires_at = excluded.max_expires_at
                """,
                (cache_key, category, account_id, serialized, now_epoch, expires_at, max_expires_at),
            )
        return cache_key

    def get_cache(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        category: str | None = None,
        account_id: str | None = None,
    ) -> Any | None:
        """Retrieve a valid unexpired cache payload, or None if missing/expired."""
        self.maybe_run_daily_cleanup()
        cache_key = build_cache_key(method, params, account_id=account_id)
        now_epoch = self.clock.now_epoch()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT category, account_id, response_json, expires_at, max_expires_at
                FROM cache_entries
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None
        if category is not None and row["category"] != category:
            return None
        if row["account_id"] != account_id:
            return None
        if int(row["expires_at"]) <= now_epoch or int(row["max_expires_at"]) <= now_epoch:
            return None
        return json.loads(row["response_json"])

    def maybe_run_daily_cleanup(self) -> dict[str, int] | None:
        """Run local retention cleanup once per calendar day without polling or API calls."""
        today = pacific_date_string(self.clock.now())
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM storage_meta WHERE key = 'last_cleanup_date'"
            ).fetchone()
        finally:
            conn.close()
        if row is not None and row["value"] == today:
            return None
        return self.cleanup_expired()

    def cleanup_expired(self) -> dict[str, int]:
        """Purge expired cache entries, proposals past +7d retention, and 30-day ledger/history."""
        now_dt = self.clock.now()
        now_epoch = self.clock.now_epoch()
        today_pacific = pacific_date_string(now_dt)
        ledger_cutoff = pacific_date_string(now_dt - timedelta(days=30))

        with self.transaction(immediate=True) as conn:
            cur_cache = conn.execute(
                "DELETE FROM cache_entries WHERE expires_at <= ? OR max_expires_at <= ?",
                (now_epoch, now_epoch),
            )
            cur_prop = conn.execute(
                "DELETE FROM proposals WHERE retain_until <= ?",
                (now_epoch,),
            )
            cur_hist = conn.execute(
                "DELETE FROM action_history WHERE retain_until <= ?",
                (now_epoch,),
            )
            cur_ledger = conn.execute(
                "DELETE FROM quota_ledger WHERE pacific_date < ?",
                (ledger_cutoff,),
            )
            conn.execute(
                """
                INSERT INTO storage_meta (key, value) VALUES ('last_cleanup_date', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (today_pacific,),
            )
        return {
            "cache_entries": cur_cache.rowcount,
            "proposals": cur_prop.rowcount,
            "action_history": cur_hist.rowcount,
            "quota_ledger": cur_ledger.rowcount,
        }

    def purge_account_data(self, account_id: str) -> dict[str, int]:
        """Immediately purge all cached user/derived data for one account (FR-9.8, FR-11.6)."""
        if not isinstance(account_id, str) or not account_id.strip():
            raise InvalidArgumentsError("account_id must be a non-empty string for account purge.")
        clean_id = account_id.strip()
        now_epoch = self.clock.now_epoch()

        with self.transaction(immediate=True) as conn:
            cur_cache = conn.execute(
                "DELETE FROM cache_entries WHERE account_id = ?",
                (clean_id,),
            )
            cur_prop = conn.execute(
                """
                UPDATE proposals
                SET state = 'invalidated', updated_at = ?
                WHERE owner_account_id = ? AND state = 'proposed'
                """,
                (now_epoch, clean_id),
            )
        return {
            "cache_entries": cur_cache.rowcount,
            "proposals_invalidated": cur_prop.rowcount,
        }

    # ==========================================================================
    # Proposals, Atomic Claims, Write Progress & Action History (DB-2, DB-3)
    # ==========================================================================

    @staticmethod
    def _row_to_proposal(row: sqlite3.Row) -> StoredProposal:
        return StoredProposal(
            proposal_id=str(row["proposal_id"]),
            action_kind=str(row["action_kind"]),
            owner_account_id=str(row["owner_account_id"]),
            title=str(row["title"]),
            privacy_status=str(row["privacy_status"]),
            ordered_video_ids=json.loads(row["ordered_video_ids_json"]),
            target_playlist_id=row["target_playlist_id"],
            canonical_payload=json.loads(row["canonical_payload_json"]),
            canonical_hash=str(row["canonical_hash"]),
            state=str(row["state"]),
            execution_status=str(row["execution_status"]),
            claimed_at=row["claimed_at"],
            expires_at=int(row["expires_at"]),
            retain_until=int(row["retain_until"]),
            inserted_count=int(row["inserted_count"]),
            failed_step_code=row["failed_step_code"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    def save_proposal(
        self,
        *,
        proposal_id: str,
        action_kind: Literal["create", "resume", "undo"],
        owner_account_id: str,
        title: str,
        privacy_status: Literal["private", "unlisted", "public"],
        ordered_video_ids: list[str],
        canonical_payload: dict[str, Any],
        canonical_hash: str,
        expires_at: datetime,
        target_playlist_id: str | None = None,
    ) -> StoredProposal:
        """Persist an immutable proposal with unique ID and expiry+7d retention (never stores token)."""
        if not proposal_id or not owner_account_id or not canonical_hash:
            raise InvalidArgumentsError("proposal_id, owner_account_id, and canonical_hash are required.")
        now_epoch = self.clock.now_epoch()
        exp_epoch = int((expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC)).timestamp())
        retain_until = exp_epoch + PROPOSAL_POST_EXPIRY_RETENTION_SECONDS

        try:
            with self.transaction(immediate=True) as conn:
                conn.execute(
                    """
                    INSERT INTO proposals (
                        proposal_id, action_kind, owner_account_id, title, privacy_status,
                        ordered_video_ids_json, target_playlist_id, canonical_payload_json,
                        canonical_hash, state, execution_status, claimed_at, expires_at,
                        retain_until, inserted_count, failed_step_code, result_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', 'pending', NULL, ?, ?, 0, NULL, NULL, ?, ?)
                    """,
                    (
                        proposal_id,
                        action_kind,
                        owner_account_id,
                        title,
                        privacy_status,
                        json.dumps(ordered_video_ids, separators=(",", ":")),
                        target_playlist_id,
                        json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")),
                        canonical_hash,
                        exp_epoch,
                        retain_until,
                        now_epoch,
                        now_epoch,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise InvalidArgumentsError(f"Proposal '{proposal_id}' already exists.") from exc
        loaded = self.get_proposal(proposal_id)
        assert loaded is not None
        return loaded

    def get_proposal(self, proposal_id: str) -> StoredProposal | None:
        """Fetch a persisted proposal by ID, or None if not found."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        finally:
            conn.close()
        return self._row_to_proposal(row) if row is not None else None

    def supersede_active_proposals(
        self,
        owner_account_id: str,
        *,
        action_kind: str | None = None,
    ) -> int:
        """Mark older active proposals for an owner as superseded (FR-7.3)."""
        now_epoch = self.clock.now_epoch()
        with self.transaction(immediate=True) as conn:
            if action_kind is not None:
                cur = conn.execute(
                    """
                    UPDATE proposals
                    SET state = 'superseded', updated_at = ?
                    WHERE owner_account_id = ? AND action_kind = ? AND state = 'proposed'
                    """,
                    (now_epoch, owner_account_id, action_kind),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE proposals
                    SET state = 'superseded', updated_at = ?
                    WHERE owner_account_id = ? AND state = 'proposed'
                    """,
                    (now_epoch, owner_account_id),
                )
            return cur.rowcount

    def claim_proposal(
        self,
        proposal_id: str,
        *,
        owner_account_id: str,
        expected_action_kind: str,
        expected_hash: str,
    ) -> ProposalClaimResult:
        """Atomically claim a valid, unexpired proposal before any YouTube write (DB-2, FR-7)."""
        now_epoch = self.clock.now_epoch()
        with self.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise ConfirmationInvalidError("Proposal was not found or has expired past retention.")

            proposal = self._row_to_proposal(row)
            if (
                proposal.owner_account_id != owner_account_id
                or proposal.action_kind != expected_action_kind
                or proposal.canonical_hash != expected_hash
            ):
                raise ConfirmationInvalidError(
                    "Confirmation context or canonical proposal hash does not match."
                )

            if proposal.state == "completed":
                return ProposalClaimResult(
                    status="already_completed",
                    proposal=proposal,
                    recorded_result=proposal.result,
                )

            if proposal.state == "expired" or now_epoch > proposal.expires_at:
                if proposal.state == "proposed":
                    conn.execute(
                        "UPDATE proposals SET state = 'expired', updated_at = ? WHERE proposal_id = ?",
                        (now_epoch, proposal_id),
                    )
                raise ConfirmationExpiredError()

            if proposal.state != "proposed":
                raise ConfirmationInvalidError(
                    f"Proposal is in state '{proposal.state}' and cannot be claimed."
                )

            cur = conn.execute(
                """
                UPDATE proposals
                SET state = 'confirmed',
                    execution_status = 'claimed',
                    claimed_at = ?,
                    updated_at = ?
                WHERE proposal_id = ? AND state = 'proposed'
                """,
                (now_epoch, now_epoch, proposal_id),
            )
            if cur.rowcount != 1:
                raise ConfirmationInvalidError("Proposal was already claimed concurrently.")

            updated_row = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            assert updated_row is not None
            return ProposalClaimResult(
                status="claimed",
                proposal=self._row_to_proposal(updated_row),
            )

    def update_proposal_execution(
        self,
        proposal_id: str,
        *,
        state: Literal["proposed", "confirmed", "completed", "expired", "invalidated", "superseded"]
        | None = None,
        execution_status: str | None = None,
        target_playlist_id: str | None = None,
        inserted_count: int | None = None,
        failed_step_code: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> StoredProposal:
        """Update execution state and progress fields for a claimed proposal."""
        now_epoch = self.clock.now_epoch()
        with self.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise InvalidArgumentsError(f"Unknown proposal '{proposal_id}'.")

            new_state = state if state is not None else str(row["state"])
            new_exec = execution_status if execution_status is not None else str(row["execution_status"])
            new_pid = target_playlist_id if target_playlist_id is not None else row["target_playlist_id"]
            new_inserted = inserted_count if inserted_count is not None else int(row["inserted_count"])
            new_failed = failed_step_code if failed_step_code is not None else row["failed_step_code"]
            new_result_json = (
                json.dumps(result, separators=(",", ":"), ensure_ascii=False)
                if result is not None
                else row["result_json"]
            )
            conn.execute(
                """
                UPDATE proposals
                SET state = ?,
                    execution_status = ?,
                    target_playlist_id = ?,
                    inserted_count = ?,
                    failed_step_code = ?,
                    result_json = ?,
                    updated_at = ?
                WHERE proposal_id = ?
                """,
                (
                    new_state,
                    new_exec,
                    new_pid,
                    new_inserted,
                    new_failed,
                    new_result_json,
                    now_epoch,
                    proposal_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            assert updated is not None
            return self._row_to_proposal(updated)

    def record_write_progress(
        self,
        *,
        proposal_id: str,
        item_index: int,
        video_id: str,
        status: Literal["pending", "inserted", "failed", "ambiguous"],
        playlist_item_id: str | None = None,
    ) -> None:
        """Record per-item playlist insertion state inside an atomic transaction."""
        now_epoch = self.clock.now_epoch()
        with self.transaction(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO write_progress (
                    proposal_id, item_index, video_id, playlist_item_id, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id, item_index) DO UPDATE SET
                    video_id = excluded.video_id,
                    playlist_item_id = COALESCE(excluded.playlist_item_id, write_progress.playlist_item_id),
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (proposal_id, item_index, video_id, playlist_item_id, status, now_epoch),
            )

    def get_write_progress(self, proposal_id: str) -> list[WriteProgressEntry]:
        """Return ordered write progress items for a proposal."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT proposal_id, item_index, video_id, playlist_item_id, status, updated_at
                FROM write_progress
                WHERE proposal_id = ?
                ORDER BY item_index ASC
                """,
                (proposal_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            WriteProgressEntry(
                proposal_id=str(r["proposal_id"]),
                item_index=int(r["item_index"]),
                video_id=str(r["video_id"]),
                playlist_item_id=r["playlist_item_id"],
                status=str(r["status"]),
                updated_at=int(r["updated_at"]),
            )
            for r in rows
        ]

    def append_action_history(
        self,
        *,
        proposal_id: str | None,
        proposal_hash: str,
        action_kind: Literal["create", "resume", "undo", "confirm_rejected", "write_failed"],
        account_id: str,
        target_playlist_id: str | None = None,
        inserted_count: int = 0,
        outcome: str,
        failed_step_code: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> int:
        """Append an operational audit entry with 30-day retention (never stores tokens/PII)."""
        now_epoch = self.clock.now_epoch()
        retain_until = now_epoch + ACTION_RETENTION_SECONDS
        result_json = (
            json.dumps(result, separators=(",", ":"), ensure_ascii=False)
            if result is not None
            else None
        )
        with self.transaction(immediate=True) as conn:
            cur = conn.execute(
                """
                INSERT INTO action_history (
                    timestamp_epoch, proposal_id, proposal_hash, action_kind,
                    account_id, target_playlist_id, inserted_count, outcome,
                    failed_step_code, result_json, retain_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_epoch,
                    proposal_id,
                    proposal_hash,
                    action_kind,
                    account_id,
                    target_playlist_id,
                    inserted_count,
                    outcome,
                    failed_step_code,
                    result_json,
                    retain_until,
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def list_action_history(self, *, account_id: str | None = None) -> list[ActionHistoryEntry]:
        """Return retained append-only action history records."""
        now_epoch = self.clock.now_epoch()
        conn = self._connect()
        try:
            if account_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM action_history
                    WHERE account_id = ? AND retain_until > ?
                    ORDER BY id ASC
                    """,
                    (account_id, now_epoch),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM action_history WHERE retain_until > ? ORDER BY id ASC",
                    (now_epoch,),
                ).fetchall()
        finally:
            conn.close()
        return [
            ActionHistoryEntry(
                entry_id=int(r["id"]),
                timestamp_epoch=int(r["timestamp_epoch"]),
                proposal_id=r["proposal_id"],
                proposal_hash=str(r["proposal_hash"]),
                action_kind=str(r["action_kind"]),
                account_id=str(r["account_id"]),
                target_playlist_id=r["target_playlist_id"],
                inserted_count=int(r["inserted_count"]),
                outcome=str(r["outcome"]),
                failed_step_code=r["failed_step_code"],
                result=json.loads(r["result_json"]) if r["result_json"] else None,
                retain_until=int(r["retain_until"]),
            )
            for r in rows
        ]

    def is_playlist_undo_eligible(self, playlist_id: str, account_id: str) -> bool:
        """Check whether playlist_id was created by FocusList for account_id within 30 days and not undone."""
        now_epoch = self.clock.now_epoch()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT action_kind, outcome
                FROM action_history
                WHERE target_playlist_id = ?
                  AND account_id = ?
                  AND retain_until > ?
                ORDER BY id ASC
                """,
                (playlist_id, account_id, now_epoch),
            ).fetchall()
        finally:
            conn.close()
        created = False
        undone = False
        for row in rows:
            kind = str(row["action_kind"])
            outcome = str(row["outcome"]).lower()
            if kind in {"create", "resume"} and outcome in {"created", "partially_created", "resumed"}:
                created = True
            if kind == "undo" and outcome == "undone":
                undone = True
        return created and not undone
