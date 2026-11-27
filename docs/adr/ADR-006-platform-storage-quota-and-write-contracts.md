# ADR-006: Platform Storage, Quota Admission, OAuth, and Write Contracts

- **Status:** Accepted (C16 platform integration gate for C17, C18, C19, and C22)
- **Date:** 2026-11-27 (IST)
- **Owner:** Aangir Doshi (C16)
- **Stakeholders:** Harshil Srivastav (BT2024187), Ayush Patel (BT2024171)
- **Scope:** FR-5.9–5.14, FR-7, FR-9, FR-10, FR-11, DB-1–DB-3, NFR-QUOTA-01, NFR-PRV, NFR-SEC, TBD-6, TBD-7, TBD-11

[Condensed SRS §§4.9–4.11, 5.1–5.3, 6.1, Appendix C](../../FocusList_SRS_Condensed.docx) · [C16 plan](../../FocusList_Commit_Plan.md#c16-build-the-platform-and-offline-checks) · [ADR-001](ADR-001-service-architecture-and-contracts.md) · [ADR-003](ADR-003-minimum-write-scope-and-elicitation.md) · [ADR-004](ADR-004-playlist-action-lifecycle-and-threat-model.md) · [ADR-005](ADR-005-official-youtube-provider-mapping.md)

---

## 1. Reusable Contracts for Downstream Owners (C17 & C18)

### 1.1 Storage & Transactional State (`src/focuslist/platform/storage.py`)
- **`FocusListStorage(db_path, clock=...)`**: Runs idempotent schema migrations (`schema_migrations`), enforces `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL`, and performs startup/daily local cleanup (`cleanup_expired`) without background API polling.
- **Cache TTLs & Retention**:
  - Public video/channel metadata (`"video"`, `"channel"`): `86,400 s` (24 hours).
  - Account-scoped user data & derived profiles (`"user"`, `"derived_profile"`): `21,600 s` (6 hours), strictly keyed by `account_id`.
  - Categories (`"category"`): `604,800 s` (7 days). Hard maximum: `2,592,000 s` (30 days).
  - Proposals (`proposals`): retained until `expires_at + 7 days`. Ledger (`quota_ledger`) and append-only `action_history` (enforced via `trg_action_history_no_update`): retained for 30 days.
- **C18 Proposal & Recovery Methods**: `save_proposal`, `get_proposal`, `supersede_active_proposals`, `claim_proposal` (atomic `BEGIN IMMEDIATE` single-use claim returning `ProposalClaimResult(status="claimed" | "already_completed")`), `update_proposal_execution`, `record_write_progress`, `get_write_progress`, `append_action_history`, `list_action_history`, and `is_playlist_undo_eligible`.
- **C17 Purge Guarantee**: `purge_account_data(account_id)` wipes all `"user"` and `"derived_profile"` rows for that `account_id` while leaving public entries and other accounts untouched.

### 1.2 Quota Admission & Gateway (`src/focuslist/platform/quota.py`, `src/focuslist/platform/gateway.py`)
- **`QuotaManager`**: Atomic `BEGIN IMMEDIATE` reservation (`reserve`), per-attempt charging (`charge_attempt`), retry budget verification (`can_afford_retry`), unused reservation release (`release_reservation`), zero-cost cache hit accounting (`record_cache_hit`), and bucket exhaustion tracking (`mark_exhausted`).
- **Pacific Calendar Rollover**: Uses `America/Los_Angeles` (`ZoneInfo` with portable US Pacific DST fallback in `src/focuslist/clock.py` for environments without `tzdata`) for `pacific_date_for()` and `next_pacific_midnight_utc()`.
- **`ProviderGateway`**: Implements `VideoProvider`, wraps any underlying provider, serves unexpired cache hits at 0 cost, enforces COM-5 retries (up to 3 retries on transient read timeouts/5xx only when budget and `request_unit_cap` allow), and stops immediately on `QuotaExhaustedError` or `RateLimitedError`.
- **`estimate_operation_cost`**: Single local dry-run estimator shared by `estimate_quota` MCP tool and preflight checks.

### 1.3 OAuth & Credential Storage (`src/focuslist/platform/auth.py`)
- **`AuthManager` & `CredentialStore`**: Implements RFC 7636 PKCE + ephemeral `127.0.0.1` loopback listener (`LoopbackOAuthListener`) with CSRF `state` verification and guaranteed listener closure.
- **Least Privilege (TBD-6 / ADR-003)**: Initial login requests strictly `youtube.readonly`. `request_write_consent(confirmed_write_intent=True)` upgrades to `youtube.force-ssl` only upon confirmed write intent.
- **Credential & Key Isolation**: `OSKeyringCredentialStore` with `UserOnlyFileCredentialStore` (`~/.focuslist/`, `0o700` dir / `0o600` file on POSIX) stores tokens and HMAC key `K_install` strictly outside SQLite. `SecretRedactingFilter` scrubs tokens from `focuslist` diagnostics.
- **Testing-Mode Reauthorization Prerequisites (TBD-7)**: Refresh tokens in Google Cloud Testing mode expire after 7 days (`TESTING_EXPIRY_DAYS = 7`). `auth_status` and `focuslist doctor` emit proactive warnings at day 5 (`testing_mode_warning = True`), and `invalid_grant` purges local tokens and account-scoped cache immediately. Full live reauthorization checklist & scheduled smoke workflow remain tracked for **C22**.

### 1.4 Write Primitives & C18 Guardrail (`src/focuslist/platform/write_contracts.py`, `live_provider.py`)
- **`WriteAuthorizationContext`**: Required by `LiveVideoProvider.create_playlist`, `insert_playlist_item`, and `delete_playlist`, ensuring the provider receives only stored approved title/privacy/IDs.
- **`AmbiguousWriteError`**: Raised on write timeout or uncertain upstream 5xx so C18 reconciles via `list_playlist_items_for_reconciliation` / `playlists.list` instead of issuing duplicate writes.
- **Closed Write Gate Until C18**: `confirm_playlist` and `undo_playlist` in `src/focuslist/server.py` fail closed (`CONFIRMATION_INVALID` / `INVALID_ARGUMENTS` / `CONFIRMATION_EXPIRED`) with zero writes for placeholder, unsigned, tampered, or unapproved tokens until C18 integrates verified approval.

---

## 2. TBD-11 Quota Allocation & Method Cost Verification Baseline

Per YouTube Data API v3 documentation (`developers.google.com/youtube/v3/determine_quota_cost`):
- Default project allocation: **10,000 general units/day** (with FocusList 5% safety reserve = **9,500 effective units/day**, **2,600 per-request cap**) and **100 search calls/day** tracked in a separate search bucket; scheduled live CI smoke cap: **500 units and 5 searches/run**.
- Verified per-method cost table (`METHOD_COSTS` in `src/focuslist/platform/quota.py`):
  - Read list calls (`videos.list`, `channels.list`, `playlistItems.list`, `playlists.list`, `subscriptions.list`, `videoCategories.list`): **1 general unit** per page/batch ($\le 50$ items).
  - Search (`search.list`): **1 search call** (100 Google units; isolated in FocusList's 100-search bucket).
  - Write calls (`playlists.insert`, `playlistItems.insert`, `playlists.delete`): **50 general units** per mutation.
- Final live Cloud Console cost parity check remains scheduled in **C22** (`CI-LIVE`).
