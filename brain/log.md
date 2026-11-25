# FocusList Second Brain Activity Log

This append-only log tracks additions, modifications, decision milestones, and significant AI-assisted development sessions within the FocusList Second Brain (`brain/`), fulfilling **SB-1 to SB-6** and **SE-5**.

---

## Chronological Change Log

### 2026-11-25 · Commit C12: Pure Playlist Constraint Solver & Proposal Schema
- **Author**: Ayush Patel (BT2024171)
- **Commit Reference**: C12 (`feat(curation): establish playlist constraints and solver tests`)
- **SRS Scope**: FR-5.1–5.8, FR-5.15, NFR-REL, TQ-1
- **Changes Delivered**:
  1. **Proposal Argument Schema & Validators**: Added `PlaylistProposalRequest`, `ValidatedPlaylistConstraints`, and `validate_proposal_arguments` (`src/focuslist/curation/constraints.py`) reusing C11's `parse_duration_seconds`, `normalise_language_tag`, and `parse_video_id`. Rejects unknown fields, out-of-range caps, and contradictory bounds before any discovery call.
  2. **Pure Deterministic Duration Solver & FR-5 Scorer**: Added `solve_playlist`, `filter_eligible_candidates`, `score_candidates_fr5` (`0.65/0.10/0.10/0.10/0.05` with objective non-engagement `capped_quality`), and `greedy_baseline_select` (`src/focuslist/curation/solver.py`). Returns explicit feasible or nearest-infeasible `SolverResult` with unmet constraint breakdowns.
  3. **Boundary, Baseline & Property Tests**: Added `tests/unit/test_curation_constraints_and_solver.py` (22 tests including 250 randomized property cases) and documented baseline comparison & Stage 2 evidence in `docs/testing/curation-solver-baseline.md`.

### 2026-11-25 · Commit C10: Deterministic Fixture Provider, Fault Injection, and MCP Stdio Harness
- **Author**: Aangir Doshi (BT2024078)
- **Commit Reference**: C10 (`feat(testkit): add the fixture provider and MCP harness`)
- **SRS Scope**: FR-9, FR-11, TQ-2–TQ-5, TBD-2, TBD-6
- **Changes Delivered**:
  1. **Deterministic Fixture Provider & Counters**: Enhanced `FixtureVideoProvider` with deterministic ID-sorted outputs, `requests`, `network_attempts`, `writes`, `call_log`, and `reset_counters()`.
  2. **Normalized Fault Injection**: Extended `FaultInjectionProvider` with `NORMALIZED_FAULT_MAP` and `inject_normalized_fault()` covering quota, rate, unavailable, timeout, no_channel, auth, and upstream 500/503 faults, distinguishing preflight rejections from outbound attempts.
  3. **Scripted Stdio MCP Test Harness**: Added `McpStdioTestClient` (`tests/mcp_harness.py`) and `tests/system/test_mcp_stdio_harness.py` exercising real subprocess startup, JSON-RPC handshake, capability listing, fixture selection, stderr/stdout isolation, and clean teardown.
  4. **ADR-003 (TBD-6 & TBD-2)**: Documented minimum writable OAuth scope analysis (`youtube.force-ssl` vs `youtube`, live check pending C22) and offline MCP elicitation capability evidence (live AI-client UI check pending C24).

### 2026-11-25 · Commit C09: Playlist Action Lifecycle and Threat Model ADR
- **Author**: Ayush Patel (BT2024171)
- **Commit Reference**: C09 (`docs(design): specify the playlist action lifecycle`)
- **SRS Scope**: FR-5, FR-7, FR-8, NFR-SAF, NFR-SEC, DB-2, DB-3
- **Summary**: Authored [`docs/adr/ADR-004-playlist-action-lifecycle-and-threat-model.md`](../docs/adr/ADR-004-playlist-action-lifecycle-and-threat-model.md) defining the full curation state machine (`proposed`, `expired`, `superseded`, `confirmed`, `creating`, `completed`, `partially_created`, `resuming`, `undone`), separation of proposal/approval/write rights, canonical proposal fields and HMAC-SHA-256 signing, elicitation and conversational approval paths, idempotent replay, ambiguous timeout reconciliation, deterministic DP selection objective with objective `capped_quality` (FR-5 weights `0.65/0.10/0.10/0.10/0.05`), FR-8 diversity/ordering, and an 8-threat security model (`TM-01`–`TM-08`).

