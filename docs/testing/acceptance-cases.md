# FocusList Acceptance Cases

Use these Given/When/Then cases to implement and report the planned tests in the [C02 traceability matrix](../requirements-traceability.md). They are acceptance specifications. Execution evidence is pending.

## Fixture and observation conventions

- Use synthetic videos, channels, accounts, timestamps, credentials and mock responses. IDs and labels are test inputs and do not refer to real accounts. Use a deterministic clock, temporary storage, mock OAuth and mock transport. The official live-provider integration cases use a mock transport. The scheduled live smoke job is the only live CI case.
- A **provider call** is a call into the instrumented provider. An **outbound attempt** is dispatch through its transport. Assert both counters on paths that must reject before provider dispatch. Count writes independently as creation, insertion or deletion operations, and track retries/pages independently to verify quota.
- Examples specify observable behaviour, test data and reference IDs. Concrete JSON keys, optional field types and error strings not prescribed by the SRS are proposed until C07–C12 pin the contracts. Preserve SRS-defined error codes. Check errors include a code, message, remediation hint and retryable flag and contain no sensitive data.
- For live-read eligibility, account authorisation and playlist writes, distinguish the permitted preflight reads from the mutations. Run through the actual registered MCP tools where the case names the scripted client. Use direct unit/integration tests only for the layers named by the case.
- Evidence for each executed check belongs in this folder. Record test ID, command or manual action, mode, result and linked PR. The twelve ST-FR IDs and six SKE-SK IDs match the condensed SRS traceability section.

[Condensed SRS](../../FocusList_SRS_Condensed.docx) · [Course project statement](../../Project_1_YouTube_MCP.pdf) · [Curation Walkthrough](../curation-walkthrough.md)

## Course functionality and workflow

### ST-MCP

**Given** the server starts as a stdio subprocess in fixture mode with a temporary data directory.

**When** the scripted client initialises MCP and lists tools, resources and prompts.

**Then** JSON-RPC responses parse without stray stdout output, and the course tools, the proposal resource and required skill exposure match the agreed schemas. An AI-client fixture run can discover the workflow. **YouTube outbound calls 0, writes 0.**

### ST-FR1

**Given** a public seed, equivalent URL and raw ID forms, two relevant videos with a deliberate ranking tie, and candidates that include the seed, a duplicate and unavailable or ineligible items.

**When** the scripted MCP client calls `get_video_details` and `similar_videos` using each supported form.

**Then** the detail result contains normalised facts and a marked description excerpt of at most 500 characters. Rankings agree for equivalent inputs, omit the seed/duplicates/ineligible items, prefer the newer result on a score tie and use stable ID for a remaining tie. Verify default 10 and max 50 results, at most two searches plus one seed-upload page and at most 150 deduplicated candidates. **Writes 0.**

### ST-FR2

**Given** a fixture resolves a channel URL, handle and ID to one seed and supplies recent public uploads, ineligible channels and a candidate with a hidden count.

**When** the MCP client calls `similar_channels` with each supported form.

**Then** eligible results are ranked consistently. The seed and duplicates are absent, a hidden count stays unknown and is flagged, and reranking uses recent uploads only for the top ten. Assert no more than 20 seed uploads, three searches, 100 deduplicated candidates and 25 returned results (default 10). **Writes 0.**

### ST-FR3

**Given** an authorised fixture account with likes, subscriptions and playlists, and candidates that include liked and saved videos plus relevant unseen videos.

**When** the MCP client calls `recommend_videos` with all sources and then a supported subset.

**Then** source selection and caps are respected, known items are excluded, and rankings explain the highest contributing items or channels (at most three). The response states that watch history is unavailable. Check caps of 200 likes, 200 subscriptions, five playlists with 100 items each, three searches and five subscribed channels for recent uploads. **Writes 0.**

### ST-FR4

**Given** two disjoint fixture periods with unique observations drawn from likes, subscriptions and playlists, named categories and known durations. In the current period one channel represents 3 of 4 observations and in the baseline it represents 2 of 4. A second metric has an empty or zero baseline.

**When** the MCP client calls `analyse_engagement` with an explicit comparison and week/month grouping, then exercises the 30/90/365-day presets.

