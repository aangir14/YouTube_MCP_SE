---
title: Quota Budget Management, Caching Strategy, and Dry-Run Estimation
author: Aangir Doshi
date: 2026-11-19
type: research-note
status: active
srs_ids:
  - FR-10.1
  - FR-10.2
  - FR-10.3
  - FR-10.4
  - FR-10.5
  - FR-10.6
  - FR-10.7
  - FR-10.8
  - FR-10.9
  - FR-11.4
  - FR-11.5
  - FR-11.6
  - FR-11.7
  - FR-11.8
  - FR-11.9
  - NFR-QUOTA-01
  - DB-1
  - DB-2
  - DB-3
  - TBD-11
sources:
  - "https://developers.google.com/youtube/v3/determine_quota_cost"
  - "https://cloud.google.com/docs/quota"
  - "FocusList_SRS_Condensed.docx Section 4.10, 5.1, Appendix B"
  - "FocusList_Commit_Plan.md Section 3"
evidence:
  - "docs/testing/acceptance-cases.md#it-quota"
  - "docs/testing/acceptance-cases.md#it-cache"
  - "docs/testing/acceptance-cases.md#st-fr10"
uncertainty:
  - "TBD-11: Verification of live Google Cloud Console method cost deductions against documented baseline"
  - "Dynamic daylight saving time boundary handling (PST UTC-8 vs PDT UTC-7) for exact midnight Pacific rollover"
---

# Quota Budget Management, Caching Strategy, and Dry-Run Estimation

## 1. Executive Summary and Baseline Allocations

Google Cloud Platform allocates a standard default quota of **10,000 general units per day** for YouTube Data API v3 projects. Because `search.list` consumes 100 units per invocation, unconstrained discovery can rapidly exhaust a project's daily quota in 100 search queries. 

FocusList implements strict local quota governance per requirements **FR-10.1–FR-10.9** and **NFR-QUOTA-01**:
1. **Dual Daily Budgets**: The server tracks two distinct counters:
   - **General Quota Units**: 10,000 units baseline per Pacific day.
   - **Search Call Allowance**: 100 search calls baseline per Pacific day.
2. **5% Safety Reserve**: A mandatory 5% buffer (500 units) is retained. Operations are rejected if projected spend exceeds 9,500 units, preventing unexpected mid-workflow quota exhaustion.
3. **Per-Request Cap**: A hard cap of **2,600 general units** per single tool operation prevents runaway workflows from draining more than 26% of daily quota in one invocation.
4. **Scheduled Live CI Cap**: The scheduled live smoke workflow operates under an enforced ceiling of **500 units and 5 searches** per run.
5. **Pacific Time Reset**: Daily counters reset at midnight Pacific Time (`America/Los_Angeles`), synchronized with Google Cloud's quota rollover schedule.

---

## 2. Baseline Method Costs and Operation Bounds (TBD-11)

The following baseline costs govern all local cost estimations and reservations. These allocations represent the baseline for **TBD-11**, scheduled for verification in C19 and final rechecking in C31:

### Baseline Per-Method Cost Matrix
| API Method | Target Resource | Quota Units | Search Increment | Cacheable? |
| :--- | :--- | :---: | :---: | :---: |
| `videos.list` | Videos (up to 50 IDs) | 1 | 0 | Yes (24h) |
| `search.list` | Video / Channel Search | 100 | 1 | No |
| `channels.list` | Channel details / handles | 1 | 0 | Yes (24h) |
| `playlistItems.list`| Uploads / playlist items | 1 | 0 | Yes (6h user / 24h public) |
| `playlists.list` | User or public playlists | 1 | 0 | Yes (6h user / 24h public) |
| `subscriptions.list`| User subscriptions | 1 | 0 | Yes (6h) |
| `videoCategories.list`| Category taxonomy | 1 | 0 | Yes (7d) |
| `playlists.insert` | Create playlist | 50 | 0 | No |
| `playlistItems.insert`| Insert video into playlist | 50 | 0 | No |
| `playlists.delete` | Delete playlist (undo) | 50 | 0 | No |

### Operation Bounds Matrix (SRS Section 3 & NFR-QUOTA-01)
| Tool / Operation | Max Searches | Max General Units (Before Retries) | Breakdown and Rationale |
| :--- | :---: | :---: | :--- |
| `get_video_details` | 0 | 1 | 1 batched `videos.list` call |
| `similar_videos` | 2 | 6 | $\le 2$ searches (200 units avoided if cached), 3 batched video lookups, 1 channel lookup |
| `similar_channels` | 3 | 25 | $\le 3$ searches, channel profile lookups, uploads inspection |
| `recommend_videos` | 3 | 40 | $\le 3$ searches, subscriptions scan, batched candidate details |
| `analyse_engagement` | 0 | 60 | Paged user likes (max 4 pages = 4 units), subscriptions (4 units), playlists (max 50 units) |
| `propose_playlist` | 3 | 15 | $\le 3$ searches, candidate batched details (12 units) |
| `confirm_playlist` ($N$ items) | 0 | $51 + 50 \times N$ | 1 channel check (1) + 1 create (50) + $N$ inserts ($50 \times N$). E.g., $N=12 \implies 651$ units |
| `undo_playlist` (deletion) | 0 | 50 | 1 playlist delete call |
| `analyse_playlist` ($n$ items) | 0 | $2 \times \lceil n/50 \rceil + 1$ | 1 playlist metadata lookup + batched item fetches |
| `estimate_quota` / `status` | 0 | 0 | Pure local computation, zero network requests |

