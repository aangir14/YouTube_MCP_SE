---
title: Human Confirmation Gate, Proposal Token Signing, and Write Lifecycle
author: Ayush Patel
date: 2026-11-24
type: research-note
status: active
srs_ids:
  - FR-7.1
  - FR-7.2
  - FR-7.3
  - FR-7.4
  - FR-7.5
  - FR-7.7
  - FR-7.8
  - FR-7.9
  - FR-5.9
  - FR-5.10
  - FR-5.11
  - FR-5.12
  - DB-2
  - DB-3
  - NFR-SEC
sources:
  - "docs/curation-walkthrough.md"
  - "FocusList_SRS_Condensed.docx"
  - "Project_1_YouTube_MCP.pdf"
evidence:
  - "docs/testing/acceptance-cases.md#st-fr5"
  - "docs/testing/acceptance-cases.md#st-fr7"
  - "docs/testing/acceptance-cases.md#sec-approval"
  - "docs/curation-walkthrough.md#scenario-cw-02-learner-decline-with-zero-writes"
  - "docs/curation-walkthrough.md#scenario-cw-05-edit--changed-request-new-proposal-required"
  - "docs/curation-walkthrough.md#scenario-cw-06-partial-creation--approved-resume"
  - "docs/curation-walkthrough.md#scenario-cw-07-approved-undo-of-focuslist-created-playlist"
uncertainty:
  - "Handling of race conditions if a user clicks approval simultaneously across multiple AI client tabs"
  - "Clock skew tolerance when validating ISO-8601 timestamps across distributed MCP client and server hosts"
---

# Human Confirmation Gate, Proposal Token Signing, and Write Lifecycle

## 1. Architectural Scope and Design Objectives

Per **FR-7.1–FR-7.9, FR-5.9–FR-5.12, DB-2, DB-3**, FocusList establishes a cryptographic and state-enforced confirmation gate governing all state-mutating YouTube Data API operations.

Because FocusList operates on personal YouTube accounts (creating, modifying, or deleting playlists), accidental, automated, or injected mutations are unacceptable. The confirmation architecture guarantees:
1. **Cryptographic Binding**: A write request cannot alter a single video, title, or privacy parameter without invalidating the cryptographic confirmation token.
2. **Distinct Conversational Turn**: The decision to mutate account state must originate from an explicit human interaction (via MCP elicitation or explicit client turn).
3. **Atomic Single-Use Tokens**: Tokens cannot be replayed or shared. Claiming a proposal transitions its state atomically in SQLite.
4. **Resilient Recovery (Partial Creation & Resume)**: Write interruptions halt safely without data loss, issuing a structured resume proposal for remaining uninserted items.
5. **Auditable Undo**: Playlists created by FocusList can be deleted through an approved undo action within a 30-day retention window. Unrecorded or third-party playlists are strictly protected.

```
+--------------------------------------------------------------------------+
|                            1. PROPOSAL STAGE                             |
|          (Read-only discovery, deterministic solver, cost calc)          |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                         Generate Proposal & Token                        |
|       Token = HMAC-SHA-256(proposal_id | video_ids | title | ...)        |
|             State: PROPOSED (persisted in SQLite, TTL: 30m)              |
+--------------------------------------------------------------------------+
                                     |
                                     +-----------------------+
                                     | (Decline / Edit)      | (Explicit Approval)
                                     v                       v
                         +-----------------------+   +---------------------+
                         | DISCARDED / EXPIRED   |   | 2. CONFIRMATION     |
                         | (Zero YouTube writes) |   |    GATE TURN        |
                         +-----------------------+   +---------------------+
                                                                 |
                                                                 v
                                                     +---------------------+
                                                     | Verify HMAC, Hash,  |
                                                     | Expiry, Unused State|
                                                     +---------------------+
                                                                 |
                                                                 v
                                                     +---------------------+
                                                     | Atomic SQLite Claim |
                                                     | State: CLAIMED      |
                                                     +---------------------+
                                                                 |
                                                                 v
                                                     +---------------------+
                                                     | 3. WRITE EXECUTION  |
                                                     | (<= 1 write/second) |
                                                     +---------------------+
                                                                 |
                                           +---------------------+---------------------+
                                           | (All succeeded)                           | (Interrupted)
                                           v                                           v
                               +-----------------------+                   +-----------------------+
                               |    State: CREATED     |                   | State: PARTIALLY_     |
                               | (Idempotent replay)   |                   |        CREATED        |
                               +-----------------------+                   +-----------------------+
                                           |                                           |
                                           v                                           v
                               +-----------------------+                   +-----------------------+
                               | 4. UNDO STAGE (<=30d) |                   | Issue Resume Proposal |
                               | (Approved deletion)   |                   | (Uninserted items)    |
                               +-----------------------+                   +-----------------------+
```

