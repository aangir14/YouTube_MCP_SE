---
title: Agent Skill Format, Frontmatter Standards, and Upstream Tool Specification
author: Ayush Patel
date: 2026-11-24
type: research-note
status: active
srs_ids:
  - SK-0
  - SK-2
  - SE-6
  - TBD-10
sources:
  - "builtin/skills/agy-customizations/SKILL.md"
  - "FocusList_SRS_Condensed.docx"
  - "Project_1_YouTube_MCP.pdf"
evidence:
  - "docs/testing/acceptance-cases.md#sk-metadata"
  - "docs/testing/acceptance-cases.md#ske-sk2"
uncertainty:
  - "Upstream variation in maximum prompt token overhead when loading multiple complex skills simultaneously"
  - "Exact schema for exposing Agent Skills as MCP prompts versus MCP resources across diverse client hosts"
---

# Agent Skill Format, Frontmatter Standards, and Upstream Tool Specification

## 1. Context and Objective (TBD-10 Resolution)

Per **SK-0, SK-2, SE-6**, and condensed SRS Appendix C **TBD-10**, FocusList packages reusable agent workflows as specialized **Agent Skills**. In an MCP environment, Agent Skills serve as guided operational playbooks that instruct conversational AI clients (such as Gemini CLI, Antigravity, Claude Code, or Cursor) on how to coordinate multi-tool operations, respect human consent boundaries, and handle errors.

TBD-10 previously left open the exact upstream skill naming, description, and format limits. This research note investigates the authoritative upstream specification defined by Google Antigravity and the broader Agent Skill ecosystem, establishes exact frontmatter and directory conventions for FocusList, and closes the uncertainty surrounding TBD-10.

```
+--------------------------------------------------------------------------+
|                        FocusList Skills Package                          |
|                       (Root `skills/` Directory)                         |
+--------------------------------------------------------------------------+
                                     |
    +--------------------------------+--------------------------------+
    |                                |                                |
    v                                v                                v
+-----------------------+  +-----------------------+  +-----------------------+
|  skills/local-check/  |  |skills/video-to-play-  |  | skills/playlist-audit/|
|  SKILL.md (SK-1)      |  |list/ SKILL.md (SK-2)  |  | SKILL.md (SK-6)       |
+-----------------------+  +-----------------------+  +-----------------------+
    |                                |                                |
    +--------------------------------+--------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                         Canonical SKILL.md Anatomy                       |
|  1. Strict YAML Frontmatter: `name` (<=64 chars), `description` (<=1024) |
|  2. Distilled Research Note Citation (Second Brain link)                 |
|  3. Preconditions & MCP Tool Prerequisite Checklist                      |
|  4. Step-by-Step Interactive Protocol & Explicit Confirmation Gate      |
|  5. Minimum 3 Deterministic Evaluations (Positive, Negative, Adversarial)|
+--------------------------------------------------------------------------+
```

---

## 2. Canonical Skill Directory Layout (SK-0, SE-6)

Every FocusList skill is packaged in an isolated directory under `skills/<skill-name>/`:

```text
skills/
└── video-to-playlist/
    ├── SKILL.md                  # Authoritative skill definition with YAML frontmatter
    ├── scripts/                  # (Optional) Helper automation or validation scripts
    ├── examples/                 # Sample conversational dialogues and input prompts
    ├── resources/                # Offline fixtures or static evaluation templates
    └── references/               # Deep-dive documentation or linked research notes
```

### Required Files and Rules:
1. `SKILL.md` is mandatory. The file name must be uppercase `SKILL.md`.
2. The enclosing directory name must match the skill's `name` frontmatter property exactly.
3. Every skill must link to at least one distilled research note in `brain/resources/`.

---

## 3. Upstream YAML Frontmatter Schema (TBD-10 Resolution)

Inspection of the Google Antigravity Customization System specification reveals the precise metadata schema parsed by AI clients during skill discovery:

```yaml
---
name: video-to-playlist
description: Guided 5-step workflow to summarize a YouTube seed video, discover similar candidates, propose a constrained playlist, request explicit learner approval, and analyze the created playlist.
---
```