### 2026-11-25 · Commit C07: Scaffold the Python MCP Service
- **Author**: Aangir Doshi (BT2024078)
- **Commit Reference**: C07 (`chore(build): scaffold the Python MCP service`)
- **SRS Scope**: UI-1–UI-5, COM-1–COM-6, FR-11, NFR-PORT
- **Changes Delivered**:
  1. **Package Setup & Entry Point**: Configured `pyproject.toml` with `focuslist = "focuslist.cli:app"`, dependencies (`mcp`, `pydantic`, `pydantic-settings`, `typer`, `anyio`, `httpx`, `google-api-python-client`, `google-auth`, `google-auth-oauthlib`, `cryptography`), dev dependencies (`pytest`, `pytest-asyncio`, `ruff`), and ruff configuration (`B008` ignore).
  2. **FastMCP Server & Stdio Protocol Isolation**: Created `src/focuslist/server.py` registering 13 tool endpoints, 2 resources (`focuslist://config/scoring`, `focuslist://quota/status`), and 2 prompts (`video-to-playlist`, `playlist-audit`). Enforced strict stderr logging isolation ensuring stdout carries 100% JSON-RPC protocol traffic (COM-1).
  3. **Injectable Seams & Shared Contracts**: Built `src/focuslist/clock.py` (`Clock` protocol, `SystemClock`, `FakeClock`), `src/focuslist/types.py` (`VideoRecord`, `ChannelRecord`, `AccountActivityRecord`, `RankedItemRecord`, `ProposalRecord`, `QuotaStatusRecord`, `MetaEnvelope`, `ResultEnvelope`, `ErrorInfo`, `ErrorEnvelope`, text sanitization, duration formatting), `src/focuslist/context.py` (`RequestContext`), and `src/focuslist/errors.py` (18 pinned `ErrorCode` enums and `ERROR_REGISTRY`).
  4. **Platform Provider Boundary**: Isolated Google API clients to `src/focuslist/platform/live_provider.py` (FR-11.2). Implemented `FixtureVideoProvider` (reading synthetic offline datasets) and `FaultInjectionProvider` (for simulating timeouts, quota depletion, and transient 500/503 errors).
  5. **CLI Administration**: Created `src/focuslist/cli.py` (Typer CLI) exposing `serve`, `doctor`, `quota`, `auth`, `purge`, and `record-fixtures` commands sharing identical provider/clock dependencies.
  6. **Synthetic Test Datasets & Test Suite**: Added `sample_videos.json`, `sample_channels.json`, and `sample_categories.json` under `tests/fixtures/`. Added 33 unit, integration, and system tests passing across `tests/unit/`, `tests/integration/`, and `tests/system/`.
  7. **ADR-001 & Documentation**: Authored `docs/adr/ADR-001-service-architecture-and-contracts.md` pinning architecture, error codes, and setup commands. Updated `README.md` and indexed ADR-001 in `brain/index.md`.

### 2026-11-24 · Commit C06: Requirements Milestone Closure and Stage 1 Review
- **Author**: Ayush Patel (BT2024171)
- **Commit Reference**: C06 (`docs(review): close the requirements milestone`)
- **SRS Scope**: FR-5, FR-7, SK-0, SK-2, SE-5–SE-6, SB-1–SB-6, TBD-10
- **Summary**: Delivered four curation and Agent Skill research notes (`playlist-constraints-and-duration-solver.md`, `proposal-disclosure-and-metadata-sanitization.md`, `confirmation-gate-and-action-lifecycle.md`, `skill-format-and-upstream-specification.md`). Resolved TBD-10 regarding upstream skill format limits. Authored the comprehensive Stage 1 Review (`docs/stage-1-review.md`) verifying coverage across all 5 course FRs, SK-2, and TQ-1–TQ-6 testing requirements. Reconciled all 11 Appendix C TBDs in `brain/index.md` and completed Stage 1 handoff to Stage 2.

