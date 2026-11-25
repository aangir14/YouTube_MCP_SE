# ADR-005: Official YouTube Data API v3 Read Adapter & Endpoint Mapping

- **Status:** Accepted (C13 read-only adapter; write operations deferred to C21/C27/C30)
- **Date:** 2026-11-25 (IST)
- **Owner:** Aangir Doshi (C13)
- **Stakeholders:** Harshil Srivastav (BT2024187), Ayush Patel (BT2024171)
- **Scope:** FR-11, FR-1–FR-4, FR-12, COM-2, COM-5, TQ-2

[Condensed SRS §§3.3, 4.1–4.4, 4.11](../../FocusList_SRS_Condensed.docx) · [C13 plan](../../FocusList_Commit_Plan.md#c13-add-official-youtube-read-operations) · [ADR-001 shared contracts](ADR-001-service-architecture-and-contracts.md) · [Official API design note](../../brain/resources/official-api-provider-design.md)

---

## 1. Endpoint Mapping Table (`VideoProvider` Read Operations)

All Google API client imports (`google.auth`, `googleapiclient.discovery`, `googleapiclient.errors`, `google_auth_httplib2`, `httplib2`) are confined strictly to `src/focuslist/platform/live_provider.py`.

| `VideoProvider` Method | YouTube Data API v3 Endpoint | `part` & Key Parameters | Batch / Page Caps | Scope | Baseline Cost |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `get_video_details(ids)` | `videos.list` | `part="snippet,contentDetails,status,statistics"`, `id=...` | Batches of $\le 50$ IDs | `youtube.readonly` | 1 unit / batch |
| `search_candidates(q, max)` | `search.list` + `videos.list` | `part="snippet"`, `q=...`, `type="video"` | $\le 50$/page, capped at `max` ($\le 150$) | `youtube.readonly` | 100 units / search + 1 / batch |
| `get_channel_details(id/handle)` | `channels.list` | `part="snippet,statistics,topicDetails"`, `id=...` or `forHandle=...` | Single item | `youtube.readonly` | 1 unit |
| `get_channel_recent_uploads(cid, max)` | `channels.list` + `playlistItems.list` + `videos.list` | `contentDetails` (`uploads` playlist) $\rightarrow$ `playlistItems.list` | Capped at `max` ($\le 50$) | `youtube.readonly` | 1 + 1 + 1 units |
| `get_user_likes(account, max)` | `videos.list` | `part="snippet"`, `myRating="like"` | $\le 50$/page, max 4 pages ($\le 200$) | `youtube.readonly` | 1 unit / page |
| `get_user_subscriptions(account, max)` | `subscriptions.list` | `part="snippet"`, `mine=True` | $\le 50$/page, max 4 pages ($\le 200$) | `youtube.readonly` | 1 unit / page |
| `get_user_playlists(account, max)` | `playlists.list` | `part="snippet,contentDetails,status"`, `mine=True` | Capped at `max` ($\le 50$) | `youtube.readonly` | 1 unit |
| `get_categories(region)` | `videoCategories.list` | `part="snippet"`, `regionCode=...` | Single page | `youtube.readonly` | 1 unit |
| `check_channel_eligibility(account)` | `channels.list` | `part="id"`, `mine=True` | Single check | `youtube.readonly` | 1 unit |

---

## 2. Transport, Attempt Accounting, and Error Mapping

1. **Verified TLS & Shared Timeout**: When no custom `http_transport` is injected for testing, `LiveVideoProvider` builds `httplib2.Http(timeout=settings.request_timeout_seconds, disable_ssl_certificate_validation=False)` wrapped with `google_auth_httplib2.AuthorizedHttp`.
2. **Attempt Accounting (for C19)**: Every outbound `request.execute()` increments `network_attempts` and invokes the optional `attempt_observer(endpoint_name, 1)` callback before execution so C19's quota gateway sees every page and retry attempt.
3. **Safe Error Mapping (No Raw Bodies)**:
   - `401` $\rightarrow$ `AuthExpiredError`
   - `403` (`quotaExceeded` / `dailyLimitExceeded`) $\rightarrow$ `QuotaExhaustedError`
   - `403` (`rateLimitExceeded` / `userRateLimitExceeded`) or `429` $\rightarrow$ `RateLimitedError`
   - `403` (other) $\rightarrow$ `AuthRequiredError`
   - `404` $\rightarrow$ `ChannelUnavailableError` (channel calls) or `VideoUnavailableError`
   - `503` $\rightarrow$ `UpstreamUnavailableError`
   - Other HTTP errors / malformed responses $\rightarrow$ `UpstreamFailureError`
   - `TimeoutError` / `socket.timeout` $\rightarrow$ `NetworkTimeoutError`
4. **Developer Fixture Recorder (`src/focuslist/platform/recorder.py`)**: Uses an explicit allowlist of public fields, sanitizes untrusted strings, and rejects any payload matching raw OAuth tokens or authorization headers (`Bearer `, `access_token`, `refresh_token`, `client_secret`, `ya29.`).
