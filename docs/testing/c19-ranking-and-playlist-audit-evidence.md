# C19 Ranking and Playlist Audit Evidence

Verified 29 November 2026 (IST). C19 started from published C18 revision `f5efe08`, which includes the fixture CI repair. The paired evaluation ran on the frozen public C08 labels. Playlist verification used a fixed UTC clock, synthetic records and a mocked official provider. [C19 plan](../../FocusList_Commit_Plan.md#c19-publish-scoring-evidence-and-playlist-audit) · [SRS](../../FocusList_SRS_Condensed.docx)

## FR-6 and paired evaluation

The four ranking paths share the same score explanation format. It publishes named raw values, active weights, their products, up to five shared terms, named missing fields and a locally computed reason. FR-3 retains the bounded list of contributing account items or channels. FR-5 keeps the existing selection math and adds the explanation to the returned proposal. Reading `focuslist://config/scoring` and constructing explanations require zero provider calls.

Both rankers returned precision@5 **0.5300** and MRR **0.904166666667** on 20 seeds with 19 candidates each. Weighted precision is **0.0700 below** the provisional target. The order was identical for every seed, and both arms had 281 adjacent score ties. The comparison leaves the SRS defaults intact and supplies the evidence for TBD-4 and TBD-8. The optional local Linux benchmark measured **4.400 ms p95** over 20 weighted runs with 150 synthetic candidates on WSL Python 3.12.13. GitHub-hosted timing remains pending. [Reproduction command and interpretation](ranking-evaluation.md#c19-results) · [Per-seed and aggregate results](ranking-evaluation-c19-results.json)

## FR-12 interface for C20 and C21

Call `analyse_playlist` with `playlist_url_or_id` and an optional integer `item_limit` from 1 to 500, default 500. C21 can pass the `playlist_id` from a successful creation to this tool in the same session. Use `total_items`, `total_duration` and `top_channels` for the short analysis. Check `truncated` and `unavailable_items` before presenting it as a complete summary. The results also provide:

- `reported_item_count` from playlist metadata when known, and counts for readable and unavailable positions.
- Known-duration total and a histogram with lower-inclusive, upper-exclusive cutoffs of 5, 10, 20, 40 and 60 minutes. Unknown durations are counted separately.
- Top five channels, category IDs and primary-language distributions. Channel shares use the number of readable positions with known channels as the denominator. Missing fields are counted explicitly. The publication range uses known UTC years.

`audit_playlist` returns that summary with issue rows, counts, applied thresholds and an optional health score. Pass `max_item_length_minutes` from 1 to 1440 to enable an over-length check. Pass `stale_after_years` from 1 to 100 to override the five-calendar-year default. Flag only durations strictly greater than the limit and timestamps strictly before the UTC cutoff. Title duplicates use normalized token-count cosine at or above 0.90 between different videos. Exact ID repeats cite the earliest position. Unavailable rows retain their position even without a video ID and are excluded from metadata and runtime totals.

Both tools reserve `2 × ceil(item_limit / 50) + 1` units before dispatch. That covers one playlist lookup, a maximum of one item page per 50 requested positions and at most one detail lookup per 50 distinct IDs. The default admits up to 21 units and zero searches. Next-page signals mark a truncated scan without an extra probe. An explicitly empty playlist costs one metadata call. This bounded plan uses single-attempt reads and bypasses the shared public-video cache for account-sensitive hydration. The returned quota metadata reports actual attempts. [YouTube playlist lookup](https://developers.google.com/youtube/v3/docs/playlists/list) · [YouTube entry pagination](https://developers.google.com/youtube/v3/docs/playlistItems/list)

## SK-6 and read-only acceptance

The packaged skill estimates quota first, calls the audit only if feasible and renders suggestions by position. It performs no mutations. The three deterministic cases cover a clean result, findings with suggested fixes, and quota denial before a provider call. The real MCP fixture checks both tools on a 501-position source, including the exact eligible positions, private/deleted placeholders, cutoff flags and a 500-position truncation signal. [SK-6 package](../../skills/playlist-audit/SKILL.md) · [ST-FR12](acceptance-cases.md#st-fr12) · [SKE-SK6](acceptance-cases.md#ske-sk6) · [Scripted MCP tests](../../tests/system/test_c19_playlist_stdio.py)

Each tool used 21 fixture reads on the 501-position case, consisting of one playlist lookup, ten item pages and ten detail batches. The first 500 positions contained 498 readable entries, two placeholders and 150,000 known runtime seconds. The clean and flagged skill cases each used three fixture reads. An infeasible estimate, direct quota denial, invalid URL and invalid age threshold all made zero provider calls. All cases made zero writes.

## Commands and outcomes

| Command | Linux Python 3.11.18 | Linux Python 3.12.13 |
| --- | --- | --- |
| `python -m ruff check .` | Passed | Passed |
| `python -m mypy --ignore-missing-imports src/focuslist` | Passed 42 files | Passed 42 files |
| `FOCUSLIST_PROVIDER=fixture python -m pytest -q --cov=focuslist --cov-report=term --tb=short` | 296 passed in 26.81 s | 296 passed in 25.91 s |
| `FOCUSLIST_PROVIDER=fixture python -m focuslist.platform.compliance` | Passed, including SK-6 inventory and SK-1 teardown | Passed, including SK-6 inventory and SK-1 teardown |

The local coverage report measured 84% overall and 82% in the shared scoring module, which includes provider and authorization helpers. The standard coverage run does not collect the child MCP server's execution. Release coverage enforcement stays with C22. The Linux evaluation reproduced the saved ranking file byte for byte. Hosted benchmark evidence and teammate review remain pending.
