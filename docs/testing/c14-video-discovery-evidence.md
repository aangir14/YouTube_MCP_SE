# C14 Video Discovery Verification

[C14 plan](../../FocusList_Commit_Plan.md#c14-rank-similar-videos-and-return-video-details) · [ST-FR1](acceptance-cases.md#st-fr1) · [UT-SCORE](acceptance-cases.md#ut-score) · [NEG-INPUT](acceptance-cases.md#neg-input) · [NEG-UNAVAILABLE](acceptance-cases.md#neg-unavailable) · [NEG-METADATA](acceptance-cases.md#neg-metadata)

## Reproduce

Run from the repository root with the documented dev environment, `src` on the Python path if the project is not installed, and `FOCUSLIST_PROVIDER=fixture`.

~~~text
python -m pytest -q -s tests/system/test_video_discovery_stdio.py
python -m pytest -q tests/unit/test_video_ranking.py tests/integration/test_live_provider_mock.py
python -m pytest -q
python -m ruff check .
~~~

The C10 test client launches an actual MCP stdio subprocess. The test-only launcher injects a synthetic fixture provider with fixed ID pages and saves its observed counters in the test's temporary directory. Use the `C14_COUNTS`, `C14_FULL_PAGE_COUNTS` and `C14_BUDGET_COUNTS` lines to reproduce the observations below. Counts here are per call or per repeated failure case, calculated from the test's cumulative snapshots.

## Observed fixture stdio calls

| Case | Provider requests | Simulated attempts | Detail batch sizes | Search pages | Upload pages | General units shown | Writes |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| Malformed ID or out-of-range limit, each | 0 | 0 | — | 0 | 0 | 0 | 0 |
| Valid syntax for missing or private seed, each | 1 | 1 | 1 | 0 | 0 | 1 | 0 |
| Single video fact sheet | 1 | 1 | 1 | 0 | 0 | 1 | 0 |
| Ranking with duplicates, sparse metadata and ineligible rows | 5 | 5 | 1, 12 | 2 | 1 | 3 | 0 |
| Full 150-candidate ranking | 7 | 7 | 1, 50, 50, 50 | 2 | 1 | 5 | 0 |
| Over-budget request with a 5-unit ceiling | 0 | 0 | — | 0 | 0 | 0 | 0 |

In the mixed ranking fixture, the tools hydrated 12 distinct candidate IDs and returned four eligible videos. The first three had equal feature scores and sorted by newest publication, then ID. The sparse video stayed eligible and disclosed missing tags, language and publication time. The test checked the 500-character untrusted description cap, zero-valued public counts, missing/private seeds, rejected inputs, weights and contribution sums, deterministic equivalent URL results, and 10/50-result bounds. The fixture made no outbound YouTube calls.

## Official provider path with mocked Google transport

The full C13 provider path used two `search.list` requests, one `channels.list` uploads lookup, one `playlistItems.list` page, and four `videos.list` calls with batch sizes 1, 50, 50 and 1. The mock continued to advertise a search page token, and neither search followed it. This is **two search calls and six general units**. A fixture upload lookup simulates one combined attempt; the official path uses two endpoints. Candidate ID methods return no hydrated records, so duplicate IDs are removed before details are fetched.

The shared parser rejects invalid references before admission. FR-1 checks its bounded plan against the existing process-local quota configuration, accounts for observed attempts by bucket, and makes no retries. The persistent daily ledger, cache accounting and shared admission across tools remain with C19. Product relevance measurements and the shared scoring resource remain with C26.
