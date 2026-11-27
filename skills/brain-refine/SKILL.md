---
name: brain-refine
description: Organise confirmed Second Brain notes into PARA folders, merge duplicates while preserving provenance, repair relative links, update index and log, and validate the vault.
---

# brain-refine (SK-4)

Maintain FocusList Second Brain (`brain/`) hygiene in compliance with **SB-1–SB-6** and **SK-4**.

## Linked Second Brain Evidence

- [FocusList Second Brain Conventions](../../brain/README.md)
- [FocusList Second Brain Master Index](../../brain/index.md)
- [Synthetic Fixture Provider, Fault Injection, and CI Isolation](../../brain/resources/fixture-provider-and-ci-isolation.md)

## Execution Protocol

Run `focuslist.skills.brain_refine.refine_vault(vault_root)` on a vault copy or working branch:

1. **Triage `inbox/`**: Move confirmed notes (`active`, `baselined`, `confirmed`, or `superseded`) into `projects/`, `areas/`, `resources/`, or `archive/`.
2. **Deduplicate with Provenance**: When a note matches an existing note title, merge `author`, `srs_ids`, `sources`, `evidence`, `uncertainty`, and body notes without discarding source attribution.
3. **Repair Links**: Rewrite stale or broken relative Markdown links across moved notes, `index.md`, and `log.md`.
4. **Update Index & Log**: Append newly filed entries to `brain/index.md` and log the run in `brain/log.md` without overwriting history.
5. **Validate Vault**: Verify PARA directories, required YAML frontmatter fields, valid relative links, and zero secret or token patterns.

## Deterministic Evaluation Cases (`SKE-SK4`)

1. **Routine Inbox-to-PARA Organisation (Positive)**: Moves a confirmed research note from `inbox/` to `resources/`, repairs its relative links, updates `index.md` and `log.md`, and passes `validate_vault`.
2. **Duplicate Note Deduplication (Boundary)**: Merges a duplicate `inbox/` note into an existing `resources/` note while preserving original and incoming `author`, `sources`, and `srs_ids` provenance.
3. **Broken Link Repair & Invalid Frontmatter Rejection (Negative)**: Repairs broken relative links for moved files and flags missing YAML frontmatter keys or unresolvable broken links via `validate_vault`.
