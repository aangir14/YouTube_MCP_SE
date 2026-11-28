# C18 Playlist Approval Verification

28 November 2026 (IST). C18 was developed from GitHub `main` at `d416ae3`. Verification used synthetic fixtures, a fake clock and mocked writes. No live YouTube requests or writes were made. [C18 plan](../../FocusList_Commit_Plan.md#c18-finish-ordered-playlists-and-confirmed-writes) · [ADR-004](../adr/ADR-004-playlist-action-lifecycle-and-threat-model.md#9-c18-implementation-decisions) · [Client procedure](../curation-walkthrough.md#c18-client-procedure)

| Check | Python 3.11.18 on Linux | Python 3.12.13 on Linux |
| --- | --- | --- |
| `python -m ruff check .` | Passed | Passed |
| `FOCUSLIST_PROVIDER=fixture python -m pytest -q --cov=focuslist --cov-report=term --tb=short` | 282 passed in 22.34 s | 282 passed in 23.82 s |
| Statement coverage | 86% overall, 93% approval, 91% execution, 100% ordering | 86% overall, 93% approval, 91% execution, 100% ordering |
| `FOCUSLIST_PROVIDER=fixture python -m focuslist.platform.compliance` | Passed with local-check teardown confirmed in 3.10 s | Passed with local-check teardown confirmed in 3.77 s |

The standalone C18 revision reported the same 32 mypy diagnostics as the merged baseline. After stacking C18 on the separate C16–C17 CI repair, `python -m mypy --ignore-missing-imports src/focuslist` passed all 38 source files on Linux Python 3.11 and 3.12. Ruff and fixture compliance passed again. `python -m pytest -q --tb=short` passed 282 tests on both versions in 19.41 s and 22.17 s, respectively. Hosted CI is pending.

## Acceptance evidence

| Workstream | Observed result |
| --- | --- |
| FR-8 and TQ-1 | All three ordering modes, numeric same-channel series, near-duplicate removal, the three-per-channel cap, and oversize single-item sessions passed. Each of 1,000 seeded inputs produced identical results after reversal and preserved applicable hard constraints and session membership. A 200-candidate synthetic case with four-minute videos selected 30 items for exactly two hours and 1,551 baseline write units. [Solver tests](../../tests/unit/test_curation_constraints_and_solver.py) |
| FR-7 signed action and SEC-APPROVAL | Changes to all signed fields tested, an incorrect signature, the wrong account or action, supersession, expiry, a missing decision and decline were rejected. Zero provider calls and writes were asserted where the rejection occurs before provider business checks. Concurrent confirmation executed one sequence. Fifteen synthetic metadata cases exercised titles, channel text, descriptions and tags with the real proposal path. The exact action survived sanitation and none of the metadata supplied approval. [Approval tests](../../tests/unit/test_c18_playlist_execution.py) |
| ST-FR5 and TQ-6 | The real MCP stdio fixture displayed and confirmed twelve ten-minute items. The provider trace recorded one channel check, one create and twelve ordered inserts at least one fake second apart. Cost was 651 general units. Budget failure made zero provider calls. A missing channel made one eligibility call and zero writes. Replaying the same successful action after restart returned the recorded result and made zero calls. [Scripted MCP cases](../../tests/system/test_c18_playlist_stdio.py) |
| FR-9 boundary | Mocked incremental consent was reached only after valid human approval and quota admission. The original channel could proceed. A different channel made zero writes and restored the prior read grant. Live OAuth consent and real account identity parity remain to be verified in the scheduled workflow. [Mocked authorization tests](../../tests/unit/test_c18_playlist_execution.py) |
| ST-FR7 recovery and undo | A fresh server process read the original partial result and proposed only the remaining positions. A fresh approval was needed before inserts. A changed prefix blocked resume. Ambiguous create used the exact signed creation marker and did not create again. Ambiguous insert used the verified position or stopped without another write. Undo proposals made zero calls, approved deletion targeted the exact playlist once, and replay or unresolved deletion made no second write. The retention test covered undo after the original proposal was purged. [Recovery tests](../../tests/unit/test_c18_playlist_execution.py) · [Scripted MCP cases](../../tests/system/test_c18_playlist_stdio.py) |
| TBD-2 and NFR-SAF | An eliciting scripted client received the exact review, including title, privacy and ordered IDs. A non-eliciting scripted client rejected a token alone, rejected piped input, and accepted the action after a separately simulated interactive terminal approval. The team's chosen AI client remains unverified. [Client test](../../tests/system/test_c18_playlist_stdio.py) |

Both other teammates' formal FR-7 review remains outstanding. Hosted performance evidence and the chosen-client demonstration remain open.
