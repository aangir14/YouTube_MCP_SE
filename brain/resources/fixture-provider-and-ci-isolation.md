---
title: Synthetic Fixture Provider, Fault Injection, and CI Isolation
author: Aangir Doshi
date: 2026-11-19
type: research-note
status: active
srs_ids:
  - FR-11.1
  - FR-11.2
  - FR-11.3
  - TQ-1
  - TQ-2
  - TQ-3
  - TQ-4
  - TQ-5
  - TQ-6
  - NFR-SEC
  - COM-5
  - COM-6
sources:
  - "FocusList_SRS_Condensed.docx Section 4.11, 6.6, TQ-1 to TQ-6"
  - "FocusList_Commit_Plan.md Section 3 & Section 6"
  - "Project_1_YouTube_MCP.pdf (Testing & Security Constraints)"
evidence:
  - "docs/testing/acceptance-cases.md#ci-fixture"
  - "docs/testing/acceptance-cases.md#ci-live"
  - "docs/testing/acceptance-cases.md#it-provider"
  - "docs/testing/acceptance-cases.md#neg-upstream"
uncertainty:
  - "Synthetic nextPageToken encoding format fidelity compared to Google's opaque base64 tokens"
  - "Accurate simulation of Google transient connection drops (TCP reset vs HTTP 503) across OS platforms"
---

# Synthetic Fixture Provider, Fault Injection, and CI Isolation

## 1. Architectural Motivation and Testing Isolation

FocusList relies on an external, quota-metered, and authenticated third-party service (YouTube Data API v3). Relying on live API endpoints during daily development and Continuous Integration (CI) introduces severe risks:
1. **Quota Depletion**: Automated pull-request runs could drain the 10,000-unit daily quota in minutes, leaving the team unable to develop or demonstrate.
2. **Flakiness and Non-Determinism**: Upstream network latency, transient 503 errors, and changing YouTube search rankings prevent reproducible automated testing.
3. **Credential Leaks**: Distributing live OAuth client secrets and refresh tokens across pull-request runners creates security vulnerabilities.

To satisfy **FR-11.1–FR-11.3**, **TQ-5**, and **NFR-SEC**, FocusList enforces a strict **two-tier execution model**:
- **Tier 1 (Default): Offline Synthetic Fixture Mode**: Used for all local unit, integration, and MCP system tests, and enforced across all pull-request CI workflows.
- **Tier 2 (Controlled): Scheduled Live Smoke Mode**: Isolated in a separate, scheduled workflow with dedicated secrets and an enforced quota ceiling of 500 units and 5 searches.

```
+-------------------------------------------------------------------------------+
|                       Testing Execution Environments                          |
+-------------------------------------------------------------------------------+
           |                                                      |
           v                                                      v
+--------------------------------------+     +----------------------------------+
|      Pull-Request CI & Local Dev     |     |   Scheduled Live Smoke Workflow  |
| - FOCUSLIST_PROVIDER=fixture         |     | - Scheduled cron or manual owner |
| - ZERO network requests allowed      |     | - Authorized test Google account |
| - ZERO credentials required          |     | - Strict 500-unit / 5-search cap |
| - Replays synthetic JSON fixtures    |     | - Validates real Google endpoints|
| - Uses FaultInjectionProvider        |     | - Secrets stored in repo secrets |
+--------------------------------------+     +----------------------------------+
```

---

## 2. Fixture Provider Architecture (`FixtureVideoProvider`)

The `FixtureVideoProvider` implements the complete `VideoProvider` protocol using static, deterministic JSON files stored under `tests/fixtures/`:

```python
class FixtureVideoProvider(VideoProvider):
    """Deterministic offline provider reading from synthetic test datasets."""

    def __init__(self, fixture_dir: Path):
        self.fixture_dir = fixture_dir
        self.call_counts: dict[str, int] = defaultdict(int)

    async def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        self.call_counts["videos.list"] += 1
        # Replay matching synthetic records from local JSON
        ...
```

### Synthetic Data Seeding Guarantees
1. **Completely Synthetic Identifiers**: Video IDs use synthetic patterns (e.g. `syn_vid_0001`, `syn_vid_0002`), channel IDs use `UCsyn_chan_001`, and user account IDs use `synthetic_user_001`.
2. **Absolute Exclusion of Real User Data**: No real personal names, private playlist titles, watch histories, or actual Google access tokens exist in fixture datasets (**BR-9**, **SEC-SECRETS**).
3. **Diverse Edge-Case Coverage**:
   - Videos with missing descriptions, missing tags, or non-English titles.
   - Restricted items (age-restricted, live streams, upcoming broadcasts, deleted tombstones).
   - Candidate sets with near-duplicate titles (cosine similarity $\ge 0.90$) to exercise deduplication.
   - Varied durations (from 30 seconds to 3 hours) to test solver constraint satisfaction.