**Then** that channel's shares are 75% and 50%, and its count comparison is +1 and +50%. The second metric's percentage change is null. Check top channels/categories, counts per source, chart buckets, average/median, histogram cutoffs at 5/10/20/40/60 minutes and the sparse-data warning. Use actual event dates where available and disclose publication-date fallback where applicable. **Search attempts 0, general units ≤60, writes 0.**

### ST-FR5

**Given** a seed/topic with twelve eligible ten-minute English videos, an authorised test context with a channel and mocked write provider, and constraints of two hours with a 20-minute per-item maximum.

**When** the client translates those constraints, calls `propose_playlist`, shows the exact ordered response, receives a separate explicit human approval, and calls `confirm_playlist` with the reviewed proposal ID and token.

**Then** the proposal shows title, channel, duration, rank reason, exact order, 120-minute total, 12 items, constraint status and estimated cost. Proposal uses no more than three searches, **proposal writes 0**. Confirmation does one channel check where needed, one private playlist creation with the stored title and 12 ordered inserts, respecting the write interval. For the SRS baseline the confirmation estimate is 651 general units before retry charges. Verify the returned playlist identity and repeat the exact successful confirmation to assert **additional writes 0**.

### SKE-SK2

**Given** a fixture seed, related candidates and input constraints, and a scripted stream of user decisions.

**When** the client invokes `video-to-playlist`, trace (1) video fact retrieval and summary, (2) `similar_videos`, (3) collection of constraints, read-only proposal and an approval request, (4) confirmation in a separate turn after approval, and (5) read-only analysis of the created playlist.

**Then** the approved path returns a short analysis of the correct playlist. Trace the separate turns and assert **writes 0 until approval**. Run deterministic decline, edit and over-budget variants. A decline has **writes 0** and no confirmation call. Edits require a fresh proposal and approval. Over-budget work exits with the quota error and **writes 0**.

## Required engineering and API checks

### UT-PARSE

**Given** equivalent valid video URLs, canonical IDs, a supported channel handle and durations `PT20M` and `PT2H`.

**When** the shared parsers normalise them and process a malformed duration and invalid/foreign URL.

**Then** seconds are 1,200 and 7,200, accepted IDs canonicalise consistently, and invalid values are rejected rather than guessed. **Outbound calls 0, writes 0.**

### UT-SCORE

**Given** a fixed synthetic corpus containing exact text matches, unrelated terms and records with absent tags or language.

**When** TF-IDF cosine and the local weighted scorer run twice on the same inputs.

**Then** ordering and scores match exactly across runs, comparable matches outrank unrelated candidates, tie-breaks are stable and missing inputs produce warnings instead of invented data. **Outbound calls 0, writes 0.**

### UT-SOLVER

**Given** integer-second candidates covering tolerance boundaries, a too-long item, a wrong-language item and an infeasible eligible set.

**When** the pure selector applies the same validated constraints to fixed examples and at least 1,000 generated cases.

**Then** every returned item respects hard filters and the item cap, a feasible set stays within tolerance, and the infeasible result gives the nearest eligible total and identifies unmet constraints. Output is deterministic. **Outbound calls 0, writes 0.**

### IT-PROVIDER

**Given** a synthetic transport for the official provider and a fixture equivalent using the same typed responses.

**When** the service reads public/authorised records and follows bounded pagination.

**Then** result shapes agree, URI/method and import-boundary inspection shows use of the official YouTube Data API through `VideoProvider`, and each required page/attempt is counted once. Check read auth, safe error mapping and the cache and quota hooks. The test makes **real YouTube outbound calls 0, writes 0**.

### IT-CACHE

**Given** a temporary SQLite database, fake clock and two distinct synthetic accounts.

**When** a request runs twice, advances past each TTL, purges one account and repeats the calls.

**Then** a usable cache hit makes **provider calls 0** and costs zero. Expired records miss according to the SRS TTLs and hard retention limit. An account purge removes authorised and derived data for that account without touching the other account. Validate retention, parameterised SQL and atomic state updates. **Writes to YouTube 0.**

### CI-FIXTURE

**Given** a pull-request workflow run with fixture data and canary environment values.

**When** it runs the unit, integration and scripted MCP suite.

**Then** check fixture-only configuration, no live secrets or remote provider calls, and at least two Python versions with required line coverage. The security/data scan sees only synthetic values. **Real YouTube outbound calls 0, writes 0.**

