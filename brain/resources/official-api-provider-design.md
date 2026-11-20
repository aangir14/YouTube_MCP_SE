---
title: Official YouTube Data API v3 and VideoProvider Architecture
author: Aangir Doshi
date: 2026-11-19
type: research-note
status: active
srs_ids:
  - FR-11.1
  - FR-11.2
  - FR-11.3
  - FR-1.9
  - COM-1
  - COM-2
  - COM-3
  - COM-4
  - COM-5
  - COM-6
sources:
  - "https://developers.google.com/youtube/v3/docs"
  - "https://developers.google.com/youtube/v3/docs/videos/list"
  - "https://developers.google.com/youtube/v3/docs/search/list"
  - "https://developers.google.com/youtube/v3/docs/channels/list"
  - "https://developers.google.com/youtube/v3/docs/playlists/insert"
  - "https://developers.google.com/youtube/v3/docs/playlistItems/insert"
  - "https://developers.google.com/youtube/v3/determine_quota_cost"
evidence:
  - "docs/testing/acceptance-cases.md#it-provider"
  - "docs/testing/acceptance-cases.md#st-fr11"
  - "docs/testing/acceptance-cases.md#neg-upstream"
uncertainty:
  - "Upstream per-second write burst limits beyond nominal 50-unit quota cost for playlist inserts"
  - "Exact JSON structure of tombstone/placeholder items for deleted versus private videos in batched videos.list queries"
---

# Official YouTube Data API v3 and VideoProvider Architecture

## 1. Architectural Scope and Boundaries

FocusList is designed around an explicit architectural boundary for all external YouTube communication. Per requirements **FR-11.1–FR-11.3** and **Implementation Plan Section 1 & Section 3**, direct interaction with Google's REST services is strictly isolated behind an abstract `VideoProvider` protocol located in `src/focuslist/platform/`.

```
+--------------------------------------------------------------------------+
|                            MCP Client Layer                              |
|         (JSON-RPC 2.0 stdio, Tool Handlers, Parameter Validation)        |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                         Feature & Service Layer                          |
|         (Discovery, Ranking, Curation Solver, Proposal Generator)        |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                  Platform Gateway (Cache & Quota Guard)                  |
|    - SQLite Cache Lookup (Zero-Quota Hit)                                |
|    - Atomic Quota Reservation & Pre-Flight Check                         |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                         VideoProvider Interface                          |
|        +---------------------------+---------------------------+         |
|        |                           |                           |         |
|        v                           v                           v         |
|  LiveVideoProvider        FixtureVideoProvider       FaultInjectionProvider|
|  (Google API Client       (Local Synthetic Data      (Simulates Timeouts,  |
|   OAuth TLS 1.2+)          Deterministic Replay)      429, 500, QuotaErr)  |
+--------------------------------------------------------------------------+
```

### Core Design Rules
1. **Confined Dependencies**: Imports of `google-api-python-client`, `google-auth`, and `google-auth-oauthlib` are permitted **only** inside `src/focuslist/platform/`. Higher layers (discovery, curation, analytics, server) depend exclusively on typed data records (`VideoRecord`, `ChannelRecord`, `ProposalRecord`) and domain interfaces.
2. **Protocol Cleanliness**: The MCP server uses `stdio` strictly for JSON-RPC 2.0 protocol traffic (**COM-1**). All YouTube provider logs, diagnostics, and HTTP trace information are directed to `stderr` or a sanitized, rotating local log file.
3. **No Web Scraping**: In strict compliance with course constraints, project terms, and Developer Policies, FocusList employs official API endpoints exclusively. Unofficial endpoints, HTML scraping, transcript ripping, or private internal APIs are completely prohibited.

---

## 2. API Operations, Endpoints, and Batching Dynamics

The official YouTube Data API v3 employs a resource-oriented architecture. To minimize quota consumption and ensure predictable performance, operations are selected and batched according to specific endpoint characteristics:

| Domain Operation | Official REST Endpoint | HTTP Method | Quota Cost | Batching Capacity & Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Video Fact Sheet & Details** | `/youtube/v3/videos` | `GET` | 1 unit | Up to 50 video IDs per call (`id=id1,id2,...`). Fixed 1 unit cost regardless of batch size. |
| **Candidate Search** | `/youtube/v3/search` | `GET` | 100 units | Max 50 results per page (`type=video`). Capped at 2–3 searches per discovery workflow. |
| **Channel Resolution** | `/youtube/v3/channels` | `GET` | 1 unit | By channel ID (`id=UC...`) or handle (`forHandle=@...`). Returns snippets and statistics. |
| **Channel Uploads / Activity** | `/youtube/v3/playlistItems` | `GET` | 1 unit | Fetches uploads playlist (`UU...` derived from channel ID). 50 items/page. |
| **User Likes** | `/youtube/v3/videos` | `GET` | 1 unit | `myRating=like` with `part=snippet,contentDetails`. Paged up to 200 items. |
| **User Subscriptions** | `/youtube/v3/subscriptions`| `GET` | 1 unit | `mine=true` with `part=snippet`. Paged up to 200 items. |
| **Category List** | `/youtube/v3/videoCategories` | `GET` | 1 unit | Region-specific category catalog (`regionCode=US`). Cached for 7 days. |
| **Playlist Creation** | `/youtube/v3/playlists` | `POST` | 50 units | Single creation call with title, description, and `privacyStatus=private`. |
| **Playlist Item Insertion** | `/youtube/v3/playlistItems` | `POST` | 50 units | One call per item. Ordered sequential inserts; rate-paced at $\le 1$ insert/second. |
| **Playlist Deletion (Undo)** | `/youtube/v3/playlists` | `DELETE`| 50 units | Confirmed undo of FocusList-created playlist ID. |