### 2026-11-19 · Commit C04: Platform Constraints and Second Brain Initialization
- **Author**: Aangir Doshi (BT2024078)
- **Commit Reference**: C04 (`docs(platform): record provider and credential constraints`)
- **SRS Scope**: FR-9–FR-11, DB-1–DB-3, SB-1–SB-6, TBD-5, TBD-11, NFR-QUOTA-01, NFR-SEC
- **Changes Delivered**:
  1. **Vault Structure Setup**: Created PARA structure (`inbox/`, `projects/`, `areas/`, `resources/`, `archive/`) with `.gitkeep` sentinels and established `brain/README.md` defining frontmatter and governance rules.
  2. **Note Frontmatter Standard**: Formalized YAML schema requiring `title`, `author`, `date`, `type`, `status`, `srs_ids`, `sources`, `evidence`, and `uncertainty`.
  3. **Master Catalog & Log**: Created `brain/index.md` (cross-referencing SRS requirements, planned verification cases, and open decisions) and `brain/log.md`.
  4. **Four Platform Research Notes** (authored by Aangir Doshi):
     - `resources/official-api-provider-design.md`: Official YouTube Data API v3 integration, `VideoProvider` boundary, Google client isolation in `platform/`, endpoint batching dynamics (50 IDs / 1 unit), rate-paced writes ($\le 1$ req/sec), domain error translation, and untrusted metadata sanitization.
     - `resources/quota-budgeting-and-caching.md`: Quota ledger architecture, 10k general unit & 100 search daily budgets with Pacific midnight reset, 5% reserve margin (9,500 effective cap), 2,600 per-request cap, 500-unit / 5-search live CI cap, baseline method cost table (TBD-11), atomic pre-flight reservations, local `estimate_quota` dry run, and SQLite cache TTLs (24h/6h/7d/30d max) with zero-cost hits.
     - `resources/oauth-lifecycle-and-safe-storage.md`: Native OAuth 2.0 with PKCE and loopback interface binding strictly to `127.0.0.1:<ephemeral>` with state CSRF checks; external client credential loading; least-privilege scoping (`youtube.readonly` first, write scope deferred until confirmed write per TBD-6 / ADR-003); OS credential store / `0600` user fallback; zero token logging; 7-day Testing refresh token expiry with day-5 warnings; automatic refresh and `AUTH_EXPIRED` on `invalid_grant`; and immediate token revocation plus authorized cache purge on logout.
     - `resources/fixture-provider-and-ci-isolation.md`: Fully offline `FixtureVideoProvider` replaying synthetic JSON datasets; absolute exclusion of real user data; `FaultInjectionProvider` wrapper for reproducible network/quota/auth faults; strict PR CI isolation with blocked external sockets; and COM-5 retry/backoff validation.
  5. **Licensing Analysis (TBD-5)**: Authored `resources/licensing-and-distribution.md` evaluating MIT vs Apache 2.0 licenses, detailing third-party dependency obligations (`google-api-python-client`, `mcp`), identifying `docs/licenses/` as third-party record location, and maintaining TBD-5 as an open decision for Stage 1 team sign-off.
  6. **Traceability Closure**: Updated `docs/requirements-traceability.md` to link rows previously marked `Pending (C04)` directly to the newly authored research notes.

### 2026-11-18 · Commit C03: Baseline SRS and Curation Scenarios
- **Author**: Ayush Patel (BT2024171)
- **Commit Reference**: C03 (`docs(scope): baseline the SRS and curation cases`)
- **Summary**: Baselined condensed Word SRS (`FocusList_SRS_Condensed.docx` v1.1) and project brief (`Project_1_YouTube_MCP.pdf`). Authored `docs/curation-walkthrough.md` with seven detailed acceptance walkthrough scenarios (CW-01 to CW-07). Tracked TBD-1 pending official course staff scheduling.

### 2026-11-17 · Commit C02: Requirements Traceability and Acceptance Specifications
- **Author**: Harshil Srivastav (BT2024187)
- **Commit Reference**: C02 (`docs(requirements): map brief to acceptance checks`)
- **Summary**: Established `docs/requirements-traceability.md` mapping 42 criteria across brief and SRS, and created `docs/testing/acceptance-cases.md` with 41 Given/When/Then acceptance scenarios.

### 2026-11-16 · Commit C01: Repository Bootstrap and Workflow Setup
- **Author**: Aangir Doshi (BT2024078)
- **Commit Reference**: C01 (`chore(repo): set up project workflow`)
- **Summary**: Initialized repository structure, `.gitignore` rules for secrets and virtual environments, `.env.example`, `AGENTS.md`, and issue/PR templates.

