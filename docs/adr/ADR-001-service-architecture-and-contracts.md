# ADR-001: Python MCP Service Architecture, Shared Data Contracts, and Boundary Isolation

- **Status**: Accepted
- **Date**: 2026-11-23 (IST)
- **Author**: Aangir Doshi (BT2024078)
- **Stakeholders**: Harshil Srivastav (BT2024187), Ayush Patel (BT2024171)
- **Requirements Satisfied**: SRS UI-1–UI-5, COM-1–COM-6, FR-11, NFR-PORT, DB-1–DB-3

---

## 1. Context and Problem Statement

FocusList 1.0 is an intelligent YouTube discovery, account analytics, and playlist curation assistant implemented as a local Model Context Protocol (MCP) server. To ensure high code quality, parallel development across three team members, and seamless interoperability with AI clients, the service requires:
1. A clean, reproducible Python 3.11+ packaging setup.
2. A strict boundary isolating external Google API client dependencies from core feature logic (**FR-11.2**).
3. Pinned shared data models and response envelopes so feature owners (Harshil for discovery/ranking, Ayush for curation/solver) can build without contract friction (**Section 2**).
4. A deterministic error registry with stable error codes and remediation hints (**UI-4**, **UI-5**).
5. A deterministic clock seam for time-dependent operations (token expiration, cache TTLs, quota rollovers).

---

## 2. Decision Outcomes

### 2.1 FastMCP and JSON-RPC 2.0 over Stdio (COM-1, COM-2)
- **Choice**: Official Model Context Protocol Python SDK (`mcp.server.fastmcp.FastMCP`).
- **Rationale**: FastMCP auto-generates JSON Schema specifications directly from Python type hints and Pydantic models, supports typed tools, resources, and prompt templates, and enforces JSON-RPC 2.0 standard compliance.
- **Stdio Hygiene Rule**: Standard output (`sys.stdout`) is reserved **strictly and exclusively** for MCP JSON-RPC protocol frames. All diagnostic logging, error traces, and operational banners must write to `sys.stderr` or sanitized log files (**COM-1**).

### 2.2 Layered Package Layout
The repository is structured into distinct functional boundaries:
```
src/focuslist/
├── __init__.py           # Package version and root exports
├── config.py             # Pydantic BaseSettings, central defaults, environment parsing
├── clock.py              # Injectable Clock protocol, SystemClock, FakeClock
├── types.py              # Pinned Pydantic shared data models and response envelopes
├── errors.py             # Stable ErrorCode enum, ErrorRegistry, domain exceptions
├── context.py            # RequestContext / CallContext carrying injected dependencies
├── server.py             # FastMCP server setup, tool registrations, resources, prompts
├── cli.py                # Typer CLI providing serve, doctor, quota, auth, purge
├── platform/             # VideoProvider protocol, Live, Fixture, and Fault implementations
├── discovery/            # Candidate retrieval, TF-IDF ranking, channel resolution (Harshil)
└── curation/             # Duration constraint solver, proposal signing, confirmation (Ayush)
```

### 2.3 Shared Record Schemas (Section 2)
The following core data contracts are locked:

| Record Name | Key Fields | Description |
| :--- | :--- | :--- |
| **`VideoRecord`** | `video_id`, `canonical_url`, `title`, `channel_id`, `channel_title`, `description`, `duration_seconds`, `duration_iso`, `published_at`, `view_count`, `like_count`, `untrusted` | Metadata fact sheet representation. Strips control characters and truncates descriptions to $\le 500$ characters. |
| **`ChannelRecord`** | `channel_id`, `canonical_url`, `title`, `handle`, `description`, `topic_categories`, `subscriber_count`, `video_count`, `untrusted` | Channel metadata and public upload references. |
| **`AccountActivityRecord`** | `item_id`, `activity_type`, `account_id`, `timestamp`, `timestamp_provenance`, `channel_id` | User activity events (likes, subscriptions, playlists) with explicit provenance. |
| **`RankedItemRecord`** | `item_id`, `title`, `score`, `rank`, `reason`, `components`, `shared_terms`, `missing_fields`, `low_confidence` | Normalized scored candidate with multi-factor weights and shared terms. |
| **`ProposalRecord`** | `proposal_id`, `action_kind`, `title`, `ordered_video_ids`, `total_duration_seconds`, `item_count`, `privacy_status`, `estimated_units`, `expires_at`, `canonical_hash`, `token`, `state` | Immutable proposal binding an actionable playlist creation or edit. |
| **`QuotaStatusRecord`** | `pacific_date`, `units_used`, `units_remaining`, `searches_used`, `searches_remaining`, `cache_hits`, `is_exhausted`, `reset_time_utc` | Daily ledger counters tracking 10,000 units and 100 search allocations. |