---

## 2. Cryptographic Token Specification (FR-7.1–7.4)

Each actionable proposal generated by `propose_playlist` is signed with an HMAC-SHA-256 installation key ($K_{\text{install}}$) stored securely in the OS credential store or protected configuration:

$$\text{Canonical Content} = \text{proposal\_id} \mathbin{\Vert} \text{ordered\_video\_ids} \mathbin{\Vert} \text{title} \mathbin{\Vert} \text{privacy} \mathbin{\Vert} \text{action\_kind} \mathbin{\Vert} \text{expires\_at}$$

$$\text{Token} = \text{Base64Url}(\text{HMAC-SHA-256}(K_{\text{install}}, \text{Canonical Content}))$$

### Signature Components
- `proposal_id`: UUIDv4 string.
- `ordered_video_ids`: Comma-separated list of 11-character video IDs in exact display order.
- `title`: Exact proposed playlist title string.
- `privacy`: Exact privacy status (`"private"`).
- `action_kind`: Nature of operation (`"create_playlist"`, `"resume_playlist"`, `"delete_playlist"`).
- `expires_at`: ISO-8601 UTC timestamp ($\text{creation\_time} + 30\text{ minutes}$).

### Verification Invariants
When `confirm_playlist(proposal_id, token)` is received:
1. **Signature Integrity**: Recomputes HMAC over stored proposal fields. If signature does not match, returns `CONFIRMATION_INVALID` immediately.
2. **Expiry Check**: If $\text{current\_time} > \text{expires\_at}$, returns `CONFIRMATION_INVALID` (`"Proposal has expired"`).
3. **Status Check**: Verifies stored proposal status in SQLite is `PROPOSED`. If already `CLAIMED`, `SUPERSEDED`, or `EXPIRED`, rejects.
4. **Preflight Quota & Channel Verification**: Verifies user owns a valid YouTube channel (`youtube.channels.list(mine=true)`) and has sufficient remaining daily quota.

---

## 3. Proposal Lifecycle State Transitions (DB-2, DB-3)

| Current State | Event | Next State | Side Effects & Invariants |
| :--- | :--- | :--- | :--- |
| **NONE** | Call `propose_playlist` | `PROPOSED` | Writes = 0. Records proposal, hash, and expiry in SQLite. |
| **PROPOSED** | Learner declines or 30m elapses | `EXPIRED` | Writes = 0. Token becomes permanently invalid. |
| **PROPOSED** | Learner requests edited constraints | `SUPERSEDED` | Writes = 0. A new proposal is generated; old token is invalidated. |
| **PROPOSED** | Valid `confirm_playlist` call | `CLAIMED` | Atomically transitions in single transaction. Channel checked. |
| **CLAIMED** | Write loop begins | `CREATING` | Creates playlist container via `playlists.insert`. |
| **CREATING** | All $N$ items inserted ($\le 1\text{ write/s}$) | `CREATED` | Progress committed after each item. Action history recorded. |
| **CREATING** | Write fails (retries exhausted) | `PARTIALLY_CREATED` | Halts writes immediately. Issues resume proposal token. |
| **PARTIALLY_CREATED**| Approved resume confirmation | `RESUMING` | Resumes inserting items into existing playlist. |
| **RESUMING** | Remaining items complete | `CREATED` | Full playlist assembled; transitions to `CREATED`. |
| **CREATED** | Replay of same confirmation | `CREATED` | Idempotent response: returns recorded result with **0 writes**. |
| **CREATED** | Approved `undo_playlist` within 30d | `UNDONE` | Calls `playlists.delete`. Records undo action in history. |

