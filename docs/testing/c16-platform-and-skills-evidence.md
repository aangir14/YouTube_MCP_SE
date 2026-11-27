# C16 Platform, Skills, and Offline CI Verification Evidence

- **Commit ID:** C16 (`feat(platform): integrate storage quota OAuth and offline checks`)
- **Owner:** Aangir Doshi (`aangir14`)
- **Date:** 2026-11-27 (IST)
- **Provider Mode:** `fixture` / mocked Google transport and fake clock (`FakeClock`) — **0 live YouTube calls, 0 live writes**

## 1. Executed Commands and Outcomes

| Check | Command | Outcome | Notes |
| :--- | :--- | :--- | :--- |
| Lint | `python -m ruff check .` | **PASS** | `All checks passed!` across `src/` and `tests/` |
| Full offline suite | `FOCUSLIST_PROVIDER=fixture python -m pytest -v` | **PASS (231 passed in 32.09s)** | Covers C07–C16 unit, integration, and real MCP stdio tests |
| Opening PR fixture gate | `run_fixture_gate(Path('.'), tmp_dir)` | **PASS** | Import boundary clean, 0 secret matches, `mcp-reference.md` in sync, `local-check` & `brain-refine` valid |
| SK-1 `local-check` run | `run_local_check(Path('.'))` | **PASS (15.27s)** | `build` (1.39s), `test` (10.92s), `startup` (2.97s), `fixture_fetch` (0.00s); `subprocess_terminated=True`, well under 120s target |

## 2. Workstream Coverage Summary

- **Legacy C16 (`tests/unit/test_storage_cache_and_state.py`):** Repeat schema migrations idempotent on existing SQLite DB (WAL + `foreign_keys=ON`), SRS TTL buckets (24h/6h/7d/30d max), proposal `expires_at + 7d` and 30-day ledger/history retention, append-only `action_history` trigger, account-scoped purge, concurrent `BEGIN IMMEDIATE` proposal claims (1 winner / 5 rejected), and `focuslist purge` CLI tests (`tests/system/test_platform_mcp_and_cli.py`).
- **Legacy C19 (`tests/unit/test_quota_and_gateway.py`):** Local `estimate_quota` and `get_quota_status` / `focuslist quota` parity, Appendix B 12-item baseline (`651` confirm units, `15` proposal units / `3` searches preflight), C15 proposal wired to observed dispatch charges + both buckets + 5% margin + `2,600` request cap, Pacific midnight rollover (`America/Los_Angeles` with portable DST fallback), cache hit at 0 cost, COM-5 retries charged per attempt, exhaustion stop with 0 follow-up attempts, and concurrent budget competition.
- **Legacy C22 (`tests/unit/test_oauth_and_storage.py`):** External OAuth config validation (in-repo secrets rejected), PKCE S256 + `127.0.0.1` ephemeral loopback listener with CSRF `state` validation and guaranteed closure, `youtube.readonly` initial login with `youtube.force-ssl` gated on confirmed write intent, user-only file/keyring storage separate from SQLite, automatic refresh, day-5 Testing-mode warning, `invalid_grant` purge (`AUTH_EXPIRED`), consent decline (`AUTH_CANCELLED`), logout revocation + account cache purge, and log secret redaction (`SecretRedactingFilter`).
- **Legacy C25 (`tests/unit/test_write_primitives.py`, `tests/system/test_platform_mcp_and_cli.py`):** `WriteAuthorizationContext` enforcement on `LiveVideoProvider.create_playlist`, `insert_playlist_item`, and `delete_playlist`; `NO_YOUTUBE_CHANNEL`, `AUTH_REQUIRED`, `QUOTA_EXHAUSTED`, and `AmbiguousWriteError` on timeout with zero blind replay; stored approved visibility enforcement (`private`/`unlisted`/`public`); and fail-closed MCP guard on `confirm_playlist` and `undo_playlist` producing 0 writes on placeholder, unsigned, tampered, or unapproved actions.
- **Legacy C28 (`tests/unit/test_skills_local_check_and_brain_refine.py`):** `SK-0`/`TBD-10` validation for `local-check` (`SKE-SK1`: happy path, induced build failure -> `SKIPPED`, induced MCP failure -> guaranteed teardown) and `brain-refine` (`SKE-SK4`: inbox-to-PARA organisation, duplicate merge retaining provenance, broken-link repair + invalid frontmatter/secret canary rejection).

## 3. Pending Checks (Tracked for C20–C22 and PR Review)

- Teammate reviews on GitHub PR (both other teammates required for **FR-9** changes and guarded confirmation route).
- First remote GitHub Actions run of `.github/workflows/pr-fixture-ci.yml` across Python `3.11` and `3.12`.
- Clean-clone 15-minute usability timing (`NFR-USA`) and 80%/90% coverage gate enforcement after C17–C21 (`C22`).
- Remaining 4 skills (`video-to-playlist`, `brain-ingest`, `brain-query`, `playlist-audit`) and scheduled live smoke workflow (`C20`–`C22`).
