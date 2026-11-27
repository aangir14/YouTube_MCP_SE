"""Unit tests for C16 opening fixture-only PR CI gate and compliance checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from focuslist.platform.compliance import (
    check_import_boundaries,
    run_fixture_gate,
    scan_repository_secrets,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_import_boundary_passes_repo_and_catches_google_leak(tmp_path: Path) -> None:
    """Google API imports are strictly confined to src/focuslist/platform/."""
    assert check_import_boundaries(REPO_ROOT / "src") == []

    bad_src = tmp_path / "src"
    (bad_src / "focuslist" / "discovery").mkdir(parents=True)
    (bad_src / "focuslist" / "platform").mkdir(parents=True)
    (bad_src / "focuslist" / "discovery" / "bad.py").write_text(
        "import googleapiclient.discovery\n", encoding="utf-8"
    )
    violations = check_import_boundaries(bad_src)
    assert len(violations) == 1
    assert "googleapiclient.discovery" in violations[0]


def test_secret_scanner_passes_repo_and_catches_canaries(tmp_path: Path) -> None:
    """Repository contains zero secrets/tokens; scanner catches synthetic canaries."""
    assert scan_repository_secrets(REPO_ROOT) == []

    canary_dir = tmp_path / "repo"
    canary_dir.mkdir()
    (canary_dir / "leak.md").write_text(
        "token = ya29." + "canarySyntheticToken999\n",
        encoding="utf-8",
    )
    findings = scan_repository_secrets(canary_dir)
    assert len(findings) == 1
    assert "leak.md:1" in findings[0]


def test_fixture_gate_passes_and_rejects_live_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening PR fixture gate enforces fixture mode, skills, secrets, imports, and MCP ref."""
    monkeypatch.setenv("FOCUSLIST_PROVIDER", "fixture")
    report = run_fixture_gate(REPO_ROOT, tmp_path)
    assert report.import_violations == []
    assert report.secret_findings == []
    assert report.skill_validation["valid"] is True
    assert report.reference_in_sync is True
    assert report.passed is True

    monkeypatch.setenv("FOCUSLIST_PROVIDER", "live")
    with pytest.raises(RuntimeError, match="FOCUSLIST_PROVIDER=fixture"):
        run_fixture_gate(REPO_ROOT, tmp_path)
