# FocusList Second Brain Master Index

This master index catalogs all distilled research notes, architectural decision records, and operational guides within the FocusList Second Brain (`brain/`), fulfilling requirements **SB-1 to SB-6** and **SE-5**.

---

## 1. Master Vault Note Catalog

| Note Title | File Path | Author | Date | Type | Status | Covered SRS IDs | Planned Verification Links |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Official YouTube Data API v3 and VideoProvider Architecture** | [`resources/official-api-provider-design.md`](resources/official-api-provider-design.md) | Aangir Doshi | 2026-11-19 | Research Note | Active | FR-11.1–11.3, FR-1.9, COM-1–6 | [`IT-PROVIDER`](../docs/testing/acceptance-cases.md#it-provider), [`ST-FR11`](../docs/testing/acceptance-cases.md#st-fr11), [`NEG-UPSTREAM`](../docs/testing/acceptance-cases.md#neg-upstream) |
| **Quota Budget Management, Caching Strategy, and Dry-Run Estimation** | [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md) | Aangir Doshi | 2026-11-19 | Research Note | Active | FR-10.1–10.9, FR-11.4–11.9, NFR-QUOTA-01, DB-1–3, TBD-11 | [`IT-QUOTA`](../docs/testing/acceptance-cases.md#it-quota), [`IT-CACHE`](../docs/testing/acceptance-cases.md#it-cache), [`ST-FR10`](../docs/testing/acceptance-cases.md#st-fr10) |
| **OAuth 2.0 Lifecycle, Safe Credential Storage, and Least Privilege** | [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md) | Aangir Doshi | 2026-11-19 | Research Note | Active | FR-9.1–9.9, COM-1–4, NFR-SEC, TBD-6, TBD-7 | [`SEC-OAUTH`](../docs/testing/acceptance-cases.md#sec-oauth), [`SEC-SECRETS`](../docs/testing/acceptance-cases.md#sec-secrets), [`NEG-AUTH`](../docs/testing/acceptance-cases.md#neg-auth), [`ST-FR9`](../docs/testing/acceptance-cases.md#st-fr9) |
| **Synthetic Fixture Provider, Fault Injection, and CI Isolation** | [`resources/fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md) | Aangir Doshi | 2026-11-19 | Research Note | Active | FR-11.1–11.3, TQ-1–6, NFR-SEC, COM-5–6 | [`CI-FIXTURE`](../docs/testing/acceptance-cases.md#ci-fixture), [`CI-LIVE`](../docs/testing/acceptance-cases.md#ci-live), [`IT-PROVIDER`](../docs/testing/acceptance-cases.md#it-provider), [`NEG-UPSTREAM`](../docs/testing/acceptance-cases.md#neg-upstream) |
| **Project Licensing Evaluation, Third-Party Compliance, and TBD-5 Tracking** | [`resources/licensing-and-distribution.md`](resources/licensing-and-distribution.md) | Aangir Doshi | 2026-11-19 | Decision Record | Draft | L-1 to L-6, TBD-5 | [`FocusList_Commit_Plan.md#7`](../FocusList_Commit_Plan.md#7-decisions-carried-forward-from-appendix-c) |

---

## 2. Requirement-to-Note Traceability Index

This section maps core SRS requirements to their authoritative research notes and specifications:

### Platform, Provider, and Offline Execution (FR-11)
- **FR-11.1 (VideoProvider interface)**: [`resources/official-api-provider-design.md`](resources/official-api-provider-design.md), [`resources/fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md)
- **FR-11.2 (Google client confined to `platform/`)**: [`resources/official-api-provider-design.md`](resources/official-api-provider-design.md)
- **FR-11.3 (Fixture provider & fault wrapper)**: [`resources/fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md)
- **FR-11.4 (Cache TTLs: 24h video/channel, 6h user, 7d categories)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-11.5 (Startup & daily cache purges)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-11.6 (Purge authorized data on logout)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md), [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-11.7 (Synthetic fixture scrubbing & privacy)**: [`resources/fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md)
- **FR-11.8 (Pagination capping & charging)**: [`resources/official-api-provider-design.md`](resources/official-api-provider-design.md), [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-11.9 (Zero-quota cache hits)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)

### Quota Budget Management and Estimation (FR-10, NFR-QUOTA-01)
- **FR-10.1 (Dual budgets: 10k general units, 100 searches)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.2 (Pre-flight rejection & 5% safety margin)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.3 (Per-request cap of 2,600 units)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.4 (Local `estimate_quota` tool)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.5 (Ledger reporting: units used, remaining, search calls, cache hits)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.6 (Pacific midnight reset)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.7 (Charge actual network attempts & retries)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.8 (Upstream exhaustion marking & stop)**: [`resources/official-api-provider-design.md`](resources/official-api-provider-design.md), [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **FR-10.9 (Scheduled live smoke budget: $\le 500$ units, 5 searches)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md), [`resources/fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md)

### Authentication, Authorisation, and Credential Storage (FR-9, NFR-SEC)
- **FR-9.1 (Auth code flow with PKCE)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.2 (Config loaded from outside repo)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.3 (Least-privilege scoping: readonly first, write at confirmed create)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.4 (OS credential store & user-only fallback file)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.5 (Automatic refresh & `AUTH_EXPIRED` on `invalid_grant`)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.6 (Display auth status, scopes, expiry without token values)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.7 (7-day Testing expiry & day-5 proactive warning)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.8 (Immediate revocation and purge on logout)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md)
- **FR-9.9 (Channel requirement: `NO_YOUTUBE_CHANNEL` on failure)**: [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md), [`resources/official-api-provider-design.md`](resources/official-api-provider-design.md)

### Database and Storage Integrity (DB-1 to DB-3)
- **DB-1 (SQLite in WAL mode with foreign keys)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **DB-2 (Atomic transactions & proposal uniqueness)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)
- **DB-3 (Append-only action history and 30-day retention)**: [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md)

---

## 3. Verification Task Cross-Reference

| Planned Test Scenario | Testing Document | Authoritative Research Notes |
| :--- | :--- | :--- |
| **`IT-PROVIDER`** | [`acceptance-cases.md#it-provider`](../docs/testing/acceptance-cases.md#it-provider) | [`official-api-provider-design.md`](resources/official-api-provider-design.md), [`fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md) |
| **`IT-QUOTA`** | [`acceptance-cases.md#it-quota`](../docs/testing/acceptance-cases.md#it-quota) | [`quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md) |
| **`IT-CACHE`** | [`acceptance-cases.md#it-cache`](../docs/testing/acceptance-cases.md#it-cache) | [`quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md) |
| **`CI-FIXTURE`** | [`acceptance-cases.md#ci-fixture`](../docs/testing/acceptance-cases.md#ci-fixture) | [`fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md) |
| **`CI-LIVE`** | [`acceptance-cases.md#ci-live`](../docs/testing/acceptance-cases.md#ci-live) | [`fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md), [`quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md) |
| **`ST-FR9`** | [`acceptance-cases.md#st-fr9`](../docs/testing/acceptance-cases.md#st-fr9) | [`oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md) |
| **`ST-FR10`** | [`acceptance-cases.md#st-fr10`](../docs/testing/acceptance-cases.md#st-fr10) | [`quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md) |
| **`ST-FR11`** | [`acceptance-cases.md#st-fr11`](../docs/testing/acceptance-cases.md#st-fr11) | [`official-api-provider-design.md`](resources/official-api-provider-design.md), [`fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md) |
| **`SEC-OAUTH`** | [`acceptance-cases.md#sec-oauth`](../docs/testing/acceptance-cases.md#sec-oauth) | [`oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md) |
| **`SEC-SECRETS`**| [`acceptance-cases.md#sec-secrets`](../docs/testing/acceptance-cases.md#sec-secrets) | [`oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md), [`fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md) |
| **`NEG-AUTH`** | [`acceptance-cases.md#neg-auth`](../docs/testing/acceptance-cases.md#neg-auth) | [`oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md) |
| **`NEG-UPSTREAM`**| [`acceptance-cases.md#neg-upstream`](../docs/testing/acceptance-cases.md#neg-upstream) | [`official-api-provider-design.md`](resources/official-api-provider-design.md), [`fixture-provider-and-ci-isolation.md`](resources/fixture-provider-and-ci-isolation.md) |

---

## 4. TBD Decision Tracking (Appendix C)

| ID | Title / Topic | Owner | Relevant Note / Document | Target Milestone | Status & Actionable Next Step |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TBD-5** | Repository Licence & Distribution | Aangir Doshi | [`resources/licensing-and-distribution.md`](resources/licensing-and-distribution.md) | Stage 1 close / C04–C06 | **Open / Baselined**: MIT vs Apache 2.0 evaluated. Team confirmation in Stage 1 review; publication verified in C36. |
| **TBD-6** | Minimum YouTube Write Scope | Aangir Doshi | [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md) | Stage 2 / C10 | **Open**: Compare `youtube` vs `youtube.force-ssl` in ADR-003. |
| **TBD-7** | Live Demo Reauthorisation Plan | Aangir Doshi | [`resources/oauth-lifecycle-and-safe-storage.md`](resources/oauth-lifecycle-and-safe-storage.md) | Before Stage 4 / C31 | **Open**: Capture re-auth checklist for testing-mode 7-day token renewal. |
| **TBD-11**| YouTube Quota Allocations & Method Costs | Aangir Doshi | [`resources/quota-budgeting-and-caching.md`](resources/quota-budgeting-and-caching.md) | Stage 3 / C19 & C31 | **Open / Baselined**: Initial 10k/100 search baseline established. Validate live Google Cloud metrics in C19. |

---

## 5. Teammate Contribution Dashboard (SB-5)

| Teammate | Assigned Commits | Delivered Research Notes | AI Sessions Logged | Status |
| :--- | :--- | :---: | :---: | :--- |
| **Aangir Doshi** (BT2024078) | C01, C04, C07, C10, C13, C16, C19, C22, C25, C28, C31, C36 | 4 notes (`official-api`, `quota-budgeting`, `oauth-storage`, `fixture-ci`) + 1 decision record (`licensing`) | C01, C04 logged | Active (C04 Delivered) |
| **Harshil Srivastav** (BT2024187) | C02, C05, C08, C11, C14, C17, C20, C23, C26, C29, C32, C34 | 4 notes scheduled in C05 | C02 logged | Pending C05 |
| **Ayush Patel** (BT2024171) | C03, C06, C09, C12, C15, C18, C21, C24, C27, C30, C33, C35 | 4 notes scheduled in C06 | C03 logged | Pending C06 |
