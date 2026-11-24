# FocusList Stage 1 Requirements & Architecture Baseline Review

**Review Milestone:** Stage 1 Close (Commits C01–C06)  
**Deliverable Commit:** C06 (`docs(review): close the requirements milestone`)  
**Date:** 24 November 2026 (IST)  
**Review Lead:** Ayush Patel (BT2024171)  
**Co-Reviewers:** Harshil Srivastav (BT2024187), Aangir Doshi (BT2024078)  
**Key Document Links:** [Requirements Traceability](requirements-traceability.md) · [Acceptance Cases](testing/acceptance-cases.md) · [Curation Walkthrough](curation-walkthrough.md) · [Commit Plan](../FocusList_Commit_Plan.md) · [Second Brain Master Index](../brain/index.md) · [Condensed SRS](../FocusList_SRS_Condensed.docx) · [Project Brief](../Project_1_YouTube_MCP.pdf)

---

## 1. Executive Summary and Milestone Objectives

Stage 1 establishes the complete contractual, architectural, and analytical foundation for **FocusList**, the local Model Context Protocol (MCP) server for YouTube video discovery, analytics, and constrained playlist curation.

Over the Stage 1 delivery window (16–24 November 2026), the three-person engineering team delivered and cross-reviewed commits **C01 through C06**:
- **C01 (Platform/Repo):** Repository bootstrap, security ignore rules, placeholders, and contribution workflow.
- **C02 (Discovery/Traceability):** Requirements traceability matrix (42 criteria) and 41 Given/When/Then acceptance cases.
- **C03 (Curation/Walkthrough):** Document baseline verification and 7 detailed curation acceptance walkthrough scenarios.
- **C04 (Platform/Second Brain):** Second Brain vault layout, PARA methodology, and 4 platform research notes + licensing decision record.
- **C05 (Analytics/Discovery):** 4 discovery, TF-IDF, metadata fallback, and ranking evaluation research notes.
- **C06 (Curation/Review):** 4 curation and skill specification research notes, closure of TBD-10, Second Brain reconciliation, and formal Stage 1 review.

With 13 research notes authored, the requirements matrix verified, and the curation state machine baselined, **Stage 1 is formally completed and signed off for handoff to Stage 2 (Design and Shared Contracts)**.

---

## 2. Coverage of Core Course Requirements & Testing Criteria

### 2.1 Course Functional Requirements (FR-1 to FR-5)
All five course-mandated functional requirements from the [Project Statement](../Project_1_YouTube_MCP.pdf) are completely mapped to the [Condensed SRS](../FocusList_SRS_Condensed.docx), specified in [Acceptance Cases](testing/acceptance-cases.md), and supported by authoritative Second Brain research notes:

