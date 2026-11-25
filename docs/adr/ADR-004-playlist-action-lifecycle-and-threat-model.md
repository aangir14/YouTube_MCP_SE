# ADR-004: Playlist Action Lifecycle, Selection Objective, and Threat Model

- **Status:** Proposed for owner and teammate review
- **Date:** 2026-11-25 (IST)
- **Owner:** Ayush Patel (C09)
- **Stakeholders:** Aangir Doshi (BT2024078), Harshil Srivastav (BT2024187)
- **Scope:** FR-5, FR-7, FR-8, NFR-SAF, NFR-SEC, DB-2, DB-3

[Condensed SRS §§4.5, 4.7–4.8, 5.2–5.3, 6.1](../../FocusList_SRS_Condensed.docx) · [Course brief §§2–5](../../Project_1_YouTube_MCP.pdf) · [C09 plan](../../FocusList_Commit_Plan.md#c09-design-the-playlist-action-lifecycle) · [ADR-001 shared contracts](ADR-001-service-architecture-and-contracts.md) · [ADR-002 scoring & text transform](ADR-002-discovery-analytics-and-ranking-evaluation.md) · [Curation walkthrough](../curation-walkthrough.md)

---

## 1. Context and Design Goals

FocusList curates YouTube playlists from natural-language learner constraints (**FR-5**) and executes account-mutating writes only after explicit human review (**FR-7**, **NFR-SAF**). Because YouTube Data API v3 mutations (playlist creation, item insertion, playlist deletion) are non-transactional across multiple HTTP requests, expensive in quota (50 units per write), and exposed to untrusted external metadata, curation requires:

1. Strict separation between **read-only proposal**, **human approval**, and **provider write rights**.
2. A deterministic, single-use, cryptographically bound **proposal lifecycle** with atomic SQLite claims.
3. Safe **idempotent replay** on duplicate confirmation and **reconciliation-first recovery** after remote timeouts.
4. A **pure deterministic duration solver** with objective, non-engagement-based **FR-5** scoring inputs and explicit infeasibility reporting.
5. A documented **threat model** protecting against prompt injection, token tampering, replay, and unauthorized deletions.

*(Note: `ADR-003` is reserved for Aangir Doshi's C10 minimum writable OAuth scope decision under TBD-6; this curation record is numbered `ADR-004`.)*

---

## 2. Separation of Rights and Checkpoints

FocusList enforces a three-boundary architecture so that neither the AI client nor untrusted YouTube metadata can trigger an unapproved write:

| Phase | Tool / Actor | Provider Rights | Quota, Budget & Auth Checkpoints |
| :--- | :--- | :--- | :--- |
| **1. Proposal** | `propose_playlist` (or `undo_playlist` for deletion proposal) | **Read-only** (`youtube.readonly` or fixture). Zero mutations. | 1. Validate all arguments locally before any provider call.<br>2. Preflight read quota (`<= 3` searches, `<= 15` general units for `propose_playlist`; `0` calls for `undo_playlist`).<br>3. Verify read auth if live mode is active.<br>4. Persist immutable proposal in SQLite (`state = "proposed"`). |
| **2. Approval** | Human learner via MCP elicitation or separate client turn | **None.** Purely local human decision over displayed proposal fields. | No provider calls or quota charges. Untrusted video/channel text is marked `untrusted: true` and cannot supply or trigger confirmation tokens. |
| **3. Execution** | `confirm_playlist` (with `proposal_id` + `token`) | **Write-capable** (`playlists.insert`, `playlistItems.insert`, `playlists.delete`, plus `channels.list` / reconciliation reads). | **Strictly before any YouTube request:**<br>1. Validate input types and token format.<br>2. Verify HMAC-SHA-256 signature, stored `canonical_hash`, `expires_at` via injected `Clock`, `owner_account_id`, `action_kind`, and unused state.<br>3. Check idempotency: if already `completed`, return recorded result (**0 writes**).<br>4. Atomically claim proposal in SQLite (`proposed -> confirmed`).<br>5. Verify OAuth write scope (TBD-6 / ADR-003), channel eligibility (`NO_YOUTUBE_CHANNEL`), and write quota (`51 + 50*N` create, `50*R` resume, `50` undo). |

---

## 3. Playlist Action State Machine

### 3.1 State Transition Table

| Current State | Trigger / Event | Guard Conditions | Next State | Side Effects & Invariants |
| :--- | :--- | :--- | :--- | :--- |
| *(none)* | `propose_playlist` / `undo_playlist` | Inputs valid; feasible selection (or valid FocusList-owned playlist $\le 30$ days for undo) | **`proposed`** | Persists canonical JSON, `canonical_hash`, HMAC `token`, `expires_at` (`now + 30m`), and `state = "proposed"`. **Writes = 0.** |
| `proposed` | `Clock.now() > expires_at` | Expiry elapsed before claim | **`expired`** | Lazily or periodically marked `expired`. Any later `confirm_playlist` fails closed with `CONFIRMATION_EXPIRED`. **Writes = 0.** |
| `proposed` | Learner edits constraints / new `propose_playlist` | New proposal generated for same session/context | **`superseded`** | Earlier proposal marked `superseded`; its token fails closed with `CONFIRMATION_INVALID`. **Writes = 0.** |
| `proposed` | Learner declines | Client discards or elicitation returns decline | **`expired`** *(or `invalidated`)* | `confirm_playlist` is never called. **Writes = 0.** |
| `proposed` | Valid `confirm_playlist` | HMAC valid, hash matches, not expired, owner matches, action kind matches, atomic claim succeeds | **`confirmed`** *(claim)* | Atomically updates `state = "confirmed"` in SQLite. Next verifies write auth, channel eligibility, and write quota before first YouTube write. |
| `confirmed` | Write sequence starts | Channel eligible and write budget reserved | **`creating`** | Calls `playlists.insert` (for `create`), records `target_playlist_id`, then calls `playlistItems.insert` at $\le 1\text{ write/s}$, persisting each inserted item index. |
| `creating` | All $N$ items inserted | $N$ of $N$ confirmed | **`completed`** *(Created)* | Records final playlist URL, item count, and action history row in SQLite. |
| `creating` | Write fails after retries / timeout | Permanent error or exhausted retries after partial progress | **`partially_created`** | Halts writes immediately; persists `target_playlist_id`, `inserted_count`, `remaining_video_ids`, and `failed_step_code`. Returns `PARTIALLY_CREATED` and issues a **new** `resume` proposal (`state = "proposed"`). |
| `partially_created` | Confirmed `resume` proposal | Separate human approval of `resume` proposal (`action_kind = "resume"`) | **`resuming`** | Inserts only `remaining_video_ids` into `target_playlist_id` at $\le 1\text{ write/s}$. Never creates a duplicate playlist or re-inserts completed items. |
| `resuming` | Remaining items complete | All remaining items confirmed | **`completed`** *(Resumed)* | Updates action history and marks both resume and parent records complete. |
| `completed` | Exact replay of `confirm_playlist` | Same `proposal_id` and valid `token` for an already-created proposal | **`completed`** | **Idempotent success (FR-5.11):** returns the previously recorded playlist ID, URL, and item count with **0 additional writes** and **0 write quota**. |
| `completed` | Confirmed `undo` proposal | `action_kind = "undo"`, FocusList-created playlist within 30-day window, separate approval | **`undone`** | Calls `playlists.delete(id=target_playlist_id)`. Records `UNDONE` in append-only action history. |

*(Compatibility note with C07 `ProposalRecord`: C07's `src/focuslist/types.py` pins `state` literals as `"proposed" | "confirmed" | "completed" | "expired" | "invalidated"`. Transient execution sub-states (`creating`, `partially_created`, `resuming`, `undone`) are tracked via `execution_status` / action-history status columns alongside `ProposalRecord.state`, or `ProposalRecord.state` is extended in C12/C21 by team agreement.)*

---

## 4. Canonical Proposal Format, Signing, and Consent Boundary

### 4.1 Canonical Proposal Fields
Every actionable proposal (`create`, `resume`, `undo`) serializes a deterministic canonical JSON object (UTF-8, sorted keys, no insignificant whitespace) before hashing and signing:

| Field | Type | Create | Resume | Undo | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `proposal_id` | `str` (UUIDv4) | New UUID | New UUID | New UUID | Unique single-use identifier |
| `action_kind` | `Literal["create", "resume", "undo"]` | `"create"` | `"resume"` | `"undo"` | Prevents cross-action token reuse |
| `owner_account_id` | `str` | Active account ID (or `"fixture"`) | Same account ID | Same account ID | Binds proposal to authorised learner |
| `title` | `str` | `"{topic} - {YYYY-MM-DD}"` (or custom) | Original title | Stored title | Sanitized, max 100 chars |
| `privacy_status` | `Literal["private", "unlisted", "public"]` | `"private"` (default) | Original privacy | Original privacy | Private by default (FR-5.9) |
| `ordered_video_ids` | `list[str]` | `[v_1, ..., v_N]` | Remaining `[v_{k+1}, ..., v_N]` | `[]` | Exact ordered IDs to write |
| `target_playlist_id` | `str \| None` | `None` | Existing `PL...` ID | Existing `PL...` ID | Binds recovery/deletion to exact target |
| `expires_at` | `str` (UTC RFC 3339) | `now + 30m` | `now + 30m` | `now + 30m` | Evaluated against injected `Clock` |

- **Persisted Hash (`canonical_hash`)**: `SHA-256(canonical_json)`.
- **Confirmation Token (`token`)**: `Base64Url(HMAC-SHA-256(K_install, canonical_json))`, where `K_install` is a local installation secret stored in the OS credential store (or `0600` user-only fallback), **never** logged or returned in error details.
- **SQLite Claim & Progress Columns**: `proposal_id` (PK), `canonical_hash`, `state`, `execution_status`, `claimed_at`, `target_playlist_id`, `inserted_count`, `failed_step_code`, `result_json`.

### 4.2 Human Approval Path (With and Without Elicitation)
1. **With MCP Elicitation (when supported by demo client, TBD-2):**
   - Server displays the structured proposal summary (order, sanitized title, channel, duration, score, reason, total runtime, item count, constraint status, estimated write cost) and requests explicit confirmation via MCP elicitation in the approval step.
2. **Without MCP Elicitation (standard conversational fallback):**
   - `propose_playlist` (or `undo_playlist`) returns the read-only proposal, visible item table, cost, `proposal_id`, and `token`.
   - The AI client renders the exact reviewed action to the learner and **must wait for a separate human turn** ("Yes, create/resume/delete") before calling `confirm_playlist(proposal_id, token)`.
   - Prompt instructions embedded in `VideoRecord` / `ChannelRecord` metadata are marked `untrusted: true` and are strictly ignored by authorisation logic.

---

## 5. Error, Replay, and Ambiguous Write Recovery Behaviour

### 5.1 Error Mapping and Remediations
All curation errors map to C07's `ErrorCode` registry (`src/focuslist/errors.py`) with actionable `remediation` hints and `retryable` flags:

| Condition | Error Code | Retryable | Behaviour & Remediation |
| :--- | :--- | :---: | :--- |
| Missing/invalid topic, negative duration, `min > max`, `max_items > 50` | `INVALID_ARGUMENTS` | `False` | Reject locally before any YouTube call or quota reservation. |
| Tampered token, hash mismatch, wrong `action_kind`, wrong account, `superseded` | `CONFIRMATION_INVALID` | `False` | Fail closed before any YouTube call. Advise obtaining a fresh proposal. |
| `Clock.now() > expires_at` | `CONFIRMATION_EXPIRED` | `False` | Fail closed before any YouTube call. Advise re-running `propose_playlist`. |
| Write cost exceeds remaining daily quota or 2,600-unit cap | `QUOTA_BUDGET_EXCEEDED` | `False` | Reject preflight with **0 outbound writes**; show required vs remaining units. |
| Missing write consent or expired OAuth token | `AUTH_REQUIRED` / `AUTH_EXPIRED` | `False` | Reject before writes; instruct user to run `focuslist auth login`. |
| Google account has no YouTube channel | `NO_YOUTUBE_CHANNEL` | `False` | Detect on `channels.list(mine=true)` preflight; abort before `playlists.insert`. |
| Mid-sequence insertion failure | `PARTIALLY_CREATED` | `True` (via resume) | Halt writes immediately, persist `target_playlist_id` + `inserted_count`, return partial link and a fresh `resume` proposal. |
| Undo requested for non-FocusList or $> 30$-day playlist | `INVALID_ARGUMENTS` *(or `UNDO_INELIGIBLE`)* | `False` | Reject locally from SQLite action history with **0 YouTube calls**. *(Open choice: whether to add `UNDO_INELIGIBLE` to `ErrorCode` in C12/C30.)* |

### 5.2 Ambiguous Write Recovery (Remote Timeout)
Per **Implementation Plan §3 & §5**, FocusList **never blindly retries a write whose upstream outcome is unknown**:
1. **Timeout during `playlists.insert`**:
   - Before retrying or failing, query `youtube.playlists.list(mine=true, maxResults=25)` (1 general unit) to check whether a private playlist with the exact proposed title and creation window already exists.
   - If found: record `target_playlist_id` in SQLite and proceed to item insertions without creating a duplicate playlist.
   - If not found and retry budget permits: retry once; otherwise fail safely and leave `proposal` uncompleted with clear diagnostic status.
2. **Timeout during `playlistItems.insert` at index $k$**:
   - Before retrying, query `youtube.playlistItems.list(playlistId=target_playlist_id, maxResults=50)` (1 general unit) to check whether `video_id[k]` is already present at or after index $k$.
   - If present: advance `inserted_count` to $k+1$ in SQLite and continue.
   - If absent: retry if within retry/budget cap; otherwise transition to `partially_created` and issue a `resume` proposal for `[k..N]`.
3. **Reconciliation itself fails / times out**:
   - Halt immediately, do **not** retry the mutation, record the ambiguous step in SQLite `action_history` with a safe failed-step code, and report the unresolved state to the learner for manual verification.

---

## 6. Deterministic Selection Objective, Scoring Inputs, and Ordering (FR-5, FR-8)

### 6.1 Selection Objective and Infeasibility
- **Units:** All durations are normalized to integer seconds (`int`).
- **Hard Filters (applied before scoring/selection):** Exclude non-public, unavailable, live, upcoming, duplicate, age-restricted (by default), sub-60s (unless `min_item_duration` explicitly permits), items outside `[min_item_duration, max_item_duration]`, and language mismatches.
- **Explicit Language Policy:** When an explicit language is requested (default `"en"`), candidates with a mismatched primary BCP-47 subtag or `language is None` are excluded by default. Unknown-language candidates may be admitted only if an explicit opt-in policy (`allow_unknown_language=True`) is enabled, in which case they are flagged in the proposal's `constraint_status` and warnings.
- **Optimization Objective:** Using bounded dynamic programming / branch-and-bound over reachable integer-second totals, select subset $X \subseteq C_{\text{eligible}}$ maximizing:
  $$\text{Maximize } \sum_{v \in X} \text{score}(v) \quad \text{subject to} \quad T_{\text{lower}} \le \sum_{v \in X} d(v) \le T_{\text{upper}}, \quad |X| \le N_{\text{max}}$$
  where $T_{\text{lower}} = \lceil T(1 - \tau) \rceil$, $T_{\text{upper}} = \lfloor T(1 + \tau) \rfloor$ (default $\tau = 0.05$), and $N_{\text{max}} = \min(\text{max\_items}, 50)$ (default 30, tracked under **TBD-9**).
- **Deterministic Tie-Breaking:** (1) Higher total relevance score (6-decimal rounded), (2) smaller absolute runtime error $|\sum d(v) - T|$, (3) newer mean publication date, (4) lexicographically smallest sorted tuple of `video_id`s.
- **Infeasible Selection:** Never silently relax hard constraints (`max_item_duration`, `language`, `target_duration` tolerance). Return a read-only `infeasible` response containing the nearest achievable hard-filtered total duration, item count, and each unmet constraint with deficit/surplus. Issue **no** confirmation token.

### 6.2 FR-5 Scoring Factors (`0.65, 0.10, 0.10, 0.10, 0.05`)
Every eligible candidate receives a normalized score in $[0.0, 1.0]$ using SRS-pinned weights:

| Factor | Weight | Definition & Calculation | Missing-Field Handling |
| :--- | :---: | :--- | :--- |
| **`topic_match`** | `0.65` | L2-normalized TF-IDF cosine similarity between the sanitized `topic` query and candidate `title + description + tags`, reusing ADR-002's shared Unicode NFKC + casefold tokenizer. | `0.0` if candidate text is empty; flag `missing_fields`. |
| **`caption_availability`** | `0.10` | `1.0` if `has_captions is True`; `0.0` if `False` or `None`. | `0.0` if `None`; flag `has_captions`. |
| **`freshness`** | `0.10` | `max(0.0, 1.0 - age_days / 1825.0)` relative to injected `Clock.now()` (5-year linear decay aligned with FR-12 staleness). | `0.0` if `published_at is None`; flag `published_at`. |
| **`capped_quality`** | `0.10` | **Objective metadata-derived signal with zero engagement ranking** (excludes views, likes, comments, watch history) and no double-counting of topic, captions, freshness, or language. Defined as equal `1/3` contributions for: (a) informative description (`len(description) >= 50`), (b) structured tags (`len(tags) >= 3`), and (c) assigned `category_id is not None`, capped at `1.0`. | Missing sub-signal contributes `0.0`. *(Open choice: exact sub-signal thresholds may be tuned in C15 if metadata is sparse.)* |
| **`known_language`** | `0.05` | `1.0` if `language` primary BCP-47 subtag matches requested language; `0.0` otherwise. | `0.0` if `language is None`; flag `language`. |

### 6.3 FR-8 Diversity, Ordering, and Study Sessions
- **Pre-Selection Diversity & Deduplication:** Near-duplicate title collapse (title cosine $\ge 0.90$, keeping higher-scoring item), per-channel cap (default $\le 3$ items per channel), and Maximal Marginal Relevance ($\lambda = 0.7$) are applied **before or inside** candidate selection so they never silently invalidate total duration bounds.
- **Post-Selection Ordering (`learning_path` default, `relevance`, `chronological`):**
  - `learning_path`: Detects series (same `channel_id`, distinct episode/part numbers, title cosine $\ge 0.60$), keeps detected series adjacent in ascending episode order, and orders remaining items by difficulty cues (introductory $\rightarrow$ intermediate $\rightarrow$ advanced) then descending relevance.
- **Study Session Packing (`session_minutes`):** Groups the already-ordered playlist consecutively without splitting videos, reporting each session's videos and total duration, and flagging any single video whose duration exceeds `session_minutes`.

---

## 7. Threat Model for Playlist Curation (NFR-SAF, NFR-SEC)

| Threat ID | Threat & Attack Vector | Impact | Mitigation & Architectural Control | Verification Target |
| :--- | :--- | :--- | :--- | :--- |
| **TM-01** | **Prompt Injection via YouTube Metadata:** Malicious video title/description instructs AI client to auto-confirm or call `confirm_playlist`. | Unauthorized playlist creation or deletion. | Strip control/zero-width chars, truncate descriptions to 500 chars, tag `untrusted: true`, and enforce separate human approval turn (never trust model-only text from metadata). | [`SEC-APPROVAL`](../testing/acceptance-cases.md#sec-approval) |
| **TM-02** | **Token Tampering / Forgery:** Client or caller alters `title`, `privacy_status`, or `ordered_video_ids` while reusing `proposal_id` or `token`. | Writing unreviewed videos or making a private playlist public. | Recompute `canonical_hash` and `HMAC-SHA-256` over all canonical fields on confirmation; mismatch fails closed with `CONFIRMATION_INVALID` before any API call. | [`SEC-APPROVAL`](../testing/acceptance-cases.md#sec-approval), [`ST-FR7`](../testing/acceptance-cases.md#st-fr7) |
| **TM-03** | **Replay / Duplicate Write:** Calling `confirm_playlist` multiple times with the same valid token. | Duplicate playlists or duplicate quota spend. | Atomic SQLite claim (`proposed -> confirmed`). Exact replay of `completed` proposal returns recorded result with **0 additional writes**; replay of `expired`/`superseded` fails closed. | [`ST-FR5`](../testing/acceptance-cases.md#st-fr5), [`ST-FR7`](../testing/acceptance-cases.md#st-fr7) |
| **TM-04** | **Cross-Action / Cross-Account Confusion:** Using a `create` token for `undo`, or one account's token on another account. | Accidental deletion or cross-account leakage. | `action_kind` and `owner_account_id` are bound into `canonical_hash` and `token` and verified against active context before claiming. | [`SEC-APPROVAL`](../testing/acceptance-cases.md#sec-approval) |
| **TM-05** | **Confused-Deputy Undo:** Calling `undo_playlist` on a user's pre-existing personal playlist not created by FocusList. | Irreversible loss of user's own YouTube playlist. | `undo_playlist` checks SQLite `action_history` for FocusList creation provenance within 30 days, and still requires a signed `undo` proposal + separate confirmation turn. | [`ST-FR7`](../testing/acceptance-cases.md#st-fr7) |
| **TM-06** | **Quota Exhaustion / Overspend:** Large playlist confirmation or retry loop drains daily 10,000-unit budget. | Service denial for all other tools. | Preflight write budget check (`51 + 50*N`) before `playlists.insert`; $\le 1\text{ write/s}$ pacing; halt on quota exhaustion with zero retries. | [`IT-QUOTA`](../testing/acceptance-cases.md#it-quota), [`ST-FR10`](../testing/acceptance-cases.md#st-fr10) |
| **TM-07** | **Ambiguous Timeout Duplicate:** Blindly retrying `playlists.insert` after HTTP timeout. | Orphaned duplicate playlists in user account. | Reconcile via `playlists.list(mine=true)` / `playlistItems.list` before any retry; transition to `partially_created` if unresolved. | [`ST-FR7`](../testing/acceptance-cases.md#st-fr7) |
| **TM-08** | **Secret / Token / PII Leakage:** Logging `token`, `K_install`, OAuth credentials, or personal data in stdout/logs/DB. | Credential compromise or privacy violation. | Redact `token` and keys from all logs and `action_history`; keep stdout strictly for JSON-RPC 2.0. | [`SEC-SECRETS`](../testing/acceptance-cases.md#sec-secrets) |

---

## 8. Open Choices & Downstream Integration Notes

The following unresolved items remain explicitly open per SRS Appendix C and implementation plan handoffs:
1. **TBD-2 (MCP Elicitation Support):** Demo client elicitation support is to be probed and recorded by Aangir in **C10** and verified in **C24**.
2. **TBD-6 (Minimum Writable OAuth Scope):** Exact write scope (`youtube` vs `youtube.force-ssl`) will be pinned by Aangir in **ADR-003 (C10)** and tested in **C22**.
3. **TBD-9 (30-Item Default):** Usefulness and quota impact of the 30-item default (`NFR-QUOTA` vs solver runtime) will be measured by Ayush in **C18 / C27**.
4. **C07 `ProposalRecord` & `ErrorCode` Extensions (for C12 / C21 / C30):**
   - Extend `ProposalRecord` (or companion SQLite persistence model) with `target_playlist_id`, `owner_account_id`, `execution_status`, and `inserted_count` for `resume`/`undo`.
   - Decide in **C12 / C30** whether to add `UNDO_INELIGIBLE` and `INFEASIBLE_CONSTRAINTS` to `ErrorCode` or return `INVALID_ARGUMENTS` / structured infeasible `ResultEnvelope`.
   - Confirm whether `capped_quality` sub-signal thresholds (`>= 50` char description, `>= 3` tags, `category_id`) need adjustment against C15 synthetic fixtures.
