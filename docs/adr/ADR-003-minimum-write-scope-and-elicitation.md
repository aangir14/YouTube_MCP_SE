# ADR-003: Minimum YouTube Write Scope and Demo Client Elicitation Evidence

- **Status:** Proposed (C10 baseline; live OAuth scope & live AI-client UI pending C22/C24)
- **Date:** 2026-11-25 (IST)
- **Owner:** Aangir Doshi (C10)
- **Stakeholders:** Ayush Patel (BT2024171), Harshil Srivastav (BT2024187)
- **Scope:** FR-7.5, FR-9.2, FR-9.3, TBD-2, TBD-6

[Condensed SRS §§2.7, 4.7, 4.9, Appendix C](../../FocusList_SRS_Condensed.docx) · [C10 plan](../../FocusList_Commit_Plan.md#c10-add-the-fixture-provider-and-mcp-test-harness) · [OAuth research note](../../brain/resources/oauth-lifecycle-and-safe-storage.md) · [ADR-001 shared contracts](ADR-001-service-architecture-and-contracts.md)

---

## 1. Minimum Writable OAuth Consent Scope (TBD-6)

### 1.1 Context
Per **FR-9.3** and **TBD-6**, FocusList applies least-privilege OAuth 2.0 authorization:
- Initial login for read/discovery/analytics requests only `https://www.googleapis.com/auth/youtube.readonly`.
- Playlist creation (`playlists.insert`), item insertion (`playlistItems.insert`), and confirmed undo (`playlists.delete`) require an incremental writable scope requested only at the first confirmed write.

### 1.2 Scope Comparison Against Official YouTube Data API v3 Docs
| OAuth Scope | Supported Write Endpoints | Risk & Privilege Surface | Suitability |
| :--- | :--- | :--- | :--- |
| `https://www.googleapis.com/auth/youtube.readonly` | **None** (read-only) | Minimal; cannot mutate playlists or account state. | **Default initial login scope.** |
| `https://www.googleapis.com/auth/youtube.force-ssl` | `playlists.insert`, `playlistItems.insert`, `playlists.delete`, plus comments/captions/live-chat mutations. | Broad write access over SSL, though narrower than full channel management. | **Candidate** (pending live Google OAuth consent screen & endpoint verification in C22). |
| `https://www.googleapis.com/auth/youtube` | `playlists.insert`, `playlistItems.insert`, `playlists.delete`, plus full YouTube account management (uploads, channel settings, deletions). | Broadest YouTube account management scope. | **Fallback** only if `youtube.force-ssl` is rejected by Google Cloud Testing-mode project configuration. |

*(Note: YouTube Data API v3 does not offer a `youtube.playlists.write`-only scope; `youtube.force-ssl` and `youtube` are the two official writable scopes listed for `playlists` and `playlistItems`.)*

### 1.3 Decision & Remaining Verification
- **Decision**: Target incremental upgrade from `youtube.readonly` to **`youtube.force-ssl`** (if accepted by Google's OAuth consent screen for Testing-mode apps) or `youtube` as documented fallback, requested only upon the first confirmed write action.
- **Pending Evidence**: Live OAuth consent-screen verification and mocked incremental scope upgrade tests remain scheduled for **C22** (`feat(auth): implement OAuth and credential lifecycle`).

---

## 2. Demo Client and MCP Elicitation Support (TBD-2)

### 2.1 Observed SDK & Harness Evidence (Offline)
Using the C10 scripted stdio harness (`tests/mcp_harness.py` with `mcp` SDK `1.x`, `FastMCP`, and `ClientSession`):
- **Server-side & Protocol Support**: `mcp.server.fastmcp` (`mcp<2`) supports JSON-RPC 2.0 `tools`, `resources`, and `prompts` over `stdio` cleanly, verified in `tests/system/test_mcp_stdio_harness.py`.
- **Elicitation Capability Status**: Standard MCP `ClientSession` in the scripted test harness does **not** render interactive UI prompts unless an explicit `elicitation_callback` is registered by the host AI client. Many desktop/CLI MCP hosts (including older client releases) do not yet implement interactive MCP `elicitation/create` requests uniformly.

### 2.2 Decision & Approval Path
- **Decision**: FocusList **must not rely solely on MCP elicitation** to enforce the FR-7 human approval gate.
  1. When the host client advertises MCP elicitation capability and `elicitation_callback` is available, FocusList may request structured confirmation through elicitation.
  2. In all other cases (including the offline scripted harness and standard conversational clients), `propose_playlist` / `undo_playlist` returns the read-only proposal with its signed `token`, and `confirm_playlist` requires a separate explicit human-confirmed turn per **ADR-004**.
- **Pending Evidence**: Manual end-to-end UI approval verification against the chosen live demo AI client (Claude Desktop / Antigravity / Gemini) remains scheduled for **C24** (`feat(curation): enforce untrusted metadata and approval gate`).
