# FocusList Second Brain

The FocusList Second Brain (`brain/`) is the team's shared knowledge repository, managed according to Software Requirements Specification requirements **SB-1 to SB-6**, **SE-5**, and the course AI-Assisted SDLC guidelines.

## Architecture and Layout

The vault is organized following Tiago Forte's PARA framework (Projects, Areas, Resources, Archive), augmented with a landing `inbox/`:

```
brain/
├── README.md                           # Vault overview, conventions, and operational rules
├── index.md                            # Central catalog of all notes, requirements, and tests
├── log.md                              # Append-only chronological changelog and AI session records
├── inbox/                              # Raw captures, initial drafts, and incoming material
├── projects/                           # Short-term active project deliverables and sprint tracking
├── areas/                              # Long-term responsibilities (e.g. platform, curation, discovery)
├── resources/                          # Reference materials, research notes, API specs, and benchmarks
└── archive/                            # Inactive, superseded, or completed historical items
```

## Note and Frontmatter Convention

All notes in the vault adhere to a strict YAML frontmatter standard to ensure automated traceability and consistency:

```yaml
---
title: "Descriptive Note Title"
author: "Teammate Name (e.g., Aangir Doshi)"
date: YYYY-MM-DD
type: research-note | decision-record | meeting-note | ai-session
status: draft | active | baselined | superseded
srs_ids:
  - FR-11.1
  - COM-1
sources:
  - "https://developers.google.com/youtube/v3/docs"
evidence:
  - "docs/testing/acceptance-cases.md#it-provider"
uncertainty:
  - "Documented technical ambiguities or pending team decisions"
---
```

### Frontmatter Fields

1. **`title`**: Concise, unambiguous name of the topic or decision.
2. **`author`**: Primary author responsible for the note content (`Aangir Doshi`, `Harshil Srivastav`, or `Ayush Patel`).
3. **`date`**: ISO date (`YYYY-MM-DD`) when the note was created or substantially updated.
4. **`type`**: Classification of document (`research-note`, `decision-record`, `meeting-note`, `ai-session`).
5. **`status`**: Note lifecycle state (`draft`, `active`, `baselined`, `superseded`).
6. **`srs_ids`**: List of exact SRS requirement identifiers satisfied or analyzed by this note (e.g. `FR-9`, `FR-10`, `FR-11`, `DB`, `SB-1`).
7. **`sources`**: Authoritative URLs, RFCs, official API documentation, or academic references supporting the note.
8. **`evidence`**: Relative paths and anchors to test specifications in `docs/testing/acceptance-cases.md`, test suites, or execution logs.
9. **`uncertainty`**: Explicit declaration of assumptions, risks, upstream ambiguities, or unresolved open questions (linking to Appendix C TBDs where applicable).

## Second Brain Governance Rules (SB-1 to SB-6)

- **SB-1 (PARA Structure)**: Maintain `inbox/`, `projects/`, `areas/`, `resources/`, and `archive/` alongside `index.md` and `log.md`.
- **SB-2 (Bidirectional Traceability)**: Every technical note must link to related requirements (`FocusList_SRS_Condensed.docx`), planning milestones (`FocusList_Commit_Plan.md`), and test cases (`docs/testing/acceptance-cases.md`).
- **SB-3 (Stage Reviews & ADRs)**: Major design choices must be captured in Architecture Decision Records (ADRs) that cite distilled notes in the vault.
- **SB-4 (PR-Based Evolution)**: All changes to `brain/` are made via pull requests reviewed by another teammate.
- **SB-5 (Author Contributions)**: Each teammate contributes at least four foundational research notes and records their own significant AI-assisted working sessions.
- **SB-6 (Strict Secrecy & Data Privacy)**: **NEVER** store real OAuth client secrets, refresh tokens, access tokens, personal identifiers, or unredacted YouTube account data in the vault. Use synthetic IDs and redacted placeholders only.