---

## AI Session Records (SB-1, SB-5, SE-5)

### Session C07-S01: Scaffold the Python MCP Service
- **Date**: 2026-11-25 (IST)
- **Teammate / Operator**: Aangir Doshi (BT2024078)
- **AI Model**: Antigravity (Gemini 3.8 Flash High)
- **Session Goals**:
  1. Inspect C07 brief, AGENTS.md, Commit Plan, and SRS requirements (`UI-1–UI-5`, `COM-1–COM-6`, `FR-11`, `NFR-PORT`).
  2. Implement package structure, CLI, FastMCP server, injectable clock seam, shared contracts, and error registry.
  3. Implement `VideoProvider` abstraction, fixture provider, fault injection provider, and isolated live provider.
  4. Provide synthetic test fixtures and comprehensive unit, integration, and system test suites.
  5. Verify clean stdio protocol isolation, linter status, and zero secret leakage.
  6. Document ADR-001, update README.md, update Second Brain log, and update Commit Plan completion line.
- **Key Decisions & Resolutions**:
  - Implemented FastMCP server stdio protocol with stdout strictly reserved for JSON-RPC frames; all diagnostic and logging output redirected to stderr (COM-1).
  - Confined all Google API client imports (`googleapiclient`, `google.auth`) to `src/focuslist/platform/live_provider.py` (FR-11.2).
  - Designed deterministic `FakeClock` seam for repeatable testing of timestamps, proposal expiration, and quota resets (NFR-PORT).
  - Pinned 18 error codes in `src/focuslist/errors.py` with clear remediation advice and retryability flags (COM-5).
  - Created offline synthetic fixtures with zero live account data or credentials (SEC-SECRETS, BR-9).
- **Verification Performed**:
  - `python -m ruff check .` passed with zero errors.
  - `python -m pytest -v` executed and passed 33 tests across unit, integration, and system test modules.
  - Subprocess script executed `focuslist.cli serve`, sent standard JSON-RPC `initialize` frame, and validated that stdout contained 100% protocol frames with zero log contamination.
  - Secret scan confirmed no API keys or personal data committed.

### Session C04-S01: Second Brain Layout & Platform Research Notes
- **Date**: 2026-11-20
- **Teammate / Operator**: Aangir Doshi
- **AI Model**: Antigravity (Gemini 3.8 Flash High)
- **Session Goals**:
  1. Inspect existing project repository state, condensed SRS, AGENTS.md, and Commit Plan C04 specifications.
  2. Establish Second Brain vault structure (`brain/`) conforming to PARA methodology with inbox, index, and log.
  3. Formulate strict frontmatter schema and author four comprehensive platform research notes covering official API design, quota budget management, OAuth 2.0 lifecycle, and synthetic fixture isolation.
  4. Document licensing status (TBD-5) and baseline quota allocations (TBD-11).
  5. Link notes to SRS requirements, commit plan sections, and planned acceptance test cases.
  6. Verify all links, frontmatter syntax, and complete absence of real secrets or personal user data.
- **Key Decisions & Resolutions**:
  - Confined all Google client imports to `src/focuslist/platform/` and verified that higher layers only see typed protocol records.
  - Baselined daily quota at 10,000 general units and 100 search calls with a 5% margin (9,500 effective ceiling) and 2,600 per-request cap.
  - Specified incremental OAuth scoping, requesting `youtube.readonly` initially and deferring write scope to first confirmed playlist creation (TBD-6 / ADR-003).
  - Resolved TBD-5 documentation by providing an in-depth comparative evaluation of MIT vs Apache 2.0, designating `docs/licenses/` for third-party notices, and keeping the final team decision open for Stage 1 close.
- **Verification Performed**:
  - Automated Python script executed to validate YAML frontmatter keys across all notes in `brain/resources/`.
  - Path and anchor link validation for cross-references to `docs/requirements-traceability.md`, `docs/testing/acceptance-cases.md`, and `FocusList_Commit_Plan.md`.
  - Secret scanning scan verifying zero API keys, client secrets, bearer tokens, or PII in `brain/`.