---

## 3. Atomic Pre-Flight Reservation and Dry-Run Estimation

To enforce zero-call rejection (**TQ-6**, **IT-QUOTA**), FocusList adopts an **atomic reservation pattern**:

```
+-------------------------------------------------------------------------------+
|                           Client Tool Invocation                              |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                          1. Dry-Run Cost Estimation                           |
|       - Compute Worst-Case Outbound Calls: N_search, N_units, Max Retries     |
|       - Check for Valid Unexpired Cache Entries (Cost = 0)                    |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                       2. Pre-Flight Budget Validation                         |
|  IF (spend.units > 2600) OR (spend.units > remaining - 500)                   |
|     OR (spend.searches > remaining_searches):                                 |
|     --> REJECT IMMEDIATELY with QUOTA_BUDGET_EXCEEDED                         |
|     --> ZERO OUTBOUND CALLS MADE                                              |
+-------------------------------------------------------------------------------+
                                      |
                                      v (Within Budget)
+-------------------------------------------------------------------------------+
|                      3. Atomic Reservation in SQLite                          |
|       BEGIN IMMEDIATE TRANSACTION;                                            |
|       UPDATE quota_ledger SET reserved_units = reserved_units + spend.units;  |
|       COMMIT;                                                                 |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                         4. Outbound API Execution                             |
|       - Charge Actual Calls / Retries to Ledger                               |
|       - On Upstream 403 quotaExceeded: Mark Bucket Exhausted, Halt Execution  |
|       - Release Unused Reservation Upon Completion                            |
+-------------------------------------------------------------------------------+
```

### Dry Run Tool (`estimate_quota`)
The `estimate_quota` MCP tool accepts a target tool name and its arguments, performing the exact calculation above **locally**. It outputs:
- `estimated_units`: Total worst-case quota units.
- `estimated_searches`: Total search requests required.
- `cache_hits`: Number of items serviced from local cache.
- `feasible`: Boolean indicating whether current budget can accommodate the request.

---

## 4. SQLite Caching Architecture and Retention Lifecycles

Local caching in SQLite (WAL mode, foreign keys enabled, **DB-1 to DB-3**) eliminates redundant external requests:

```sql
CREATE TABLE cache_entries (
    cache_key TEXT PRIMARY KEY,       -- SHA-256 of canonical (method, params, account_scope)
    category TEXT NOT NULL,           -- 'video', 'channel', 'user', 'category'
    account_id TEXT,                  -- Authorised user account ID (NULL for public data)
    response_json TEXT NOT NULL,      -- Serialised JSON response
    created_at INTEGER NOT NULL,      -- UTC Unix epoch seconds
    expires_at INTEGER NOT NULL       -- UTC Unix epoch seconds
);
CREATE INDEX idx_cache_expires ON cache_entries(expires_at);
```

### Time-to-Live (TTL) Hierarchy (FR-11.4)
- **Public Video and Channel Metadata**: 24 hours ($86,400\text{ s}$).
- **Authorised User Data** (Likes, Subscriptions, Playlists): 6 hours ($21,600\text{ s}$).
- **YouTube Category Taxonomy**: 7 days ($604,800\text{ s}$).
- **Hard Upper Retention Cap**: 30 days maximum under any circumstance.

### Cache Maintenance and Purge Rules
1. **Startup & Daily Maintenance**: Expired cache rows are purged at server startup and once daily via a local cleanup task, with zero polling to YouTube.
2. **Account Purge on Logout**: Invoking `focuslist auth logout` or receiving a token revocation immediately deletes all cache entries where `account_id` matches the authenticated subject (**FR-9.7**, **FR-11.6**).
3. **Zero-Quota Guarantee**: Cache hits incur exactly zero quota unit charges and zero search deductions.

---

## 5. Traceability and Verification Plan

- **SRS Requirements**: [FR-10.1–FR-10.9](../../FocusList_SRS_Condensed.docx), [FR-11.4–FR-11.9](../../FocusList_SRS_Condensed.docx), [NFR-QUOTA-01](../../FocusList_SRS_Condensed.docx), [DB-1–DB-3](../../FocusList_SRS_Condensed.docx), [TBD-11](../../FocusList_SRS_Condensed.docx)
- **Commit Plan**: [Section 3](../../FocusList_Commit_Plan.md#3-provider-cache-quota-and-oauth)
- **Planned Test Cases**:
  - [`IT-QUOTA`](../../docs/testing/acceptance-cases.md#it-quota): Verifies budget tracking, atomic reservation, 5% margin, 2,600 cap, and zero calls on rejection.
  - [`IT-CACHE`](../../docs/testing/acceptance-cases.md#it-cache): Verifies TTL enforcement, zero quota on hit, and purge on logout.
  - [`ST-FR10`](../../docs/testing/acceptance-cases.md#st-fr10): MCP system test for `get_quota_status` and `estimate_quota`.

---

## 6. Documented Uncertainties and Next Steps

1. **TBD-11 (Live Method Costs)**: Official docs list `videos.list` as 1 unit and `search.list` as 100 units. Google Cloud Console metrics must be monitored during live smoke tests to confirm no unlisted backend surcharges apply to parameter combinations (e.g. `part=snippet,contentDetails,statistics`).
2. **Daylight Saving Time Transitions**: Pacific Time observes PST (UTC-8) in winter and PDT (UTC-7) in summer. The ledger reset calculation must use `zoneinfo.ZoneInfo("America/Los_Angeles")` rather than a fixed offset to guarantee exact synchronization with Google's quota reset.