### Frontmatter Validation Rules:
| Property | Type | Specification Limit | FocusList Convention |
| :--- | :--- | :--- | :--- |
| `name` | `string` | 1–64 characters; lowercase alphanumeric and hyphens `[a-z0-9-]` only; no spaces or symbols. | Must match directory name (e.g. `video-to-playlist`). |
| `description` | `string` | 1–1024 characters; concise, third-person present tense; describes when and how the skill is activated. | Clear trigger conditions and capability summary. |

### Upstream Verification & Boundaries:
- **No Extraneous Root Keys**: Upstream validators reject unexpected top-level frontmatter keys (e.g. `author:`, `version:`, `tools:`) if not defined in the skill schema. Metadata such as author, links, and requirements belong in the Markdown body or Second Brain note.
- **Description Token Budget**: Descriptions longer than 1024 characters degrade AI tool discovery and context routing efficiency.

---

## 4. FocusList 6-Skill Inventory & Responsibilities

| Skill Identifier | Directory Name | Scope & Responsibilities | Second Brain Reference |
| :--- | :--- | :--- | :--- |
| **SK-1** | `local-check` | Automated local health check: builds, runs offline tests, verifies MCP stdio, outputs PASS/FAIL. | `resources/fixture-provider-and-ci-isolation.md` |
| **SK-2** | `video-to-playlist` | The primary 5-step course workflow: seed summary $\rightarrow$ similar search $\rightarrow$ proposal $\rightarrow$ confirmation $\rightarrow$ analysis. | `resources/confirmation-gate-and-action-lifecycle.md` |
| **SK-3** | `brain-ingest` | Automated Second Brain ingestion: captures source, author, type, requirement links, updates log. | `brain/README.md` |
| **SK-4** | `brain-refine` | Knowledge vault hygiene: organizes notes into PARA categories, repairs broken relative links, updates index. | `brain/index.md` |
| **SK-5** | `brain-query` | Query and synthesis: extracts requirements, cites notes, drafts ADR material for team review. | `brain/index.md` |
| **SK-6** | `playlist-audit` | Quality audit: runs read-only analysis on existing playlists, detects stale/duplicate/unavailable items. | `resources/ranking-evaluation-metrics.md` |

---

## 5. Evaluation & Testing Requirements (SK-0, TQ-7, TQ-8)

Per **SK-0 and TQ-7**, every skill package must deliver at least **three deterministic evaluation cases** before Stage 4 release:
1. **Positive Baseline Case**: Standard happy path with valid inputs and normal user confirmation.
2. **Boundary / Edge Case**: Extreme but valid inputs (e.g. exactly 50 items, maximum duration tolerance, single-video study sessions).
3. **Negative / Adversarial Case**: Malicious or invalid inputs designed to test error recovery and safety:
   - For `video-to-playlist`: Prompt injection in video description attempting to bypass human approval (`CW-01`), learner decline (`CW-02`), and conflicting duration bounds (`CW-03`).

---

## 6. Traceability and Verification Mappings

| Requirement | Contract Invariant | Acceptance Test Link |
| :--- | :--- | :--- |
| **SK-0** | Valid YAML frontmatter and folder conventions | [`SK-METADATA`](../docs/testing/acceptance-cases.md#sk-metadata) |
| **SK-2** | 5-step video-to-playlist workflow execution | [`SKE-SK2`](../docs/testing/acceptance-cases.md#ske-sk2), [`ST-FR5`](../docs/testing/acceptance-cases.md#st-fr5) |
| **TQ-7** | 3 deterministic evaluations per skill package | [`SK-METADATA`](../docs/testing/acceptance-cases.md#sk-metadata), [`QA-RELEASE`](../docs/testing/acceptance-cases.md#qa-release) |
| **TBD-10**| Skill naming and frontmatter specification | Closed in this note; validated in CI via [`SK-METADATA`](../docs/testing/acceptance-cases.md#sk-metadata) |
