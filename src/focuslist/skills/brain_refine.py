"""Implementation of SK-4 brain-refine Second Brain vault hygiene and validation (C16)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from focuslist.platform.auth import redact_secrets
from focuslist.skills.validator import parse_yaml_frontmatter

PARA_FOLDERS: tuple[str, ...] = ("inbox", "projects", "areas", "resources", "archive")
REQUIRED_NOTE_KEYS: frozenset[str] = frozenset(
    {"title", "author", "date", "type", "status", "srs_ids", "sources", "evidence", "uncertainty"}
)
_MD_LINK_RE = re.compile(r"(\[[^\]]+\]\()([^)]+)(\))")


@dataclass(frozen=True, slots=True)
class BrainRefineReport:
    """Outcome summary of running brain-refine against a Second Brain vault."""

    moved_notes: list[tuple[str, str]] = field(default_factory=list)
    merged_duplicates: list[tuple[str, str]] = field(default_factory=list)
    repaired_links: int = 0
    validation_errors: list[str] = field(default_factory=list)
    valid: bool = True


def _format_frontmatter(fm: dict[str, object]) -> str:
    lines = ["---"]
    for key, val in fm.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f'  - "{item}"')
        else:
            s = str(val).replace('"', "'")
            if key in {"date", "type", "status"}:
                lines.append(f"{key}: {s}")
            else:
                lines.append(f'{key}: "{s}"')
    lines.append("---")
    return "\n".join(lines)


def _target_para_folder(fm: dict[str, object]) -> str:
    explicit = str(fm.get("para_folder") or "").strip().lower()
    if explicit in {"projects", "areas", "resources", "archive"}:
        return explicit
    status = str(fm.get("status") or "").strip().lower()
    if status == "superseded":
        return "archive"
    note_type = str(fm.get("type") or "").strip().lower()
    if note_type in {"project-note", "milestone-note"}:
        return "projects"
    if note_type in {"area-note", "responsibility"}:
        return "areas"
    return "resources"


def _rewrite_links_for_move(
    body: str,
    *,
    old_parent: Path,
    new_parent: Path,
    moved_map: dict[Path, Path],
) -> tuple[str, int]:
    """Update relative markdown links after moving a note or its link targets."""
    repairs = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal repairs
        prefix, target, suffix = match.group(1), match.group(2), match.group(3)
        if "://" in target or target.startswith(("#", "mailto:")):
            return match.group(0)
        path_part, hash_sep, anchor = target.partition("#")
        if not path_part:
            return match.group(0)
        old_resolved = (old_parent / path_part).resolve()
        new_target_resolved = moved_map.get(old_resolved, old_resolved)
        if not new_target_resolved.exists():
            # Attempt basename search across vault if target moved
            candidates = list(new_parent.parent.rglob(Path(path_part).name))
            if len(candidates) == 1:
                new_target_resolved = candidates[0].resolve()
        new_rel = Path(os.path.relpath(new_target_resolved, start=new_parent.resolve())).as_posix()
        rebuilt = f"{new_rel}{hash_sep}{anchor}" if hash_sep else new_rel
        if rebuilt != target:
            repairs += 1
        return f"{prefix}{rebuilt}{suffix}"

    updated = _MD_LINK_RE.sub(_replace, body)
    return updated, repairs


def _merge_note_records(
    existing_fm: dict[str, object],
    existing_body: str,
    incoming_fm: dict[str, object],
    incoming_body: str,
) -> tuple[dict[str, object], str]:
    """Merge duplicate notes while preserving all source attribution and provenance."""
    merged_fm = dict(existing_fm)

    # Preserve author attribution
    existing_author = str(existing_fm.get("author") or "")
    incoming_author = str(incoming_fm.get("author") or "")
    if incoming_author and incoming_author not in existing_author:
        merged_fm["author"] = f"{existing_author}; {incoming_author}".strip("; ")

    for list_key in ("srs_ids", "sources", "evidence", "uncertainty"):
        base_vals = [str(x) for x in (existing_fm.get(list_key) or []) if str(x).strip()]
        add_vals = [str(x) for x in (incoming_fm.get(list_key) or []) if str(x).strip()]
        merged_fm[list_key] = list(dict.fromkeys([*base_vals, *add_vals]))

    clean_inc_body = incoming_body.strip()
    if clean_inc_body and clean_inc_body not in existing_body:
        attribution = incoming_author or "Unknown Author"
        merged_body = (
            existing_body.rstrip()
            + f"\n\n### Merged Provenance Note ({attribution}, {incoming_fm.get('date', '')})\n\n"
            + clean_inc_body
            + "\n"
        )
    else:
        merged_body = existing_body
    return merged_fm, merged_body


def validate_vault(vault_root: Path) -> list[str]:
    """Validate PARA structure, note YAML frontmatter, relative links, and secret absence."""
    errors: list[str] = []
    for folder in PARA_FOLDERS:
        if not (vault_root / folder).is_dir():
            errors.append(f"Missing required PARA folder: {folder}/")
    for req_file in ("README.md", "index.md", "log.md"):
        if not (vault_root / req_file).is_file():
            errors.append(f"Missing required vault file: {req_file}")

    for folder in PARA_FOLDERS:
        folder_dir = vault_root / folder
        if not folder_dir.is_dir():
            continue
        for md_path in sorted(folder_dir.rglob("*.md")):
            text = md_path.read_text(encoding="utf-8")
            if redact_secrets(text) != text:
                errors.append(f"{md_path}: Potential secret or token pattern detected.")
            try:
                fm, body = parse_yaml_frontmatter(text)
            except ValueError as exc:
                errors.append(f"{md_path}: {exc}")
                continue
            missing = sorted(REQUIRED_NOTE_KEYS - set(fm.keys()))
            if missing:
                errors.append(f"{md_path}: Missing required frontmatter keys {missing}.")
            for _, target, _ in _MD_LINK_RE.findall(body):
                if "://" in target or target.startswith(("#", "mailto:")):
                    continue
                path_part = target.split("#", 1)[0].strip()
                if not path_part:
                    continue
                resolved = (md_path.parent / path_part).resolve()
                if not resolved.exists():
                    errors.append(f"{md_path}: Broken relative link '{target}'.")

    for top_file in ("index.md", "log.md"):
        tf_path = vault_root / top_file
        if tf_path.is_file():
            content = tf_path.read_text(encoding="utf-8")
            if redact_secrets(content) != content:
                errors.append(f"{tf_path}: Potential secret or token pattern detected.")
            for _, target, _ in _MD_LINK_RE.findall(content):
                if "://" in target or target.startswith(("#", "mailto:")):
                    continue
                path_part = target.split("#", 1)[0].strip()
                if path_part and not (tf_path.parent / path_part).resolve().exists():
                    errors.append(f"{tf_path}: Broken relative link '{target}'.")
    return errors


def refine_vault(
    vault_root: Path | str,
    *,
    date_str: str = "2026-11-27",
) -> BrainRefineReport:
    """Move confirmed inbox notes to PARA folders, merge duplicates, repair links, and validate."""
    root = Path(vault_root)
    inbox_dir = root / "inbox"
    moved_notes: list[tuple[str, str]] = []
    merged_duplicates: list[tuple[str, str]] = []
    repaired_links = 0
    moved_map: dict[Path, Path] = {}

    # Index existing PARA notes by normalized title for deduplication
    existing_by_title: dict[str, Path] = {}
    for para in ("projects", "areas", "resources", "archive"):
        pdir = root / para
        if not pdir.is_dir():
            continue
        for md_path in sorted(pdir.rglob("*.md")):
            try:
                fm, _ = parse_yaml_frontmatter(md_path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            title = str(fm.get("title") or "").strip().casefold()
            if title:
                existing_by_title[title] = md_path

    if inbox_dir.is_dir():
        for inbox_note in sorted(inbox_dir.glob("*.md")):
            raw = inbox_note.read_text(encoding="utf-8")
            try:
                fm, body = parse_yaml_frontmatter(raw)
            except ValueError:
                continue
            status = str(fm.get("status") or "").strip().lower()
            if status not in {"active", "baselined", "confirmed", "superseded"}:
                continue

            norm_title = str(fm.get("title") or "").strip().casefold()
            if norm_title and norm_title in existing_by_title:
                target_path = existing_by_title[norm_title]
                ex_fm, ex_body = parse_yaml_frontmatter(target_path.read_text(encoding="utf-8"))
                merged_fm, merged_body = _merge_note_records(ex_fm, ex_body, fm, body)
                merged_body, link_fixes = _rewrite_links_for_move(
                    merged_body,
                    old_parent=target_path.parent,
                    new_parent=target_path.parent,
                    moved_map=moved_map,
                )
                repaired_links += link_fixes
                target_path.write_text(
                    _format_frontmatter(merged_fm) + "\n\n" + merged_body.lstrip(),
                    encoding="utf-8",
                )
                moved_map[inbox_note.resolve()] = target_path.resolve()
                inbox_note.unlink()
                merged_duplicates.append(
                    (
                        inbox_note.relative_to(root).as_posix(),
                        target_path.relative_to(root).as_posix(),
                    )
                )
            else:
                para_folder = _target_para_folder(fm)
                dest_dir = root / para_folder
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / inbox_note.name
                rewritten_body, link_fixes = _rewrite_links_for_move(
                    body,
                    old_parent=inbox_note.parent,
                    new_parent=dest_path.parent,
                    moved_map=moved_map,
                )
                repaired_links += link_fixes
                dest_path.write_text(
                    _format_frontmatter(fm) + "\n\n" + rewritten_body.lstrip(),
                    encoding="utf-8",
                )
                moved_map[inbox_note.resolve()] = dest_path.resolve()
                inbox_note.unlink()
                if norm_title:
                    existing_by_title[norm_title] = dest_path
                moved_notes.append(
                    (
                        inbox_note.relative_to(root).as_posix(),
                        dest_path.relative_to(root).as_posix(),
                    )
                )

    # Repair any remaining broken or stale relative links across vault files
    all_md_files = [
        p
        for folder in PARA_FOLDERS
        if (root / folder).is_dir()
        for p in sorted((root / folder).rglob("*.md"))
    ]
    for tf in ("index.md", "log.md"):
        if (root / tf).is_file():
            all_md_files.append(root / tf)

    for md_file in all_md_files:
        original = md_file.read_text(encoding="utf-8")
        updated, fixes = _rewrite_links_for_move(
            original,
            old_parent=md_file.parent,
            new_parent=md_file.parent,
            moved_map=moved_map,
        )
        if fixes > 0 and updated != original:
            md_file.write_text(updated, encoding="utf-8")
            repaired_links += fixes

    # Update index.md and log.md preserving existing content
    index_path = root / "index.md"
    if index_path.is_file() and moved_notes:
        idx_text = index_path.read_text(encoding="utf-8")
        additions = []
        for _, dst in moved_notes:
            if dst not in idx_text:
                note_fm, _ = parse_yaml_frontmatter((root / dst).read_text(encoding="utf-8"))
                additions.append(
                    f"| **{note_fm.get('title', dst)}** | [`{dst}`]({dst}) | "
                    f"{note_fm.get('author', 'Unknown')} | {note_fm.get('date', date_str)} | "
                    f"{note_fm.get('type', 'research-note')} | {note_fm.get('status', 'active')} | "
                    f"{', '.join(str(x) for x in (note_fm.get('srs_ids') or []))} | — |"
                )
        if additions:
            index_path.write_text(idx_text.rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8")

    log_path = root / "log.md"
    if log_path.is_file() and (moved_notes or merged_duplicates or repaired_links):
        log_text = log_path.read_text(encoding="utf-8")
        summary_line = (
            f"\n### {date_str} · brain-refine Vault Hygiene\n"
            f"- Moved {len(moved_notes)} note(s), merged {len(merged_duplicates)} duplicate(s), "
            f"repaired {repaired_links} link(s).\n"
        )
        log_path.write_text(log_text.rstrip() + summary_line, encoding="utf-8")

    errors = validate_vault(root)
    return BrainRefineReport(
        moved_notes=moved_notes,
        merged_duplicates=merged_duplicates,
        repaired_links=repaired_links,
        validation_errors=errors,
        valid=not errors,
    )
