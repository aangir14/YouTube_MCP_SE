"""Skill frontmatter, structure, and Second Brain citation validator (SK-0, TBD-10)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

_SKILL_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_ALLOWED_FRONTMATTER_KEYS = frozenset({"name", "description"})

ALL_EXPECTED_SKILLS: tuple[str, ...] = (
    "local-check",
    "video-to-playlist",
    "brain-ingest",
    "brain-refine",
    "brain-query",
    "playlist-audit",
)


@dataclass(frozen=True, slots=True)
class SkillValidationResult:
    """Validation outcome for a single skill directory."""

    skill_name: str
    skill_dir: Path
    valid: bool
    errors: list[str] = field(default_factory=list)
    linked_notes: list[str] = field(default_factory=list)


def parse_yaml_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse minimal YAML frontmatter (scalars and simple lists) using stdlib only."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Missing opening YAML frontmatter delimiter '---'.")

    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("Missing closing YAML frontmatter delimiter '---'.")

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :])
    data: dict[str, object] = {}
    current_list_key: str | None = None

    for raw_line in fm_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_list_key is None:
                raise ValueError(f"Unexpected YAML list item without key: {stripped}")
            item_val = stripped[2:].strip().strip("\"'")
            existing = data.get(current_list_key)
            if isinstance(existing, list):
                existing.append(item_val)
            continue

        if ":" not in raw_line:
            raise ValueError(f"Malformed YAML frontmatter line: {raw_line}")
        key, _, raw_val = raw_line.partition(":")
        key = key.strip()
        val = raw_val.strip()
        if not val:
            data[key] = []
            current_list_key = key
        else:
            current_list_key = None
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            data[key] = val

    return data, body


def validate_skill_dir(skill_dir: Path, *, repo_root: Path | None = None) -> SkillValidationResult:
    """Validate one skill package directory against SK-0 and TBD-10 rules."""
    errors: list[str] = []
    linked_notes: list[str] = []
    skill_name = skill_dir.name
    root = repo_root or skill_dir.parent.parent

    if not skill_dir.is_dir():
        return SkillValidationResult(
            skill_name=skill_name,
            skill_dir=skill_dir,
            valid=False,
            errors=[f"{skill_dir}: Skill path is not a directory."],
        )

    skill_md = skill_dir / "SKILL.md"
    exact_names = [p.name for p in skill_dir.iterdir()]
    if "SKILL.md" not in exact_names or not skill_md.is_file():
        errors.append(f"{skill_dir}: Missing required uppercase 'SKILL.md'.")
        return SkillValidationResult(
            skill_name=skill_name,
            skill_dir=skill_dir,
            valid=False,
            errors=errors,
        )

    content = skill_md.read_text(encoding="utf-8")
    try:
        fm, body = parse_yaml_frontmatter(content)
    except ValueError as exc:
        errors.append(f"{skill_md}: {exc}")
        return SkillValidationResult(
            skill_name=skill_name,
            skill_dir=skill_dir,
            valid=False,
            errors=errors,
        )

    extra_keys = set(fm.keys()) - _ALLOWED_FRONTMATTER_KEYS
    if extra_keys:
        errors.append(
            f"{skill_md}: Unexpected root frontmatter keys {sorted(extra_keys)} (TBD-10 forbids extras)."
        )

    name_val = fm.get("name")
    if not isinstance(name_val, str) or not _SKILL_NAME_RE.fullmatch(name_val):
        errors.append(
            f"{skill_md}: 'name' must be 1–64 lowercase alphanumeric/hyphen characters."
        )
    elif name_val != skill_name:
        errors.append(
            f"{skill_md}: 'name' ('{name_val}') must match directory name ('{skill_name}')."
        )

    desc_val = fm.get("description")
    if not isinstance(desc_val, str) or not (1 <= len(desc_val.strip()) <= 1024):
        errors.append(f"{skill_md}: 'description' must be 1–1024 non-empty characters.")

    for target in _MARKDOWN_LINK_RE.findall(body):
        path_only = target.split("#", 1)[0].strip()
        if not path_only or "://" in path_only or path_only.startswith("mailto:"):
            continue
        resolved = (skill_md.parent / path_only).resolve()
        if not resolved.exists():
            errors.append(f"{skill_md}: Broken relative link '{target}'.")
            continue
        try:
            rel = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        rel_posix = rel.as_posix()
        if rel_posix.startswith("brain/") and rel_posix.endswith(".md"):
            linked_notes.append(rel_posix)

    if not linked_notes:
        errors.append(
            f"{skill_md}: Must link to at least one existing distilled note under brain/."
        )

    return SkillValidationResult(
        skill_name=skill_name,
        skill_dir=skill_dir,
        valid=not errors,
        errors=errors,
        linked_notes=linked_notes,
    )


class SkillInventory(TypedDict):
    valid: bool
    results: list[SkillValidationResult]
    present_skills: list[str]
    pending_skills: list[str]


def validate_all_skills(
    skills_root: Path,
    *,
    repo_root: Path | None = None,
    require_all_six: bool = False,
) -> SkillInventory:
    """Validate all packaged skills currently present and report pending inventory."""
    root = repo_root or skills_root.parent
    present_dirs = (
        sorted(p for p in skills_root.iterdir() if p.is_dir() and not p.name.startswith("."))
        if skills_root.exists()
        else []
    )
    results = [validate_skill_dir(d, repo_root=root) for d in present_dirs]
    present_names = {r.skill_name for r in results}
    pending = [name for name in ALL_EXPECTED_SKILLS if name not in present_names]
    all_valid = all(r.valid for r in results)
    if require_all_six and pending:
        all_valid = False
    return {
        "valid": all_valid,
        "results": results,
        "present_skills": sorted(present_names),
        "pending_skills": pending,
    }