### 2.4 Standard Response Envelopes (COM-4)
All MCP tools return structured payloads matching standard envelopes:
- **Success Envelope (`ResultEnvelope`)**:
  ```json
  {
    "result": { ... },
    "meta": {
      "quota_used": 6,
      "quota_remaining": 9994,
      "cache_hits": 0,
      "provider": "fixture",
      "warnings": []
    }
  }
  ```
- **Error Envelope (`ErrorEnvelope`)**:
  ```json
  {
    "error": {
      "code": "QUOTA_BUDGET_EXCEEDED",
      "message": "The requested workflow exceeds the allowable quota allowance.",
      "remediation": "Reduce candidate limits or await daily quota reset at midnight Pacific.",
      "retryable": false,
      "details": {}
    },
    "meta": {
      "quota_used": 0,
      "quota_remaining": 500,
      "cache_hits": 0,
      "provider": "fixture",
      "warnings": []
    }
  }
  ```

### 2.5 Pinned Tool Error Registry (UI-4, UI-5)
The 18 canonical error codes are pinned:
1. `INVALID_VIDEO_ID` (Non-retryable)
2. `INVALID_CHANNEL_ID` (Non-retryable)
3. `INVALID_ARGUMENTS` (Non-retryable)
4. `VIDEO_UNAVAILABLE` (Non-retryable)
5. `CHANNEL_UNAVAILABLE` (Non-retryable)
6. `QUOTA_BUDGET_EXCEEDED` (Non-retryable)
7. `QUOTA_EXHAUSTED` (Non-retryable)
8. `RATE_LIMITED` (Retryable)
9. `AUTH_REQUIRED` (Non-retryable)
10. `AUTH_EXPIRED` (Non-retryable)
11. `AUTH_CANCELLED` (Non-retryable)
12. `NO_YOUTUBE_CHANNEL` (Non-retryable)
13. `CONFIRMATION_INVALID` (Non-retryable)
14. `CONFIRMATION_EXPIRED` (Non-retryable)
15. `PARTIALLY_CREATED` (Retryable with resume)
16. `UPSTREAM_FAILURE` (Retryable)
17. `UPSTREAM_UNAVAILABLE` (Retryable)
18. `NETWORK_TIMEOUT` (Retryable)

### 2.6 Injectable Clock Seam (`Clock`)
Time is treated as an explicit dependency. The abstract `Clock` protocol exposes `now() -> datetime` (timezone-aware UTC) and `now_epoch() -> int`. In production, `SystemClock` reads system time; in automated testing, `FakeClock` allows advancing time deterministically to verify token expiry and quota resets without system sleeps.

---

## 3. Solo Setup and Developer Commands

To bootstrap the local development environment from a fresh clone:

```bash
# 1. Create and activate a Python 3.11+ virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\Activate.ps1

# 2. Install package in editable mode with development dependencies
pip install -e ".[dev]"

# 3. Verify installation with system diagnostic doctor
focuslist doctor

# 4. Run automated test suite in offline fixture mode
pytest -v

# 5. Check code formatting and linting
ruff check .

# 6. Inspect CLI help
focuslist --help
focuslist quota
focuslist auth status

# 7. Start the MCP server over stdio
focuslist serve
```

---

## 4. Consequences and Downstream Alignment

- **For Harshil (C08/C11/C14)**: Discovery and scoring algorithms can import `VideoRecord`, `ChannelRecord`, `RankedItemRecord`, and `VideoProvider` directly without coupling to any networking or CLI code.
- **For Ayush (C09/C12/C15)**: The duration solver and proposal generator can build against `ProposalRecord`, `format_duration_display()`, and `FakeClock`.
- **For Platform & Security (Aangir)**: Google client imports remain strictly segregated in `src/focuslist/platform/live_provider.py`, preventing accidental credentials leakage or mock pollution.