### The Power of Batched `videos.list`
A critical efficiency mechanism in FocusList is candidate batching. While `search.list` costs 100 quota units and returns limited snippet data, `videos.list` costs only **1 unit** for up to 50 IDs and returns full `contentDetails` (ISO-8601 duration, caption availability, definitions) and `statistics` (view counts, like counts).
- *Implementation Strategy*: The discovery service performs 2 searches (generating up to 100 candidate IDs), deduplicates them, and issues at most 2–3 batched `videos.list` calls (total general units: 2–3 units).

---

## 3. Rate Limiting and Inter-Request Pacing

While Google Cloud Platform tracks daily quota units, YouTube Data API endpoints also enforce short-term concurrency and request-rate limits:
- **Write Cadence**: Creating a playlist and inserting 12 items requires 13 consecutive `POST` requests (650 quota units). Sending these in a burst can trigger HTTP 429 (`rateLimitExceeded`) or transient backend 503 errors.
- **Pacing Rule**: All write sequences must enforce an inter-request delay of $\ge 1.0$ second between consecutive write operations (**Commit Plan Section 5.6**).
- **Transient Retries (COM-5)**: In accordance with **COM-5**, transient 5xx errors and network timeouts are retried up to 3 times with exponential backoff and randomized jitter:
  $$T_{\text{wait}} = 2^{\text{attempt}} + \text{random\_uniform}(0, 1)$$
  No write operation with an ambiguous remote outcome may be blindly retried without prior state reconciliation.

---

## 4. Untrusted External Metadata Handling

All text returned by the YouTube Data API (`snippet.title`, `snippet.description`, `snippet.channelTitle`, `snippet.tags`) originates from external video uploaders and must be treated as **untrusted data**:

1. **Sanitization**: All external strings are sanitized before being processed, displayed, or persisted:
   - Control characters (`\x00`–`\x1F`, `\x7F`–`\x9F`) and zero-width spaces (`\u200B`, `\uFEFF`) are stripped.
   - Video descriptions are truncated to a hard maximum of 500 characters.
2. **Explicit Labeling**: Tool responses mark remote metadata fields as untrusted in response contracts.
3. **Prompt Injection Defense**: Under no circumstances may text contained within video titles, tags, or descriptions alter tool dispatch, override system prompts, or bypass the mandatory human confirmation gate (**FR-7.6–7.9**, **SEC-APPROVAL**).

---

## 5. Domain Error Mapping

The `VideoProvider` translates all low-level HTTP and Google client exceptions into stable domain errors:

| HTTP Status / Google Reason | FocusList Error Code | Retryable? | Remediation / Expected Action |
| :--- | :--- | :---: | :--- |
| `400` / `badRequest` | `INVALID_VIDEO_ID` | No | Validate input format (11-char regex) before call. |
| `401` / `invalid_grant` | `AUTH_EXPIRED` | No | Prompt user to run `focuslist auth login`. |
| `403` / `quotaExceeded` | `QUOTA_EXHAUSTED` | No | Mark local bucket exhausted until midnight Pacific. |
| `403` / `rateLimitExceeded` | `RATE_LIMITED` | Yes | Back off exponentially, then retry within budget. |
| `403` / `youtubeSignupRequired` | `NO_YOUTUBE_CHANNEL` | No | Guide user to create a YouTube channel on their account. |
| `404` / `videoNotFound` | `VIDEO_UNAVAILABLE` | No | Filter item out of ranking/curation set. |
| `500` / `backendError` | `UPSTREAM_FAILURE` | Yes | Exponential backoff (max 3 retries, COM-5). |
| `503` / `serviceUnavailable`| `UPSTREAM_UNAVAILABLE`| Yes | Exponential backoff (max 3 retries, COM-5). |
| Network Timeout (>15s) | `NETWORK_TIMEOUT` | Yes | Check connection; retry if within operation budget. |

---

## 6. Traceability and Verification Tasks

- **SRS Requirements**: [FR-11.1–FR-11.3](../../FocusList_SRS_Condensed.docx), [FR-1.9](../../FocusList_SRS_Condensed.docx), [COM-1 to COM-6](../../FocusList_SRS_Condensed.docx)
- **Commit Plan**: [Section 1 & Section 3](../../FocusList_Commit_Plan.md#3-provider-cache-quota-and-oauth)
- **Test Scenarios**:
  - [`IT-PROVIDER`](../../docs/testing/acceptance-cases.md#it-provider): Integration testing of `VideoProvider` abstraction with mock transports.
  - [`ST-FR11`](../../docs/testing/acceptance-cases.md#st-fr11): System verification of provider switching and offline mode.
  - [`NEG-UPSTREAM`](../../docs/testing/acceptance-cases.md#neg-upstream): Upstream error translation and recovery.

---

## 7. Documented Uncertainties and Open Questions

1. **Write Burst Throttling**: Official documentation specifies daily quota consumption (50 units/insert) but does not publish exact burst QPS limits for `playlistItems.insert`. The conservative 1 req/sec pacing policy must be validated during Stage 3 integration.
2. **Tombstone Representation**: Deleted videos in batched queries may either return an empty `items` array element or a partial item with empty snippets. The provider parser must robustly handle missing or null snippet blocks without failing the batch.