### CI-LIVE

**Given** a separate team-approved scheduled workflow and a dedicated authorised test account with credentials stored outside the repo.

**When** the scheduled run executes its bounded smoke operation.

**Then** the job enforces its fixed run budget (SRS defaults ≤500 general units and ≤5 searches), records actual cost and cannot be triggered by a PR. Choose a read-only smoke operation for this case. **Writes 0.** Report the actual run as pending until the named workflow runs. A syntax or fixture check is separate evidence.

### IT-QUOTA

**Given** the SRS baseline daily quotas, method costs, safety margin, request cap and a fake Pacific-day clock, with too little general quota or too few searches for a validated fixture request.

**When** `estimate_quota` runs, the same workflow is submitted, and an affordable request subsequently succeeds after a local ledger reset.

**Then** the estimate makes **outbound calls 0**, and denial returns `QUOTA_BUDGET_EXCEEDED` with **provider calls 0, outbound attempts 0, writes 0**. Verify method costs, Pacific reset, request cap, actual per-request charges, cache hits at zero and accounting for each permitted retry and page. Verify the repository uses one approved Cloud project for quota policy, with current upstream allocations tracked under TBD-11.

## Required negative and security cases

### NEG-INPUT

**Given** a malformed video/channel/playlist ID, foreign URL, unknown JSON key, invalid type or out-of-range value.

**When** each is sent to the applicable MCP tool.

**Then** receive a structured validation error with remediation and `retryable=false`. Expect `INVALID_VIDEO_ID` for malformed video identifier input. Legacy `/c/` channel URLs get a remediation hint. Other unsupported/invalid forms use the agreed registry (proposed fallback `INVALID_ARGUMENT`). **Provider calls 0, outbound attempts 0, writes 0.**

### NEG-UNAVAILABLE

**Given** valid IDs with a mocked private/deleted video seed and a playlist containing a private/deleted entry with missing detail.

**When** running video discovery and playlist audit.

**Then** return `VIDEO_UNAVAILABLE` for the inaccessible seed and identify the unavailable audit entry without leaking private fields or inventing metadata. Only bounded read lookups can occur. **Writes 0.**

### NEG-METADATA

**Given** a readable candidate with absent tags, language, keywords or public counts.

**When** ranking or displaying it.

**Then** flags name the missing fields, ranking remains deterministic and uses the agreed missing-data policy, and counts stay unknown. An unresolved explicit language match follows the SRS policy and is never silently reported as verified. **Writes 0.**

### NEG-PROFILE

**Given** two fixture contexts, one without consent and one authorised with no data for the selected sources.

**When** invoking `recommend_videos`.

**Then** missing consent returns `AUTH_REQUIRED` with **provider calls 0, writes 0**. The empty authorised profile returns `NO_PROFILE_DATA` after bounded source reads with **discovery searches 0, writes 0**.

### NEG-UPSTREAM

**Given** fault fixtures that separately simulate upstream quota exhaustion, upstream rate limiting, and a transient read timeout.

**When** an otherwise affordable read reaches the mocked provider.

**Then** quota and rate results return a stable error and stop retries; proposed safe public codes are `UPSTREAM_QUOTA_EXHAUSTED` and `RATE_LIMITED`. The follow-up denied by the applicable exhausted bucket makes **new outbound attempts 0**. A transient read may retry within SRS limits, and each attempt is charged. **Writes 0** for every read case.

### NEG-NO-CHANNEL

**Given** a valid approved creation proposal and a mock eligibility check that reports no YouTube channel, including the upstream `youtubeSignupRequired` mapping.

**When** the confirmed write workflow performs eligibility checking.

**Then** return `NO_YOUTUBE_CHANNEL` with next-step guidance. The eligibility read is allowed. **Create calls 0, insert calls 0, total writes 0.**

### NEG-AUTH

**Given** a Testing-mode token fixture approaching expiry, one with `invalid_grant`, and a declined OAuth consent fixture.

**When** checking status, attempting the applicable read, or declining access.

**Then** show the day-five warning and seven-day reauthorisation guidance as specified, return `AUTH_EXPIRED` on invalid grant and `AUTH_CANCELLED` for declined consent. Stop retrying the invalid grant. Revoke/purge authorised data when required by the SRS and reveal no credential values. A failed or declined consent may involve OAuth traffic but must make **video API reads 0, account writes 0** for the affected tool run.

