# C16 and C17 Verification

Reviewed GitHub `main` at `d416ae3` on 28 November 2026 (IST) against the condensed SRS, course brief and commit plan. All execution used fixtures or synthetic mock responses. The checks made zero live YouTube calls and zero writes. [C16 plan](../../FocusList_Commit_Plan.md#c16-build-the-platform-and-offline-checks) · [C17 plan](../../FocusList_Commit_Plan.md#c17-deliver-channels-recommendations-and-engagement)

## Fixture CI repair

The original workflow used `runner.temp` under job-level `env`. Actionlint rejected both references. The corrected runner step uses `RUNNER_TEMP` to export isolated DB and credential store paths through `GITHUB_ENV`. The original source also produced 32 mypy errors with the workflow dependencies. The repair keeps both Python versions and the original checks. [GitHub Actions context reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability) · [Workflow](../../.github/workflows/pr-fixture-ci.yml)

| Command | Local result |
| --- | --- |
| `actionlint .github/workflows/pr-fixture-ci.yml` | Passed. The original file failed with two invalid context expressions. |
| `python -m pip install -e ".[dev]" pytest-cov mypy` and `python -m ruff check .` | Passed on Linux Python 3.11 and 3.12. |
| `python -m mypy --ignore-missing-imports src/focuslist` | Passed all 35 source files on both versions. |
| `python -m pytest -v --cov=focuslist --cov-report=term-missing` | 235 passed with 85% total statement coverage on both versions. |
| `python -m focuslist.platform.compliance` | Import boundary, secret scan as currently scoped, installed skills and generated MCP reference passed. SK-1 completed in about five seconds per version with confirmed subprocess teardown. |

GitHub must run the repaired revision to produce a hosted result. Final skill inventory, coverage thresholds and scheduled live smoke remain in C20–C22. GitHub returned no submitted reviews for [C16 PR #15](https://github.com/aangir14/YouTube_MCP_SE/pull/15) or [C17 PR #16](https://github.com/aangir14/YouTube_MCP_SE/pull/16) during this audit.

## Assignment checks

| Workstream | Verified evidence | Open item |
| --- | --- | --- |
| C16 storage and purge, FR-11 and DB-1–DB-3 | Repeat migrations, retention, WAL, account isolation, one successful concurrent claim, CLI purge and MCP cache-hit checks passed. [Storage tests](../../tests/unit/test_storage_cache_and_state.py) · [MCP and CLI tests](../../tests/system/test_platform_mcp_and_cli.py) | None found in the cases run. |
| C16 quota, FR-10 and TQ-6 | Pacific rollover, zero-cost cache hits, exhausted buckets, concurrent reservations and zero-call rejection passed in the existing fixtures. [Quota tests](../../tests/unit/test_quota_and_gateway.py) | Composite official-provider calls can overrun the reservation. |
| C16 OAuth and write guards, FR-9 and FR-7 | Mocked PKCE, scope changes, refresh, expiry, logout and redaction passed. Mock writes covered visibility, positions and ambiguous timeout. Fixture MCP rejected unapproved confirmation and undo with zero writes. [OAuth tests](../../tests/unit/test_oauth_and_storage.py) · [Write tests](../../tests/unit/test_write_primitives.py) · [MCP guard tests](../../tests/system/test_platform_mcp_and_cli.py) | Both teammate reviews are still unverified. C18 owns end-to-end approval. |
| C16 skills and fixture CI, SK-1, SK-4 and TQ-5 | Success and induced teardown passed for local-check. Vault organisation, duplicate provenance and repaired links passed for brain-refine. [Skill tests](../../tests/unit/test_skills_local_check_and_brain_refine.py) | Fixture mode is selected, but there is no egress check to fail CI on accidental live access. The scanner skips most test files. Hosted CI and clean-clone usability timing are pending. |
| C17 channels, FR-2 | ID and handle agreed over MCP. Unit cases checked missing metadata, legacy rejection, scoring and zero writes. [ST-FR2](acceptance-cases.md#st-fr2) · [MCP tests](../../tests/system/test_c17_mcp_stdio.py) | The full rerank exceeded 25 units. MCP still needs the supported URL form and full candidate and rerank boundary assertions. |
| C17 recommendations, FR-3 | Subset recommendations passed over MCP. Unit cases verified zero provider calls without consent, seen-item exclusion, empty profiles, purge and SRS weights of 0.60/0.15/0.15/0.10. [ST-FR3](acceptance-cases.md#st-fr3) · [Unit cases](../../tests/unit/test_channels_recommendations_engagement.py) | The full source load exceeded 40 units. MCP still needs an all-sources case. |
| C17 engagement, FR-4 | Fixture MCP verified an explicit weekly comparison with zero searches. Unit cases checked 75% versus 50% channel share, +1 and +50% count delta, null percentage against zero, sparse data and timestamp fallback. [ST-FR4](acceptance-cases.md#st-fr4) · [C05 provenance](../../brain/resources/account-activity-timestamp-provenance.md) | MCP still needs the 30/90/365-day presets, monthly grouping and a three-source comparison. TBD-3 remains open. |

## Quota findings

Both probes used `ProviderGateway` with `LiveVideoProvider(service=mock)`, a fresh SQLite database, no retries and synthetic responses. All calls went to the mock.

| Probe | SRS baseline maximum | Measured result |
| --- | --- | --- |
| FR-2 with one seed and ten eligible candidates, each with public uploads | 25 general units and 3 searches | 35 general units, 1 search, 36 mock calls, 0 writes. |
| FR-3 with 200 likes, 200 subscriptions, five playlists of 100 items each, plus candidate search and uploads | 40 general units and 3 searches | 48 general units, 3 searches, 51 mock calls, 0 writes. |

The gateway records the cost of multi-endpoint calls after dispatch. The follow-up needs to plan calls within the FR-2 and FR-3 limits and enforce the reservation before pages and retries dispatch. Verify both full-input cases and include a rejected admission with zero mock calls and writes. [ADR-006](../adr/ADR-006-platform-storage-quota-and-write-contracts.md#3-open-quota-enforcement-finding) · [ST-FR10](acceptance-cases.md#st-fr10)