---

## 3. Fault Injection Wrapper (`FaultInjectionProvider`)

To fulfill **FR-11.3** and **TQ-4**, developers must be able to reproduce rare upstream failures deterministically without waiting for live Google outages. The `FaultInjectionProvider` wraps any underlying provider to inject simulated failures:

```
+-------------------------------------------------------------------------------+
|                           FaultInjectionProvider                              |
+-------------------------------------------------------------------------------+
|  Configured Fault Rules:                                                      |
|   - Fail next N calls with HTTP 500 (transient server error)                  |
|   - Throw NetworkTimeout after 15 seconds                                     |
|   - Simulate HTTP 403 quotaExceeded on search.list                            |
|   - Simulate HTTP 401 invalid_grant on token refresh                          |
|   - Return corrupt or malformed JSON payload                                  |
|   - Return HTTP 403 youtubeSignupRequired (no YouTube channel)                |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|     Underlying Provider (FixtureVideoProvider or Mock Transport)              |
+-------------------------------------------------------------------------------+
```

### Verified Failure Scenarios
- **Transient 5xx Backoff (COM-5)**: Simulates 2 consecutive 503 errors followed by HTTP 200 to verify exponential backoff with jitter.
- **Quota Exhaustion**: Injects HTTP 403 `quotaExceeded` on call 1; asserts that local quota bucket is immediately marked exhausted and retries are halted (**COM-6**).
- **Missing Channel**: Injects HTTP 403 `youtubeSignupRequired` during playlist creation; verifies mapping to `NO_YOUTUBE_CHANNEL` (**FR-9.8**).
- **Token Invalidation**: Injects `invalid_grant`; verifies mapping to `AUTH_EXPIRED` without infinite retry loops (**FR-9.4**).

---

## 4. Pull-Request CI Isolation and Network Guardrails

The team's CI pipeline enforces strict environmental isolation:
1. **Enforced Environment Variable**: All PR test commands execute with `FOCUSLIST_PROVIDER=fixture` and `FOCUSLIST_TEST_MODE=offline`.
2. **Socket Mocking / Network Prohibition**: Automated tests configure socket monkey-patching or `pytest-block-network` to intercept any outbound TCP connection attempt to non-loopback addresses. Any attempt to reach `www.googleapis.com` or external IPs immediately causes test failure (**CI-FIXTURE**).
3. **Zero Secrets in Runner**: Pull-request workflows run with no access to repository secrets or Google API keys.
4. **Fast and Lightweight**: Offline test suites must execute in $< 120$ seconds on GitHub-hosted Ubuntu runners (**SRS Quality Targets**).

---

## 5. Traceability and Verification Plan

- **SRS Requirements**: [FR-11.1–FR-11.3](../../FocusList_SRS_Condensed.docx), [TQ-1 to TQ-6](../../FocusList_SRS_Condensed.docx), [NFR-SEC](../../FocusList_SRS_Condensed.docx), [COM-5–COM-6](../../FocusList_SRS_Condensed.docx)
- **Commit Plan**: [Section 3 & Section 6](../../FocusList_Commit_Plan.md#6-testing-skills-and-release-evidence)
- **Planned Test Cases**:
  - [`CI-FIXTURE`](../../docs/testing/acceptance-cases.md#ci-fixture): Offline test execution, network isolation, and synthetic fixture validation.
  - [`CI-LIVE`](../../docs/testing/acceptance-cases.md#ci-live): Separate scheduled smoke test under enforced 500-unit ceiling.
  - [`IT-PROVIDER`](../../docs/testing/acceptance-cases.md#it-provider): Integration testing of provider interface and fault wrapper.
  - [`NEG-UPSTREAM`](../../docs/testing/acceptance-cases.md#neg-upstream): Deterministic fault simulation and retry policy verification.

---

## 6. Documented Uncertainties and Next Steps

1. **Synthetic `nextPageToken` Semantics**: Google uses opaque base64-encoded protobuf tokens for pagination. The fixture provider will use simple offset-based strings (e.g. `page_2_offset_50`), and tests must ensure higher-level components treat tokens as opaque blobs without inspecting internal contents.
2. **Transient Connection Drop Simulation**: Simulating broken socket pipes (`ConnectionResetError`) versus HTTP 503 response codes requires testing both low-level transport exceptions and high-level HTTP client error handling.
