---
name: local-check
description: Run offline FocusList build, fixture test suite, MCP stdio startup, and fixture video lookup diagnostics with guaranteed subprocess cleanup.
---

# local-check (SK-1)

Verify FocusList locally in safe offline **fixture mode** without credentials, YouTube API calls, or mutations to user data.

## Linked Second Brain Evidence

- [Synthetic Fixture Provider, Fault Injection, and CI Isolation](../../brain/resources/fixture-provider-and-ci-isolation.md)
- [Quota Budget Management, Caching Strategy, and Dry-Run Estimation](../../brain/resources/quota-budgeting-and-caching.md)

## Execution Protocol

Run `focuslist.skills.local_check.run_local_check` (or `focuslist doctor` for environment, quota, and safe token-age inspection):

1. **Build (`build`)**: Validate package installation and dependencies (`pip check` or editable build).
2. **Test (`test`)**: Execute offline fixture tests (`pytest -q`) using `FOCUSLIST_PROVIDER=fixture` and an isolated temporary SQLite path.
3. **Startup (`startup`)**: Launch `focuslist serve --provider fixture` over stdio with temporary DB/auth directories so existing user state is untouched.
4. **Fixture Lookup (`fixture_fetch`)**: Invoke `get_video_details` for `syn_vid0001` via JSON-RPC 2.0 stdio, verifying `untrusted_metadata: true` and zero writes.

Each stage reports `PASS`, `FAIL`, or `SKIPPED`. Any failure terminates downstream stages as `SKIPPED` while guaranteeing subprocess teardown in `finally`.

## Deterministic Evaluation Cases (`SKE-SK1`)

1. **Happy Path (Positive)**: Build, test, MCP stdio startup, and fixture `get_video_details` all report `PASS` within the 120-second CI target with zero leftover processes.
2. **Induced Build/Test Failure (Negative)**: A failing build or test stage reports `FAIL`, marks downstream `startup` and `fixture_fetch` as `SKIPPED`, returns `overall_status = FAIL`, and leaves user data untouched.
3. **Induced MCP Startup/Fetch Failure (Negative/Teardown)**: A failing MCP startup or lookup reports `FAIL`, skips remaining stages, closes the stdio subprocess cleanly, and preserves existing local DB files.