### NEG-CONSTRAINT

**Given** a missing topic or contradictory min/max values, and a separate valid request whose fixture pool cannot reach its time window.

**When** proposing each playlist.

**Then** invalid requests receive a stable validation error with **provider calls 0**. For infeasibility after bounded reads, report the nearest achievable eligible total and the unsatisfied constraint, with no silently relaxed cap or language. **Writes 0** in both cases.

### SEC-OAUTH

**Given** mocked consent, secure storage and verified HTTPS transport, and a learner who initially requests reads only.

**When** authorising, checking status, reading, first confirming a write in the fixture, and logging out.

**Then** exact read scope is `youtube.readonly` and the one agreed write scope (TBD-6) is requested only after explicit confirmed write intent. Wrong loopback state fails, credentials and installation key are in the OS credential store or user-only fallback, and logs/status contain neither value. Check revocation and private-data purge. **Writes before valid approval 0**. Mock all external requests.

### SEC-SECRETS

**Given** synthetic canary secrets and synthetic personal values in input fixtures for the scanner/redaction tests.

**When** verifying the PR diff, fixture recorder, logs, errors, local ignore rules and workflow credential isolation.

**Then** scan rules recognise the canaries and the committed fixtures, logs and evidence contain none of the canaries after sanitisation, nor real account data or credential values. Public response schema exposes only required safe metadata. Check repo CI, OAuth logs and the fixture recording allowlist. **Real outbound calls 0, writes 0.**

### SEC-APPROVAL

**Given** an exact reviewed proposal, synthetic untrusted metadata samples (at least 15), a declined/missing decision, and wrong-action, changed, expired or tampered proposal tokens.

**When** the client and server process those cases using the fixture provider.

**Then** untrusted text is marked and safely bounded and cannot substitute a human decision, modify canonical action or trigger a write. Decline/missing approval makes **confirmation calls 0, writes 0**. Invalid confirmation returns `CONFIRMATION_INVALID` with **outbound YouTube attempts 0, writes 0**. Test a valid explicit decision as a control; replay after successful creation returns its stored result with **additional writes 0**.

## SRS extension and regression cases

### ST-FR6

**Given** fixed candidate records with score contributions, shared terms, missing fields and account-source evidence.

**When** the scripted MCP client retrieves ranked results and reads `focuslist://config/scoring`.

**Then** each explanation contains raw values and weights, sums to its score within 0.000001, has at most five shared terms and a reason of at most 200 characters, and accurately identifies missing values. Assert **additional provider calls 0** to calculate the explanation or read the weights, and **writes 0** throughout.

### ST-FR7

**Given** a validated proposal, a mock provider that fails during the insertion sequence, and a signed action record.

**When** approving, forcing failure, inspecting progress, approving a fresh proposal for the remaining items and separately requesting an undo.

**Then** report `PARTIALLY_CREATED` with the known playlist and step, resume with only missing items and accept deletion only for a retained FocusList-created playlist after separate approval. Declined, stale or wrong-action recovery and unrelated targets cause **new writes 0**. For concurrent confirmation of one action, at most one execution claims it.

### ST-FR8

**Given** a selected set with numbered series videos from a single channel, near-identical titles, more than three eligible videos from another channel and one video longer than a study session.

**When** requesting learning-path, relevance and chronological ordering with sessions.

**Then** detected series stay adjacent and numerically ordered in learning-path mode, limits and deduplication apply before final selection, all hard constraints still hold and the session pack preserves whole videos and flags the overlong item. Assert deterministic order, time totals and **writes 0**.

### ST-FR9

**Given** a mock OAuth and credential store with explicit read consent, simulated write consent and a fake clock.

**When** authorising, checking MCP status, refreshing, expiring and revoking the session.

**Then** assert scope and safe status payload, account-scoped purge and actionable recovery. Re-run NEG-AUTH and SEC-OAUTH at the scripted MCP boundary where applicable. **Writes 0** for status and failed authorisation.

### ST-FR10

**Given** an instrumented fixture server with a known quota snapshot.

**When** invoking its estimate and status tools and submitting a request over the remaining search or general allowance.

