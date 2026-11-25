# FocusList: YouTube Video Intelligence MCP Server

FocusList is an intelligent local Model Context Protocol (MCP) server for YouTube discovery, account analytics, and constrained playlist curation. A learner uses an MCP-capable AI client to formulate learning goals or study budgets. FocusList discovers related videos through official YouTube Data API v3 metadata, explains rankings, enforces strict quota budgets, and requires explicit human confirmation before executing any account writes.

- [Software Requirements Specification (Condensed DOCX)](FocusList_SRS_Condensed.docx)
- [Course Project Statement (PDF)](Project_1_YouTube_MCP.pdf)
- [Implementation and Commit Plan](FocusList_Commit_Plan.md)
- [Repository Instructions & Boundaries](AGENTS.md)
- [Service Architecture & Interface Contracts (ADR-001)](docs/adr/ADR-001-service-architecture-and-contracts.md)
- [Second Brain Knowledge Base](brain/index.md)

---

## Quick Start and Setup

FocusList requires **Python 3.11 or later** and runs cleanly on Windows, macOS, and Linux (**NFR-PORT**).

### 1. Installation
Clone the repository and install FocusList in editable mode with development dependencies:

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Install package in editable mode with test and lint tooling
pip install -e ".[dev]"
```

### 2. System Diagnostic Check (`doctor`)
Verify that your local environment satisfies all runtime, SQLite, and provider dependencies:

```bash
focuslist doctor
```

Output:
```text
FocusList Diagnostic Report (v0.1.0)
---------------------------------------------
Python Runtime: 3.13.7 [OK] (Requires >=3.11)
Active Provider: fixture
Fixture Directory: tests/fixtures [OK]
SQLite DB Path: focuslist.db
OAuth Credentials: Not configured (Fixture mode active)
---------------------------------------------
System Status: HEALTHY. Ready for MCP client connection.
```

### 3. Inspect Daily Quota Status
FocusList tracks quota locally to prevent accidental API overspend:

```bash
focuslist quota
```

### 4. Run the Automated Test Suite & Linter
FocusList enforces offline, deterministic testing using synthetic fixtures (**FR-11.3**, **TQ-5**):

```bash
# Run unit, integration, and system tests (33 tests)
python -m pytest -v

# Run fast code linting and formatting
python -m ruff check .
```

---

## Starting the MCP Server

The MCP client (e.g. Claude Desktop, Antigravity, or MCP Inspector) launches FocusList as a subprocess using standard input/output (`stdio`) per **COM-1**:

```bash
# Start MCP server in safe offline fixture mode (credential-free default)
focuslist serve

# Or explicitly specify provider mode
focuslist serve --provider fixture
```

> **Protocol Cleanliness (COM-1)**: Standard output (`sys.stdout`) is strictly reserved for JSON-RPC 2.0 protocol frames. All server banners, diagnostic logs, and error traces write exclusively to `sys.stderr`.

### Example MCP Client Configuration
Add FocusList to your client's `mcpServers` configuration:

```json
{
  "mcpServers": {
    "focuslist": {
      "command": "focuslist",
      "args": ["serve"],
      "env": {
        "FOCUSLIST_PROVIDER": "fixture"
      }
    }
  }
}
```

---

## Architectural Highlights

- **FastMCP Framework**: Built on the official Model Context Protocol Python SDK, auto-generating JSON Schema definitions for all 13 tools, resources, and prompt templates.
- **Platform Boundary Isolation (`FR-11.2`)**: All Google API client imports (`googleapiclient`, `google.auth`) are strictly confined to `src/focuslist/platform/`. Feature modules (discovery, curation, analytics) interact solely with typed domain records (`VideoRecord`, `ChannelRecord`, `ProposalRecord`).
- **Deterministic Clock Seam (`Clock`)**: An injectable clock seam (`SystemClock` / `FakeClock`) guarantees reproducible time-dependent testing for proposal expiration, cache TTLs, and quota resets.
- **Untrusted Metadata Handling**: All video titles, descriptions, and channel text are treated as untrusted data, sanitized of control characters, and truncated to 500 characters (**SEC-APPROVAL**).
- **Human Confirmation Gate (`FR-7`)**: Account writes (playlist creation, item insertion, deletion) require explicit learner confirmation of an immutable, HMAC-SHA-256 signed proposal before any YouTube API call is dispatched.

---

## Legal and Non-Endorsement Notice

FocusList is developed as part of an academic term project for Software Engineering. FocusList uses official YouTube Data API v3 endpoints in compliance with the [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies). This software is not affiliated with, sponsored by, or endorsed by Google LLC or YouTube (**L-1**, **BR-11**).