### Session C06-S01: Curation Research Notes, Skill Upstream Specification, and Stage 1 Review
- **Date**: 2026-11-24 (IST)
- **Teammate / Operator**: Ayush Patel (BT2024171)
- **AI Model**: Antigravity (Gemini 3.8 Flash High)
- **Session Goals**:
  1. Inspect existing project repository state, baselined SRS, AGENTS.md, C01–C05 commits, and Commit Plan C06 specifications.
  2. Author four Ayush-owned research notes covering deterministic duration solver, proposal disclosure with metadata sanitization, human confirmation gate & action lifecycle, and Agent Skill format standards.
  3. Close TBD-10 by investigating and recording upstream Google Antigravity and Agent Skill ecosystem specifications.
  4. Write the Stage 1 Review (`docs/stage-1-review.md`) reconciling requirements coverage, Second Brain inventory (13 notes across 3 teammates), and Appendix C decisions.
  5. Update `brain/index.md`, `brain/log.md`, `docs/requirements-traceability.md`, and `FocusList_Commit_Plan.md`.
- **Key Decisions & Resolutions**:
  - Pinned integer-second duration solver architecture with bounded knapsack formulation, $\pm 5\%$ tolerance, and explicit nearest achievable runtime reporting on infeasible constraint sets.
  - Formulated metadata sanitization pipeline stripping zero-width unicode (`\u200B`–`\u200D`, `\uFEFF`) and control characters, truncating descriptions to 500 characters, and marking external data with `untrusted: true` to prevent prompt injection.
  - Specified cryptographic HMAC-SHA-256 proposal token binding canonical fields with 30-minute expiry, single-use atomic SQLite claims, and idempotent zero-write replays.
  - Resolved TBD-10 by documenting exact upstream skill limits: `name` $\le 64$ chars (lowercase alphanumeric and hyphens), `description` $\le 1024$ chars, mandatory uppercase `SKILL.md`, and 3 deterministic evaluations per skill.
- **Verification Performed**:
  - Python scripts validated YAML frontmatter schema across all notes in `brain/resources/`.
  - Markdown link validation for internal relative paths and anchors.
  - Secret scan confirmed absence of API keys, bearer tokens, or PII.

### Session C05-S01: Discovery and Analytics Evidence