**Then** status/estimate make **provider calls 0**, and the rejected request returns `QUOTA_BUDGET_EXCEEDED` with **provider calls 0, writes 0**. Verify both quota buckets in the response and combine with IT-QUOTA for charge accuracy.

### ST-FR11

**Given** fixture and fault-backed provider configurations and a populated expiring cache.

**When** running one MCP read with each provider mode and advancing the clock through expiry.

**Then** fixture results and errors follow shared schemas, the usable cache hit makes **provider calls 0**, fault attempts are counted and offline mode makes **real YouTube outbound calls 0, writes 0**.

### ST-FR12

**Given** a fixture with 501 playlist records including private/deleted placeholders, duplicate IDs, similar titles, over-length and older entries, and live/upcoming entries.

**When** invoking `analyse_playlist` and `audit_playlist` with default and explicit thresholds.

**Then** at most 500 items are read and the response reports truncation, total count/duration of processed rows, required distributions and correct issue flags. Verify bounded cost using the SRS formula, and **writes 0**.

### SK-METADATA

**Given** six named skill folders, `SKILL.md` fixtures and their linked distilled notes, including a deliberately invalid file in an isolated test copy.

**When** CI validates skill metadata and evidence and MCP lists product skill resources and prompts.

**Then** valid files meet the agreed format (TBD-10), the invalid copy fails with a location, and each skill has at least three deterministic cases including a negative/adversarial one. Product skills use fixtures by default, and evidence dates match stage reviews. **Real outbound calls 0, writes 0** in fixture verification.

### SKE-SK1

**Given** local-check scenarios for success, build/test failure and startup or fixture retrieval failure.

**When** running build, tests, stdio startup, fixture video lookup and clean shutdown.

**Then** return PASS/FAIL/SKIPPED by step, close the subprocess even on failure and preserve user data. On the documented CI runner, the offline call finishes within 120 seconds. **Real YouTube outbound calls 0, writes 0.**

### SKE-SK3

**Given** a synthetic source, a source missing required evidence, and a duplicate case.

**When** invoking brain-ingest.

**Then** valid inputs update the inbox, index and log with source, author, date, status, type, SRS IDs and evidence/uncertainty. Missing claims remain marked and no source is fabricated or overwritten. Check the Stage 1 evidence for at least ten notes. **YouTube calls 0, writes 0.**

### SKE-SK4

**Given** synthetic vault cases for routine organisation, duplicate notes and a broken link.

**When** invoking brain-refine.

**Then** confirmed moves, links, index and log agree with the PARA structure and validator. Source attribution survives any merge. **YouTube calls 0, writes 0.**

### SKE-SK5

**Given** a vault with relevant notes, a supported ADR/SRS drafting request and a request with missing evidence.

**When** invoking brain-query.

**Then** answers and drafts cite the actual notes, unsupported claims are identified, and drafts follow the reviewed PR path. **YouTube calls 0, writes 0.**

### SKE-SK6

**Given** a readable fixture playlist, a fixture with warnings and a quota-denied or inaccessible case.

**When** invoking playlist-audit.

**Then** estimate before reading, render identified issues and suggested fixes without editing the playlist, and report the applicable error on denial. For quota denial **outbound calls 0**. **Writes 0** across all scenarios.

### QA-RELEVANCE

**Given** at least 20 labelled public seeds represented in safe fixtures, with fixed candidate sets and stable relevance labels.

**When** running the same sets through TF-IDF-only and weighted strategies.

**Then** retain real precision@5 and mean reciprocal rank by seed and in aggregate, with parameters and reproduction commands. Report any gap against the provisional 0.60 precision@5 target (TBD-4). **Real outbound calls 0, writes 0.**

### QA-RELEASE

**Given** the integrated team repository and published requirement, note and release references.

**When** reviewing the release and running the SRS benchmark suite, CLI help, generated-reference check and the clean-clone fixture demo.

**Then** record actual SRS §5 benchmark results, required review and coverage evidence, locale/CLI behaviour, `local-check`, and one AI client plus the scripted client or MCP Inspector. Verify stage reviews, ADRs, privacy, branding and licence evidence, no telemetry, and a regression test for each significant fixed defect. Pending checks stay identified. **Real YouTube outbound calls 0** for the fixture run.