| Course Requirement | SRS Mapping | Planned Test IDs | Second Brain Research Note(s) | Status |
| :--- | :--- | :--- | :--- | :--- |
| **FR-1: Similar Videos** | SRS §4.1, §6.4 | [`ST-FR1`](testing/acceptance-cases.md#st-fr1), [`UT-PARSE`](testing/acceptance-cases.md#ut-parse), [`UT-SCORE`](testing/acceptance-cases.md#ut-score), [`NEG-UNAVAILABLE`](testing/acceptance-cases.md#neg-unavailable) | [`candidate-retrieval-and-tfidf.md`](../brain/resources/candidate-retrieval-and-tfidf.md), [`official-api-provider-design.md`](../brain/resources/official-api-provider-design.md) | **Baselined** |
| **FR-2: Similar Channels** | SRS §4.2, §6.4 | [`ST-FR2`](testing/acceptance-cases.md#st-fr2), [`UT-SCORE`](testing/acceptance-cases.md#ut-score), [`NEG-INPUT`](testing/acceptance-cases.md#neg-input) | [`candidate-retrieval-and-tfidf.md`](../brain/resources/candidate-retrieval-and-tfidf.md) | **Baselined** |
| **FR-3: Recommendations** | SRS §4.3, §5.3 | [`ST-FR3`](testing/acceptance-cases.md#st-fr3), [`NEG-PROFILE`](testing/acceptance-cases.md#neg-profile), [`IT-CACHE`](testing/acceptance-cases.md#it-cache) | [`candidate-retrieval-and-tfidf.md`](../brain/resources/candidate-retrieval-and-tfidf.md), [`account-activity-timestamp-provenance.md`](../brain/resources/account-activity-timestamp-provenance.md) | **Baselined** |
| **FR-4: Engagement Analysis**| SRS §4.4 | [`ST-FR4`](testing/acceptance-cases.md#st-fr4) | [`account-activity-timestamp-provenance.md`](../brain/resources/account-activity-timestamp-provenance.md), [`missing-metadata-and-sparse-fixtures.md`](../brain/resources/missing-metadata-and-sparse-fixtures.md) | **Baselined** |
| **FR-5: Constrained Playlist**| SRS §3.1, §4.5, §4.7 | [`ST-FR5`](testing/acceptance-cases.md#st-fr5), [`UT-SOLVER`](testing/acceptance-cases.md#ut-solver), [`NEG-CONSTRAINT`](testing/acceptance-cases.md#neg-constraint), [`SEC-APPROVAL`](testing/acceptance-cases.md#sec-approval) | [`playlist-constraints-and-duration-solver.md`](../brain/resources/playlist-constraints-and-duration-solver.md), [`proposal-disclosure-and-metadata-sanitization.md`](../brain/resources/proposal-disclosure-and-metadata-sanitization.md), [`confirmation-gate-and-action-lifecycle.md`](../brain/resources/confirmation-gate-and-action-lifecycle.md) | **Baselined** |

### 2.2 Course Skill Workflow: SK-2 (`video-to-playlist`)
The mandatory 5-step workflow specified in Project Brief §3 is fully baselined across C02, C03, and C06:
1. **Step 1 (Summarise seed video)**: Verified in [`ST-FR1`](testing/acceptance-cases.md#st-fr1) and [`SKE-SK2`](testing/acceptance-cases.md#ske-sk2).
2. **Step 2 (Find similar candidates)**: Verified in [`ST-FR1`](testing/acceptance-cases.md#st-fr1) and candidate bounds note.
3. **Step 3 (Propose playlist & ask consent)**: Read-only proposal with HMAC-SHA-256 token; detailed in [`curation-walkthrough.md#step-3`](curation-walkthrough.md#step-3-proposal-display--explicit-confirmation-gate).
4. **Step 4 (Create playlist after explicit human approval)**: Strict distinct turn; rate-limited writes ($\le 1\text{ write/s}$); detailed in [`confirmation-gate-and-action-lifecycle.md`](../brain/resources/confirmation-gate-and-action-lifecycle.md).
5. **Step 5 (Show playlist analysis)**: Read-only summary via `analyse_playlist`; verified in [`SKE-SK2`](testing/acceptance-cases.md#ske-sk2).

### 2.3 Product Testing Criteria (TQ-1 to TQ-6)
- **TQ-1 (Unit Tests)**: Parsers ([`UT-PARSE`](testing/acceptance-cases.md#ut-parse)), scoring ([`UT-SCORE`](testing/acceptance-cases.md#ut-score)), solver ([`UT-SOLVER`](testing/acceptance-cases.md#ut-solver)).
- **TQ-2 (Integration Tests)**: Provider mock transport ([`IT-PROVIDER`](testing/acceptance-cases.md#it-provider)), SQLite cache TTLs ([`IT-CACHE`](testing/acceptance-cases.md#it-cache)), quota tracking ([`IT-QUOTA`](testing/acceptance-cases.md#it-quota)).
- **TQ-3 (System Tests)**: End-to-end scripted MCP stdio cases ([`ST-MCP`](testing/acceptance-cases.md#st-mcp), [`ST-FR1`](testing/acceptance-cases.md#st-fr1) to [`ST-FR5`](testing/acceptance-cases.md#st-fr5)).
- **TQ-4 (Negative Tests)**: Malformed IDs, private/deleted videos, absent tags, quota exhaustion, no channel, expired auth ([`NEG-INPUT`](testing/acceptance-cases.md#neg-input), [`NEG-UNAVAILABLE`](testing/acceptance-cases.md#neg-unavailable), [`NEG-METADATA`](testing/acceptance-cases.md#neg-metadata), [`NEG-UPSTREAM`](testing/acceptance-cases.md#neg-upstream), [`NEG-NO-CHANNEL`](testing/acceptance-cases.md#neg-no-channel), [`NEG-AUTH`](testing/acceptance-cases.md#neg-auth)).
- **TQ-5 (CI Fixture vs Scheduled Live Smoke)**: PR CI uses recorded mocks/fixtures ([`CI-FIXTURE`](testing/acceptance-cases.md#ci-fixture)); dedicated scheduled workflow for live smoke test ([`CI-LIVE`](testing/acceptance-cases.md#ci-live)).
- **TQ-6 (Pre-flight Quota Enforcement)**: Zero outbound calls when projected cost exceeds remaining budget ([`IT-QUOTA`](testing/acceptance-cases.md#it-quota)).
- **Security Testing**: Minimum OAuth scopes, OS credential storage, zero secrets in repo, untrusted metadata prompt-injection defense ([`SEC-OAUTH`](testing/acceptance-cases.md#sec-oauth), [`SEC-SECRETS`](testing/acceptance-cases.md#sec-secrets), [`SEC-APPROVAL`](testing/acceptance-cases.md#sec-approval)).

---

## 3. Second Brain Knowledge Inventory (13 Research Notes)

The team's Second Brain (`brain/`) fulfills **SB-1 to SB-6**, containing 13 comprehensive, cross-linked research notes distributed evenly across all three teammates (4 notes per owner + 1 decision record):

```
brain/resources/
├── official-api-provider-design.md             # Aangir (Platform)
├── quota-budgeting-and-caching.md              # Aangir (Platform)
├── oauth-lifecycle-and-safe-storage.md         # Aangir (Platform)
├── fixture-provider-and-ci-isolation.md        # Aangir (Platform)
├── licensing-and-distribution.md               # Aangir (Decision Record)
├── candidate-retrieval-and-tfidf.md            # Harshil (Discovery)
├── missing-metadata-and-sparse-fixtures.md     # Harshil (Discovery)
├── account-activity-timestamp-provenance.md    # Harshil (Analytics)
├── ranking-evaluation-metrics.md               # Harshil (Ranking)
├── playlist-constraints-and-duration-solver.md # Ayush (Curation)
├── proposal-disclosure-and-metadata-sanitization.md # Ayush (Curation)
├── confirmation-gate-and-action-lifecycle.md   # Ayush (Curation)
└── skill-format-and-upstream-specification.md  # Ayush (Skills)
```

Every note adheres to the strict YAML frontmatter standard (`title`, `author`, `date`, `type`, `status`, `srs_ids`, `sources`, `evidence`, `uncertainty`) and contains zero secrets, tokens, or PII.

---

## 4. Reconciliation of Appendix C Decisions (TBD-1 to TBD-11)

The table below reconciles all 11 open decisions from condensed SRS Appendix C, documenting their assigned owner, target milestone, and current Stage 1 status:

| TBD ID | Title / Topic | Owner | Target Milestone | Stage 1 Status & Actionable Resolution |
| :--- | :--- | :--- | :--- | :--- |
| **TBD-1** | Official course dates and demo format | Ayush Patel | When published by staff | **Open.** Awaiting course staff announcement; no speculative dates added. |
| **TBD-2** | Demo client and MCP elicitation support | Aangir Doshi | Stage 2 / C10 | **Open.** C10 harness will probe MCP elicitation vs explicit conversational fallback. |
| **TBD-3** | Liked video timestamps and trend fallback | Harshil Srivastav | Stage 1 / C05 & Stage 3 / C23 | **Baselined.** Researched in C05; publication-date fallback with warning implemented. |
| **TBD-4** | Ranking weights and provisional 0.60 precision@5 target | Harshil Srivastav | Stage 3 / C26 | **Open.** Evaluation methodology documented in C05; 0.60 evaluated in C26. |
| **TBD-5** | Repository license | Aangir Doshi | Stage 1 / C04 | **Baselined.** Evaluated MIT vs Apache 2.0 in C04; team consensus ready for C36. |
| **TBD-6** | Minimum YouTube write scope in ADR-003 | Aangir Doshi | Stage 2 / C10 | **Open.** ADR-003 will evaluate `youtube` vs `youtube.force-ssl`. |
| **TBD-7** | Reauthorisation plan for live demo | Aangir Doshi | Before Stage 4 / C31 | **Open.** 7-day token expiry renewal runbook to be authored before viva. |
| **TBD-8** | Minimum 20 labelled public seeds | Harshil Srivastav | Stage 2 / C08 | **Open.** Selection and labeling scheduled for C08. |
| **TBD-9** | Suitability of 30-item default | Ayush Patel | Stage 3 / C18 & C27 | **Open.** Feasibility and cost analysis scheduled during solver implementation. |
| **TBD-10**| Upstream Agent Skill frontmatter & format limits | Ayush Patel | Stage 1 / C06 | **Closed.** Researched and documented in C06 (`skill-format-and-upstream-specification.md`). |
| **TBD-11**| API allocation and method costs | Aangir Doshi | Stage 3 / C19 & C31 | **Baselined.** Initial 10k unit / 100 search baseline established in C04; live validation in C19. |

---

## 5. Milestone Sign-Off & Stage 2 Handoff

### Stage 1 Criteria Checklist
- [x] Condensed Word SRS (`FocusList_SRS_Condensed.docx` v1.1) and Project Brief (`Project_1_YouTube_MCP.pdf`) tracked and verified.
- [x] Traceability matrix (`docs/requirements-traceability.md`) established with 42 criteria.
- [x] Acceptance test cases (`docs/testing/acceptance-cases.md`) authored with 41 Given/When/Then scenarios.
- [x] Curation acceptance walkthrough (`docs/curation-walkthrough.md`) authored with 7 end-to-end scenarios.
- [x] Second Brain vault structure (`brain/`) initialized with Master Index and Activity Log.
- [x] 13 comprehensive research notes delivered (4 per owner + 1 decision record).
- [x] Upstream skill format verified and TBD-10 resolved.
- [x] All PR CI tests use synthetic fixtures/mocks with zero real credentials or account data.

### Handoff to Stage 2 (Design and Shared Contracts)
The requirements baseline is closed. The project proceeds to **Stage 2**:
- Next assignment: **C07 (`chore(build): scaffold the Python MCP service`)** owned by **Aangir Doshi**.
- Deliverables: Python project layout (`src/focuslist/`), packaging, CLI entry points (`focuslist serve`), MCP stdio transport registration, and initial unit test suite.