---

## 4. Partial Creation & Controlled Resume (FR-5.10, FR-7.8)

Network timeouts or upstream Google 5xx errors during item insertion must never cause silent corruption or duplicate playlists:
1. **Fail-Closed Write Execution**: If item insertion fails after 3 exponential backoff attempts, the server **halts immediately**.
2. **State Persistence**: The local database persists:
   - Created YouTube playlist ID: `PL_rec_12345`
   - List of successfully inserted IDs: `[v_1, v_2, ..., v_k]` ($k < N$)
   - Failed step code: e.g. `INSERT_ITEM_8_TIMEOUT`
3. **Resume Proposal**:
   The engine issues a dedicated resume proposal:
   - `action_kind`: `"resume_playlist"`
   - `target_playlist_id`: `"PL_rec_12345"`
   - `remaining_video_ids`: `[v_{k+1}, ..., v_N]`
   - `estimated_cost`: $50 \times (N - k)$ general units
4. **Explicit Approval Requirement**:
   The learner must explicitly approve the resume action. Upon confirmation, the engine resumes appending items $k+1$ through $N$ into `PL_rec_12345`. It never creates a duplicate playlist container.

---

## 5. Approved Undo & Scope Restrictions (FR-7.7)

To uphold user agency while preventing accidental data loss:
1. **Ownership Verification**: When `undo_playlist(playlist_id)` is invoked, the server verifies `playlist_id` against the SQLite `action_history` table:
   - The playlist must have been created by FocusList.
   - The creation timestamp must be within the **30-day retention window**.
2. **Strict Rejection of Non-FocusList Playlists**:
   - If a learner passes an arbitrary or third-party playlist ID, the request is rejected with `UNDO_INELIGIBLE`.
   - **Zero API calls and zero deletions occur.**
3. **Explicit Deletion Confirmation**:
   - Even for an eligible FocusList playlist, deletion is **never immediate**.
   - Server issues a deletion proposal (`action_kind: "delete_playlist"`).
   - Permanent deletion (`youtube.playlists.delete`) is executed only after the learner confirms the deletion proposal in a separate turn.

---

## 6. Traceability and Verification Mappings

| Requirement | Contract Invariant | Acceptance Test Link |
| :--- | :--- | :--- |
| **FR-7.1–7.4** | HMAC token signature, single-use, 30m expiry | [`SEC-APPROVAL`](../docs/testing/acceptance-cases.md#sec-approval), [`ST-FR7`](../docs/testing/acceptance-cases.md#st-fr7) |
| **FR-7.5** | MCP elicitation / client explicit decision | [`ST-FR5`](../docs/testing/acceptance-cases.md#st-fr5), [`SKE-SK2`](../docs/testing/acceptance-cases.md#ske-sk2) |
| **FR-7.7** | Undo strictly scoped to FocusList playlists $\le 30$ days | [`ST-FR7`](../docs/testing/acceptance-cases.md#st-fr7) |
| **FR-7.8** | Action logging without secrets or PII | [`SEC-SECRETS`](../docs/testing/acceptance-cases.md#sec-secrets) |
| **FR-5.10** | Partial creation handling & resume token | [`ST-FR7`](../docs/testing/acceptance-cases.md#st-fr7), [`CW-06`](../docs/curation-walkthrough.md#scenario-cw-06-partial-creation--approved-resume) |
| **FR-5.11** | Idempotent replay with zero additional writes | [`ST-FR5`](../docs/testing/acceptance-cases.md#st-fr5) |
| **FR-5.12** | Rate-limited writes ($\le 1\text{ write/s}$) | [`ST-FR5`](../docs/testing/acceptance-cases.md#st-fr5) |