- **Date:** 2026-11-22 (IST). **Teammate / operator:** Harshil Srivastav. **AI tool:** Codex.
- **Assignment:** [C05](../FocusList_Commit_Plan.md#c05-document-discovery-and-analytics-evidence), covering FR-1–FR-4, FR-6 and TBD-3.
- **Research notes:** [Candidate retrieval and TF-IDF](resources/candidate-retrieval-and-tfidf.md), [missing metadata and sparse fixtures](resources/missing-metadata-and-sparse-fixtures.md), [account activity timestamp provenance](resources/account-activity-timestamp-provenance.md) and [ranking evaluation metrics](resources/ranking-evaluation-metrics.md).
- **Decisions and evidence:** Compared the course brief and SRS with official API references. Documented playlist-add and subscription event fields separately from video publication, with a planned warning for fallback and a separate undated case. Liked-event provenance remains open under TBD-3. Linked deterministic examples to [C02 acceptance cases](../docs/testing/acceptance-cases.md), updated the [vault index](index.md) and connected the [requirements matrix](../docs/requirements-traceability.md) to the notes.
- **Verification:** A local PowerShell here-string piped to `python -` used PyYAML to parse all four frontmatter blocks. It checked added relative paths and Markdown anchors, verified the eight supporting-note rows and recalculated the worked duration and ranking examples. `git -c core.safecrlf=false diff --check` checked the tracked changes for whitespace errors. The new note files were checked for trailing whitespace by the Python check.
- **Review:** Harshil reported teammate approval before publication. GitHub had no C05 pull request at the time.
- **Pending evidence:** The fixture variants are specifications for future implementation. Authenticated YouTube calls, MCP fixture runs and ranking benchmarks were outside this session.

### Session C08-S01: Discovery and Ranking Design

- **Date:** 2026-11-25 (IST). **Teammate / operator:** Harshil Srivastav. **AI tool:** Codex.
- **Assignment:** [C08](../FocusList_Commit_Plan.md#c08-define-ranking-and-evaluation-contracts). Compared the course brief and SRS with C02 acceptance cases, C05 evidence and C07's published scaffold at `6de612d`.
- **Decisions and evidence:** Authored the [discovery and analytics ADR](../docs/adr/ADR-002-discovery-analytics-and-ranking-evaluation.md) and [paired ranking evaluation](../docs/testing/ranking-evaluation.md). Verified the 20 public YouTube IDs against their MIT OpenCourseWare lecture pages. Froze 19 candidates per seed and labelled all 380 directed pairs before the scoring checks.
- **Verification:** A local PowerShell here-string piped to `python -` validated IDs, paths, anchors and judgement membership, then checked identical candidate sets, deterministic sorting in a standard-library reference calculation, the metric examples, UTC offsets and duration-bin edges. `git -c core.safecrlf=false diff --check` passed.
- **Publication check:** The owner requested publication after C07 merged. The ADR uses the merged scaffold's identifier parameter names and documents the retained period shorthand and production source-selection requirement. Against merged `main`, `python -m pytest -q` passed all 33 tests with `FOCUSLIST_PROVIDER=fixture` in a fresh Python 3.12 environment with MCP 1.30.0. `python -m ruff check .` passed.
- **Open evidence:** C07 interface gaps are documented in the ADR. Teammate PR review, product MCP checks and C26's measured ranking results remain pending.

### Session C11-S01: Shared Metadata Normalisation

- **Date:** 2026-11-25 (IST). **Teammate / operator:** Harshil Srivastav. **AI tool:** Codex.
- **Assignment:** [C11](../FocusList_Commit_Plan.md#c11-normalise-identifiers-duration-and-metadata). Pulled through C10, based on `f694e34`. Checked the [SRS](../FocusList_SRS_Condensed.docx), plan and merged ADRs before editing.
- **Dependency audit:** Verified C08's frozen 20-seed manifest and 380 directed judgements. C08 is merged and its plan checkbox remains open. ADR-002's recommendation row gives freshness/duration 0.20/0.10, while SRS §6.4 and plan §4 prescribe 0.15/0.15. This is a follow-up for Harshil before C20/C26. Verified C09's state and approval design, eight threat entries and links. C10's fixture provider, fault injection and stdio harness passed the pulled 49-test baseline. Live scope and demo-client approval checks remain with C22/C24. GitHub recorded the three merges without formal PR reviews.
- **Implementation:** [Caller guide](../docs/development/metadata-normalisation.md) and [UT-PARSE](../docs/testing/acceptance-cases.md#ut-parse). Normalized syntactically equivalent YouTube references, rejected malformed inputs ahead of provider access, and left missing C07 fields nullable with explicit language and timestamp provenance. Updated synthetic identifiers to match the strict public format.
- **Verification:** `FOCUSLIST_PROVIDER=fixture` with `python -m pytest -q` passed 145 tests, including C10's stdio harness and C11's provider-counter tests. `python -m ruff check .` and `git -c core.safecrlf=false diff --check` passed. A read-only Python check verified the manifest, eight threat IDs, 43 ADR/usage links and synthetic fixture cross-references. Owner and teammate review remain pending.

### Session C09-S01: Playlist Action Lifecycle and Threat Model

- **Date:** 2026-11-25 (IST). **Teammate / operator:** Ayush Patel. **AI tool:** Antigravity.
- **Assignment:** [C09](../FocusList_Commit_Plan.md#c09-design-the-playlist-action-lifecycle), covering FR-5, FR-7, FR-8, NFR-SAF, NFR-SEC, DB-2, DB-3.
- **Decisions and evidence:** Authored [`docs/adr/ADR-004-playlist-action-lifecycle-and-threat-model.md`](../docs/adr/ADR-004-playlist-action-lifecycle-and-threat-model.md) aligned with C07's `ProposalRecord`, `ErrorCode`, and `Clock` contracts. Specified the state transition table, single-use atomic SQLite claims, HMAC-SHA-256 canonical signing, idempotent replay (`0` additional writes), reconciliation-first timeout recovery, deterministic selection objective with objective `capped_quality`, and threat model `TM-01`–`TM-08`. Named open choices (TBD-2, TBD-6, TBD-9, `UNDO_INELIGIBLE`, `capped_quality` thresholds).
- **Verification:** Validated relative markdown links across `ADR-004` and `brain/index.md`, ran `git diff --check`, and verified `pytest` (33 passed) and `ruff check .` against the `.venv` environment.
- **Open evidence:** Teammate PR review and C12/C15/C21/C24/C27/C30 implementation checks remain pending.
