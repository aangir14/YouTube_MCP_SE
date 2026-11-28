"""Offline CI compliance checks: import boundaries, secret scan, skills, and MCP reference (C16)."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from focuslist.config import Settings
from focuslist.skills.validator import SkillInventory, validate_all_skills

_REPO_SECRET_PATTERNS = (
    re.compile(r"ya29\.[A-Za-z0-9\-_]{8,}"),
    re.compile(r"1//[A-Za-z0-9\-_]{8,}"),
    re.compile(r"GOCSPX-[A-Za-z0-9\-_]{3,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]{12,}=*", re.IGNORECASE),
    re.compile(
        r"[\"']?(?:access_token|refresh_token|client_secret|id_token)[\"']?"
        r"\s*[=:]\s*[\"'](?!<|\[REDACTED\])([A-Za-z0-9\-._~+/]{12,})[\"']",
        re.IGNORECASE,
    ),
)

_FORBIDDEN_GOOGLE_ROOTS = frozenset(
    {"google", "googleapiclient", "google_auth_httplib2", "httplib2"}
)

_SCAN_EXTENSIONS = frozenset({".py", ".md", ".json", ".yml", ".yaml", ".toml", ".example"})
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache"})


@dataclass(frozen=True, slots=True)
class ComplianceReport:
    """Result of running offline C16 CI compliance checks."""

    passed: bool
    skill_validation: SkillInventory
    import_violations: list[str] = field(default_factory=list)
    secret_findings: list[str] = field(default_factory=list)
    reference_in_sync: bool = True
    pending_checks: list[str] = field(default_factory=list)


def check_import_boundaries(src_root: Path) -> list[str]:
    """Ensure Google API client imports remain strictly confined to src/focuslist/platform/."""
    violations: list[str] = []
    package_root = src_root / "focuslist"
    platform_root = (package_root / "platform").resolve()
    if not package_root.is_dir():
        return [f"Source package directory not found: {package_root}"]

    for py_file in sorted(package_root.rglob("*.py")):
        resolved = py_file.resolve()
        if resolved == platform_root or platform_root in resolved.parents:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".", 1)[0]
                    if root_mod in _FORBIDDEN_GOOGLE_ROOTS:
                        violations.append(
                            f"{py_file.relative_to(src_root).as_posix()}:{node.lineno}: "
                            f"Forbidden import '{alias.name}' outside platform/"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_mod = node.module.split(".", 1)[0]
                if root_mod in _FORBIDDEN_GOOGLE_ROOTS:
                    violations.append(
                        f"{py_file.relative_to(src_root).as_posix()}:{node.lineno}: "
                        f"Forbidden import from '{node.module}' outside platform/"
                    )
    return violations


def scan_repository_secrets(
    repo_root: Path,
    *,
    extra_patterns: tuple[re.Pattern[str], ...] = (),
) -> list[str]:
    """Scan repository files for credential canaries or unredacted token patterns."""
    patterns = (*_REPO_SECRET_PATTERNS, *extra_patterns)
    findings: list[str] = []

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in _SCAN_EXTENSIONS and path.name != ".env.example":
            continue
        rel = path.relative_to(repo_root).as_posix()
        # Exclude unit test files intentionally constructing synthetic redaction inputs
        if rel.startswith("tests/") and "canary" not in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "canary-ignore" in line:
                continue
            for pat in patterns:
                if pat.search(line):
                    findings.append(f"{rel}:{lineno}: matched pattern '{pat.pattern}'")
                    break
    return findings


async def _collect_server_catalog(temp_dir: Path) -> dict[str, Any]:
    from focuslist.server import create_server

    cfg = Settings(
        provider="fixture",
        db_path=temp_dir / "ref_gen.db",
        auth_store_dir=temp_dir / "ref_auth",
    )
    server = create_server(settings=cfg)
    tools = await server.list_tools()
    resources = await server.list_resources()
    prompts = await server.list_prompts()
    return {
        "tools": [
            {
                "name": t.name,
                "description": (t.description or "").strip(),
                "inputSchema": t.inputSchema,
            }
            for t in sorted(tools, key=lambda x: x.name)
        ],
        "resources": [
            {
                "uri": str(r.uri),
                "name": r.name,
                "description": (r.description or "").strip(),
            }
            for r in sorted(resources, key=lambda x: str(x.uri))
        ],
        "prompts": [
            {
                "name": p.name,
                "description": (p.description or "").strip(),
            }
            for p in sorted(prompts, key=lambda x: x.name)
        ],
    }


def generate_mcp_reference_markdown(temp_dir: Path) -> str:
    """Generate schema-derived Markdown MCP reference from FastMCP registrations."""
    catalog = asyncio.run(_collect_server_catalog(temp_dir))
    lines = [
        "# FocusList MCP Interface Reference",
        "",
        "Auto-generated from `focuslist.server.create_server()` FastMCP tool, resource, and prompt schemas.",
        "",
        "## Registered Tools",
        "",
        "| Tool | Description | Required Inputs |",
        "| :--- | :--- | :--- |",
    ]
    for tool in catalog["tools"]:
        schema = tool["inputSchema"] or {}
        required = ", ".join(schema.get("required") or []) or "*(none)*"
        desc = tool["description"].replace("\n", " ")
        lines.append(f"| `{tool['name']}` | {desc} | `{required}` |")

    lines.extend(
        [
            "",
            "## Registered Resources",
            "",
            "| URI | Name | Description |",
            "| :--- | :--- | :--- |",
        ]
    )
    for res in catalog["resources"]:
        lines.append(f"| `{res['uri']}` | `{res['name']}` | {res['description']} |")

    lines.extend(
        [
            "",
            "## Registered Prompts",
            "",
            "| Prompt | Description |",
            "| :--- | :--- |",
        ]
    )
    for pr in catalog["prompts"]:
        lines.append(f"| `{pr['name']}` | {pr['description']} |")

    lines.extend(
        [
            "",
            "## Tool Input Schemas (JSON)",
            "",
        ]
    )
    for tool in catalog["tools"]:
        lines.append(f"### `{tool['name']}`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(tool["inputSchema"], indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def run_fixture_gate(repo_root: Path, temp_dir: Path) -> ComplianceReport:
    """Execute C16 opening PR CI compliance checks in enforced fixture mode."""
    provider_env = os.environ.get("FOCUSLIST_PROVIDER", "fixture")
    if provider_env != "fixture":
        raise RuntimeError(f"PR CI must enforce FOCUSLIST_PROVIDER=fixture (got '{provider_env}').")

    import_violations = check_import_boundaries(repo_root / "src")
    secret_findings = scan_repository_secrets(repo_root)
    skill_summary = validate_all_skills(
        repo_root / "skills", repo_root=repo_root, require_all_six=False
    )

    ref_path = repo_root / "docs" / "reference" / "mcp-reference.md"
    expected_ref = generate_mcp_reference_markdown(temp_dir)
    reference_in_sync = ref_path.is_file() and ref_path.read_text(encoding="utf-8") == expected_ref

    pending = [
        *[f"skill:{name}:pending_c20_c21" for name in skill_summary["pending_skills"]],
        "coverage_80_90_enforcement:pending_c22",
        "scheduled_live_smoke_workflow:pending_c22",
    ]

    passed = (
        not import_violations
        and not secret_findings
        and bool(skill_summary["valid"])
        and reference_in_sync
    )
    return ComplianceReport(
        passed=passed,
        import_violations=import_violations,
        secret_findings=secret_findings,
        skill_validation=skill_summary,
        reference_in_sync=reference_in_sync,
        pending_checks=pending,
    )


def main() -> int:
    """CLI entrypoint for offline PR fixture gate and SK-1 local-check verification."""
    import sys
    import tempfile

    from focuslist.skills.local_check import run_local_check

    repo_root = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="focuslist_gate_") as tmp_dir:
        rep = run_fixture_gate(repo_root, Path(tmp_dir))
    print("Skills present:", rep.skill_validation.get("present_skills"))
    print("Pending checks:", rep.pending_checks)
    if not rep.passed:
        print("Import violations:", rep.import_violations, file=sys.stderr)
        print("Secret findings:", rep.secret_findings, file=sys.stderr)
        print("Reference in sync:", rep.reference_in_sync, file=sys.stderr)
        return 1

    lc = run_local_check(repo_root)
    print(lc.format_summary())
    if lc.overall_status != "PASS" or lc.total_duration_seconds > 120.0 or not lc.subprocess_terminated:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
