# FocusList Curation Acceptance Walkthrough & Requirements Baseline

**Owner:** Ayush Patel (Curation, Confirmation, Recovery, Main Demo)  
**Deliverable Commit:** C03 (`docs(scope): baseline the SRS and curation cases`)  
**SRS Reference:** FR-5, FR-7, SK-2, TBD-1  
**Traceability Links:** [Requirements Traceability](requirements-traceability.md) · [Acceptance Cases](testing/acceptance-cases.md) · [Condensed SRS](../FocusList_SRS_Condensed.docx) · [Project Brief](../Project_1_YouTube_MCP.pdf) · [Commit Plan](../FocusList_Commit_Plan.md#c03-baseline-the-srs-and-curation-examples)

---

## 1. Requirements Baseline & Document Verification

### 1.1 Document Verification & Traceability Baseline
The FocusList repository tracks the foundational requirements documents in their native authoritative formats:

1. **Condensed SRS Document**: [FocusList_SRS_Condensed.docx](../FocusList_SRS_Condensed.docx)
   - **Version:** 1.1 (condensed final draft)
   - **Date:** 15 November 2026
   - **Authors:** Ayush Patel (BT2024171), Harshil Srivastav (BT2024187), and Aangir Doshi (BT2024078)
   - **Integrity Check:** Valid OpenXML archive containing `word/document.xml` (41,342 text characters across 13 core sections and Appendices A, B, and C).
   - **Role:** Controls the formal scope and contractual specifications for the FocusList server, its tools, Agent Skills, and verification bounds.

2. **Course Project Statement**: [Project_1_YouTube_MCP.pdf](../Project_1_YouTube_MCP.pdf)
   - **Version:** Final course project specification (2 pages, valid `%PDF-1.4` binary, 295,667 bytes).
   - **Scope:** Defines course-mandated requirements FR-1 through FR-5, the `video-to-playlist` product skill, testing criteria TQ-1 through TQ-6, and API/security constraints (official YouTube Data API v3 only, 10,000-unit baseline daily quota, zero scraping, no watch history, Testing-mode OAuth reauthorisation, and YouTube channel prerequisite).

3. **Team Review & Mapping Baseline**:
   - **Ayush Patel:** Owner of curation orchestration, confirmation lifecycle, recovery workflows, and C03/C35 walkthrough deliverables.
   - **Harshil Srivastav:** Reviewer of C02 requirements traceability matrix (42 mappings, 41 Given/When/Then cases) and C03 curation cases.
   - **Aangir Doshi:** Owner of repository setup, CI workflow, and platform architecture.
   - **Cross-Document Consistency:** Verified that course requirements (FR-1–FR-5, SK-2, TQ-1–TQ-6) map directly to condensed SRS Sections 2, 4.1–4.5, 4.13, 5, and 6.6, and match the timeline milestones in [FocusList_Commit_Plan.md](../FocusList_Commit_Plan.md).

### 1.2 Open Decisions (TBD-1 Status)
Per the condensed SRS Appendix C and Commit Plan Section 7:
- **TBD-1 (Stage Deadlines and Demonstration Format):** The official course evaluation schedule, stage viva dates, and demo format remain **open**. As of 19 November 2026, course staff have not published formal fixed milestone dates beyond the tentative target window (16 November – 11 December 2026). In accordance with project instructions, TBD-1 is kept open without artificial backdating. Real work dates and review records are captured as each planned commit is verified.

---

## 2. Core Curation Contracts & Invariants

Curation orchestration (owned by Ayush Patel) enforces the following strict invariants across all playlist workflows:

1. **Constraint Validation Bounds (FR-5.1–5.3, FR-5.15):**
   - Topic: Non-empty string, length 1–200 characters.
   - Target duration (`target_duration`): Strictly positive ISO-8601 duration string (e.g. `PT2H` = 7,200s).
   - Maximum item duration (`max_item_duration`): Strictly positive ISO-8601 duration string (e.g. `PT20M` = 1,200s).
   - Minimum item duration (`min_item_duration`): Optional, defaults to 2 minutes (`PT2M` = 120s); must be $\le \text{max\_item\_duration}$.
   - Tolerance (`tolerance`): Optional, defaults to $\pm 5\%$ ($\text{tolerance} = 0.05$).
   - Language (`language`): Optional ISO-639-1 code, defaults to `"en"`.
   - Item limit (`max_items`): Optional integer, default 30, hard maximum 50.
   - Privacy status: Defaults to `"private"` (unconfirmed/draft proposals never write public playlists).
   - Contradictions, missing required fields, or invalid ISO-8601 values are rejected **locally** with zero YouTube API calls.

2. **Immutable Proposal & Confirmation Gate (FR-5.8, FR-7.1–7.5, UI-1):**
   - Generating a proposal via `propose_playlist` is strictly **read-only** with respect to user account state. **Outbound writes = 0**.
   - Visible proposal displays: item order, video ID, sanitized title, channel title, duration, relevance score, explanation reason, total runtime, item count, constraint satisfaction report, and estimated write quota cost.
   - Proposal contains an installation-signed HMAC-SHA-256 token binding:
     $$\text{Token} = \text{HMAC-SHA-256}_{K_{\text{install}}}(\text{proposal\_id} \mathbin{\Vert} \text{ordered\_video\_ids} \mathbin{\Vert} \text{title} \mathbin{\Vert} \text{privacy} \mathbin{\Vert} \text{action\_kind} \mathbin{\Vert} \text{expires\_at})$$
   - Token expiry is 30 minutes. Tokens are single-use and claimed atomically.
   - Confirming a playlist (`confirm_playlist`) requires a distinct conversational turn from the human learner. Untrusted metadata cannot authorise a mutation.

3. **Execution, Progress Persistence & Idempotency (FR-5.9–5.14, FR-7.1, FR-7.8):**
   - Channel check: Prior to creating a playlist, verifies the user has an active YouTube channel (`youtube.channels.list(mine=true)`).
   - Write rate limiting: Playlist item insertions occur at $\le 1\text{ write/second}$.
   - Progress persistence: The returned playlist ID and each inserted item index are recorded immediately in local SQLite.
   - Idempotent replay: Resubmitting `confirm_playlist` with an already-completed proposal returns the recorded successful result with **zero additional writes**.
   - Failure handling: On transient failure after exhausted retries, the server halts immediately, logs `PARTIALLY_CREATED`, and issues a resume proposal binding only the uninserted items.

---

## 3. Curation Acceptance Scenarios (Future Test Cases)

### Scenario CW-01: Baseline 2-Hour English Playlist on Recursion
*Traceability: [ST-FR5](testing/acceptance-cases.md#st-fr5), [SKE-SK2](testing/acceptance-cases.md#ske-sk2), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval), [UT-SOLVER](testing/acceptance-cases.md#ut-solver)*

#### Context & Goal
A learner asks the AI client: *"Build a two-hour playlist on recursion, with no video over 20 minutes, in English."*

#### Step 1: Constraint Translation & Validation
The AI client parses the request and invokes `propose_playlist` with structured parameters:
- `topic`: `"recursion"`
- `target_duration`: `"PT2H"` (7,200 seconds)
- `max_item_duration`: `"PT20M"` (1,200 seconds)
- `language`: `"en"`
- `tolerance`: `0.05` ($\pm 5\%$, valid range: 6,840s to 7,560s / 114m to 126m)
- `ordering`: `"learning_path"` (default)
- `privacy`: `"private"` (default)

**Validation:** Passes all bounds. No contradiction. **Outbound writes = 0.**

#### Step 2: Read-Only Discovery & Solver Selection
1. **Provider Discovery:** Server queries YouTube Data API `search.list(q="recursion", type="video", relevanceLanguage="en")` using at most 3 search pages (budgeted cost: 300 units).
2. **Batch Detail Lookup:** Batches candidate IDs into `videos.list(part="snippet,contentDetails,status")` (budgeted cost: 3 units).
3. **Filtering:** Filters out unavailable, nonpublic, live, upcoming, duplicate, age-restricted, over-20-minute, sub-60-second, and non-English candidates.
4. **Deterministic Solver:** Pure DP/bounded solver selects 12 high-relevance items of exactly 600 seconds (10 minutes) each:
   $$\text{Total Duration} = 12 \times 600\,\text{s} = 7,200\,\text{s}\;(120\,\text{m}\;00\,\text{s}) \in [6,840\,\text{s}, 7,560\,\text{s}]$$
5. **Learning-Path Ordering:** Evaluates difficulty cues, detected series, and channel diversity (max 3 items/channel).

#### Step 3: Proposal Display & Explicit Confirmation Gate
The tool returns structured JSON. The AI client displays the exact proposal to the learner:

```text
FocusList Proposed Playlist: recursion - 2026-11-19
Visibility: Private | Items: 12 | Total Duration: 2h 00m 00s (Target: 2h ± 5%)

Selected Videos:
 1. [600s] Introduction to Recursion Basics (CS Fundamentals) - Score: 0.94 (Core concept intro)
 2. [600s] Call Stack and Activation Records (ByteCode Academy) - Score: 0.92 (Stack mechanics)
 3. [600s] Base Cases and Termination Conditions (AlgoDaily) - Score: 0.91 (Structural rules)
 4. [600s] Head vs Tail Recursion Explained (CodePath) - Score: 0.89 (Memory optimisation)
 5. [600s] Recursion Tree Method for Time Complexity (CS Academy) - Score: 0.88 (Asymptotic analysis)
 6. [600s] Divide and Conquer Paradigms (Algorithmics) - Score: 0.87 (Decomposition strategy)
 7. [600s] Merge Sort Step-by-Step (Sorting Illustrated) - Score: 0.86 (Applied recursion)
 8. [600s] Binary Tree Recursive Traversals (DataStructure Hub) - Score: 0.85 (Tree traversal)
 9. [600s] Recursive Backtracking: Maze Solver (DevPrep) - Score: 0.84 (Exploration algorithms)
10. [600s] Dynamic Programming from Recursion (Memoization) - Score: 0.83 (Overlapping subproblems)
11. [600s] Common Recursion Pitfalls and Stack Overflow (DebugPro) - Score: 0.81 (Error prevention)
12. [600s] Summary and Real-World Recursion Exercises (TechPrep) - Score: 0.80 (Synthesis & review)

Constraints Report:
 - Topic: 'recursion' (Satisfied)
 - Total Runtime: 120m 00s (Target 120m ± 6m: Satisfied)
 - Max Video Duration: 10m 00s <= 20m 00s (Satisfied)
 - Language: English (Satisfied)

Estimated Write Cost: 651 YouTube Data API quota units
Proposal ID: 7f3a9e14-6b2c-4d8e-90a1-c52f810b4231
Expires in: 30 minutes

Do you approve creating this private playlist in your YouTube account?
```

*State assertion:* **Zero mutations have occurred. Outbound writes = 0.**

#### Step 4: Separate Human Approval Turn & Execution
The learner explicitly responds: *"Yes, I approve. Please create the playlist."*

The client calls `confirm_playlist(proposal_id="7f3a9e14-6b2c-4d8e-90a1-c52f810b4231", token="hmac_sha256_sig_...")`:
1. Server validates token signature, expiration (< 30 min), unused status, and matches stored proposal hash.
2. Atomically claims proposal in SQLite.
3. Preflight check: Verifies channel eligibility (`youtube.channels.list(mine=true)`).
4. Creates playlist: `youtube.playlists.insert(snippet={title: "recursion - 2026-11-19", description: "Curated by FocusList on recursion..."}, status={privacyStatus: "private"})` $\rightarrow$ returns playlist ID `PL_rec_20261119_abc123`.
5. Inserts 12 items sequentially: `youtube.playlistItems.insert(playlistId, videoId)` with $\ge 1\,\text{second}$ interval between writes.
6. Progress persisted to SQLite after each item.
7. Executes read-only playlist analysis (`analyse_playlist`) and returns completed summary.

#### Step 5: Idempotent Replay Assertion
If the AI client or network resubmits `confirm_playlist("7f3a9e14-6b2c-4d8e-90a1-c52f810b4231", token)`:
- Server checks SQLite action history.
- Returns the recorded success result and playlist URL immediately.
- **Additional writes = 0, additional quota = 0.**

---

### Scenario CW-02: Learner Decline with Zero Writes
*Traceability: [ST-FR5](testing/acceptance-cases.md#st-fr5), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval)*

1. **Given:** The learner receives the proposal generated in Step 3 of Scenario CW-01.
2. **When:** The learner responds: *"No, I changed my mind. Do not create this playlist."*
3. **Then:**
   - The AI client acknowledges cancellation and does **not** invoke `confirm_playlist`.
   - The proposal token remains unconsumed and expires after 30 minutes in SQLite.
   - **Outbound writes = 0. Zero playlists created. Zero playlist items inserted.**

---

### Scenario CW-03: Missing or Conflicting Parameters
*Traceability: [NEG-CONSTRAINT](testing/acceptance-cases.md#neg-constraint), [UT-PARSE](testing/acceptance-cases.md#ut-parse)*

#### Variant A: Missing Required Topic
- **Input:** `propose_playlist(topic="", target_duration="PT1H", max_item_duration="PT15M")`
- **Behavior:** Rejected locally by parameter validator.
- **Error:** `INVALID_ARGUMENTS` (`"Topic must be a non-empty string between 1 and 200 characters."`).
- **Assertion:** 0 YouTube API calls, 0 writes.

#### Variant B: Conflicting Duration Constraints
- **Input:** `propose_playlist(topic="sorting", target_duration="PT1H", min_item_duration="PT25M", max_item_duration="PT10M")`
- **Behavior:** Rejected locally because $\text{min\_item\_duration} > \text{max\_item\_duration}$.
- **Error:** `CONSTRAINT_CONFLICT` (`"min_item_duration (1500s) cannot exceed max_item_duration (600s)."`).
- **Assertion:** 0 YouTube API calls, 0 writes.

#### Variant C: Negative Duration
- **Input:** `propose_playlist(topic="graph theory", target_duration="-PT1H", max_item_duration="PT20M")`
- **Behavior:** Rejected locally by ISO-8601 parser.
- **Error:** `INVALID_ARGUMENTS` (`"target_duration must specify a positive non-zero duration."`).
- **Assertion:** 0 YouTube API calls, 0 writes.

---

### Scenario CW-04: Infeasible Target with Nearest Achievable Runtime
*Traceability: [UT-SOLVER](testing/acceptance-cases.md#ut-solver), [ST-FR5](testing/acceptance-cases.md#st-fr5)*

1. **Context:** Learner requests: *"Build a 2-hour playlist on obscure niche protocol X, with no video over 3 minutes."*
   - `topic`: `"obscure niche protocol X"`
   - `target_duration`: `"PT2H"` (7,200s, tolerance 6,840s–7,560s)
   - `max_item_duration`: `"PT3M"` (180s)
2. **Discovery & Filtering:**
   - YouTube search returns only 5 unique videos matching topic and language.
   - All 5 videos have durations $\le 180\text{s}$, with a combined total duration of 850 seconds (14m 10s).
3. **Solver Outcome:**
   - Maximum reachable duration is 850s ($14\text{m }10\text{s}$), which falls far below the lower tolerance boundary ($6,840\text{s}$).
4. **Server Response:**
   - Refuses to silently violate hard constraints (will not include irrelevant videos or videos $>180\text{s}$).
   - Returns structured `status: "infeasible"`:
     - `achievable_duration`: `850` (14m 10s)
     - `achievable_item_count`: `5`
     - `unmet_constraints`: `[{"constraint": "target_duration", "requested": "7200s ± 360s", "achieved": "850s", "deficit": "-5990s"}]`
     - `remediation_hint`: `"Increase max_item_duration, widen topic keywords, or reduce target duration."`
   - **No write proposal token is issued.**
   - **Assertion:** Outbound writes = 0.

---

### Scenario CW-05: Edit / Changed Request (New Proposal Required)
*Traceability: [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval), [ST-FR7](testing/acceptance-cases.md#st-fr7)*

1. **Context:** Learner reviews proposal `7f3a9e14-...` from Scenario CW-01 and requests an edit: *"Change total time to 1 hour and remove video 4."*
2. **Workflow:**
   - The client submits a fresh `propose_playlist` call with `target_duration="PT1H"` and `exclude_video_ids=["vid_004"]`.
   - Server evaluates constraints and generates **Proposal B** with ID `b82c1094-...` and a new HMAC-SHA-256 token.
   - In SQLite, Proposal A is marked `SUPERSEDED`.
3. **Security Invariant Verification:**
   - If an adversary or faulty client attempts to call `confirm_playlist` with Proposal A's token:
     - Token validation fails with `CONFIRMATION_INVALID` (`"Proposal has expired or was superseded by a newer proposal."`).
     - Zero YouTube writes are executed.
   - Only explicit approval of Proposal B's token can create the 1-hour playlist.

---

### Scenario CW-06: Partial Creation & Approved Resume
*Traceability: [ST-FR7](testing/acceptance-cases.md#st-fr7), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval)*

1. **Context:** Learner approves the 12-item playlist from Scenario CW-01.
2. **Partial Failure Execution:**
   - Playlist is successfully created on YouTube (`PL_rec_20261119_abc123`).
   - Items 1 through 7 are inserted successfully.
   - At item 8, YouTube Data API returns transient 500 error on 3 successive retries.
   - Server halts writes immediately (does not retry indefinitely or skip items silently).
   - In SQLite, proposal transitions to `PARTIALLY_CREATED`, recording playlist ID and completed items `[1..7]`.
3. **Response to Client:**
   - `status`: `"PARTIALLY_CREATED"`
   - `playlist_id`: `"PL_rec_20261119_abc123"`
   - `playlist_url`: `"https://www.youtube.com/playlist?list=PL_rec_20261119_abc123"`
   - `inserted_items`: 7 of 12
   - `failed_step`: `"INSERT_ITEM_8"`
   - `resume_proposal_id`: `"res_3c91a0f8-..."`
   - `resume_token`: HMAC token binding playlist `PL_rec_20261119_abc123` and remaining items `[8..12]`.
4. **Approved Resume Turn:**
   - The learner reviews the partial state: *"Item 8 failed due to a temporary network issue. 7 videos were added. Resume adding the remaining 5 videos?"*
   - Learner confirms: *"Yes, resume."*
   - Client calls `confirm_playlist(proposal_id="res_3c91a0f8-...", token=resume_token)`.
   - Server validates token, resumes insertion of items 8 through 12 into the **existing** playlist.
   - Does **not** create a duplicate playlist. Does **not** re-insert items 1–7.
   - Playlist completes successfully and transitions to `CREATED`.

---

### Scenario CW-07: Approved Undo of FocusList-Created Playlist
*Traceability: [ST-FR7](testing/acceptance-cases.md#st-fr7), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval)*

1. **Context:** Learner decides to delete a playlist previously created by FocusList: `PL_rec_20261119_abc123`.
2. **Undo Request:**
   - Client invokes `undo_playlist(playlist_id="PL_rec_20261119_abc123")`.
3. **Ownership Verification (FR-7.7):**
   - Server queries SQLite action history table.
   - Confirms `PL_rec_20261119_abc123` was created by FocusList within the 30-day retention window.
   - If playlist ID is unrecorded or belongs to arbitrary third-party content, server rejects with `UNDO_INELIGIBLE` (`"Cannot undo playlist: not created by FocusList or outside 30-day action window."`). **Writes = 0.**
4. **Deletion Proposal Generation:**
   - Server generates a deletion proposal:
     - `action_kind`: `"delete_playlist"`
     - `target_playlist_id`: `"PL_rec_20261119_abc123"`
     - `estimated_cost`: 50 general units (`youtube.playlists.delete`)
     - `deletion_token`: Signed HMAC-SHA-256 token binding deletion of `PL_rec_20261119_abc123`.
   - Proposal returned to client. **Zero writes executed at this step.**
5. **Separate Confirmation Turn:**
   - Client presents confirmation prompt: *"Confirm permanent deletion of private playlist 'recursion - 2026-11-19' (12 items)?"*
   - Learner responds: *"Yes, delete it."*
   - Client calls `confirm_playlist(proposal_id="del_91a0b3-...", token=deletion_token)`.
   - Server calls `youtube.playlists.delete(id="PL_rec_20261119_abc123")`.
   - Action recorded in SQLite as `UNDONE`.

---

## 4. Traceability to C02 Acceptance Cases

The table below links each curation walkthrough scenario to the formal acceptance tests defined in [docs/testing/acceptance-cases.md](testing/acceptance-cases.md) and [docs/requirements-traceability.md](requirements-traceability.md):

| Walkthrough Scenario | Description | SRS Requirement | Course Brief § | Planned Test ID | Zero-Write Guarantee |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CW-01** | Baseline 2h English playlist (recursion, 12 items, 20m cap) | FR-5.1–5.14, FR-7.1–7.5, SK-2, UI-1 | §2 (FR-5), §3 (video-to-playlist) | [ST-FR5](testing/acceptance-cases.md#st-fr5), [SKE-SK2](testing/acceptance-cases.md#ske-sk2), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval) | Writes = 0 until separate explicit human approval turn |
| **CW-02** | Learner decline | FR-7.1–7.4, 5.2 | §2 (FR-5) | [ST-FR5](testing/acceptance-cases.md#st-fr5), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval) | Writes = 0 permanently; proposal expires |
| **CW-03** | Missing / conflicting constraint validation | FR-5.1–5.3, FR-5.15 | §2 (FR-5), §4 (Input validation) | [NEG-CONSTRAINT](testing/acceptance-cases.md#neg-constraint), [UT-PARSE](testing/acceptance-cases.md#ut-parse) | 0 outbound API calls; local rejection |
| **CW-04** | Infeasible target with nearest achievable runtime | FR-5.5–5.6 | §2 (FR-5), §4 (TQ-1) | [UT-SOLVER](testing/acceptance-cases.md#ut-solver), [ST-FR5](testing/acceptance-cases.md#st-fr5) | Writes = 0; no mutation token issued |
| **CW-05** | Edited request invalidates earlier proposal | FR-7.1, FR-7.4 | §2 (FR-5), §4 (Security) | [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval), [ST-FR7](testing/acceptance-cases.md#st-fr7) | Writes = 0 until new proposal approved |
| **CW-06** | Partial creation & approved resume | FR-5.10, FR-7.1, FR-7.8 | §2 (FR-5), §4 (TQ-4) | [ST-FR7](testing/acceptance-cases.md#st-fr7), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval) | Halts on error; resume requires new explicit approval |
| **CW-07** | Approved undo of FocusList-created playlist | FR-7.7, FR-7.8 | §2 (FR-5) | [ST-FR7](testing/acceptance-cases.md#st-fr7), [SEC-APPROVAL](testing/acceptance-cases.md#sec-approval) | 30-day ownership check; separate confirmation turn |
