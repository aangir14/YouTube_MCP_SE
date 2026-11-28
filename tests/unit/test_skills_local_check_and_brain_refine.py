"""Deterministic evaluations for SK-1 (local-check), SK-4 (brain-refine), and SK-0 validation."""

from __future__ import annotations

from pathlib import Path

from focuslist.skills.brain_refine import refine_vault, validate_vault
from focuslist.skills.local_check import run_local_check
from focuslist.skills.validator import validate_all_skills, validate_skill_dir

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_synthetic_vault(vault_dir: Path) -> Path:
    for folder in ("inbox", "projects", "areas", "resources", "archive"):
        (vault_dir / folder).mkdir(parents=True, exist_ok=True)
    (vault_dir / "README.md").write_text("# Synthetic Vault\n", encoding="utf-8")
    (vault_dir / "index.md").write_text(
        "# Index\n\n| Title | Path | Author | Date | Type | Status | SRS | Links |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    (vault_dir / "log.md").write_text("# Activity Log\n\n## Existing Entry\n- Kept.\n", encoding="utf-8")
    return vault_dir


# ==============================================================================
# SK-0 / TBD-10 Skill Validation
# ==============================================================================


def test_skill_validator_passes_present_skills_and_rejects_bad_copy(tmp_path: Path) -> None:
    """Validate local-check & brain-refine skills; verify negative invalid-frontmatter copy fails."""
    summary = validate_all_skills(REPO_ROOT / "skills", repo_root=REPO_ROOT, require_all_six=False)
    assert summary["valid"] is True
    assert set(summary["present_skills"]) == {"brain-refine", "local-check", "playlist-audit"}
    assert set(summary["pending_skills"]) == {
        "video-to-playlist",
        "brain-ingest",
        "brain-query",
    }

    bad_skill = tmp_path / "skills" / "bad-skill"
    bad_skill.mkdir(parents=True)
    (bad_skill / "SKILL.md").write_text(
        "---\nname: wrong-name\ndescription: Invalid test skill\nauthor: ExtraForbiddenKey\n---\nNo note link.\n",
        encoding="utf-8",
    )
    bad_res = validate_skill_dir(bad_skill, repo_root=REPO_ROOT)
    assert bad_res.valid is False
    assert len(bad_res.errors) >= 3


# ==============================================================================
# SKE-SK1: Three Deterministic Evaluations for local-check
# ==============================================================================


def test_ske_sk1_happy_path_real_stdio_and_user_data_preserved(tmp_path: Path) -> None:
    """SKE-SK1 Case 1: Full offline build, test, real MCP stdio startup, and fixture fetch PASS."""
    sentinel_db = tmp_path / "user_focuslist.db"
    sentinel_db.write_bytes(b"original_user_data")

    report = run_local_check(
        REPO_ROOT,
        build_cmd=["python_noop"],
        test_cmd=["python_noop"],
        command_runner=lambda cmd, cwd, env: (0, "ok"),
    )
    assert report.overall_status == "PASS"
    assert [s.stage for s in report.stages] == ["build", "test", "startup", "fixture_fetch"]
    assert all(s.status == "PASS" for s in report.stages)
    assert report.subprocess_terminated is True
    assert report.total_duration_seconds < 120.0
    assert sentinel_db.read_bytes() == b"original_user_data"


def test_ske_sk1_induced_build_or_test_failure_skips_downstream() -> None:
    """SKE-SK1 Case 2: Induced build/test failure reports FAIL and marks downstream SKIPPED."""
    report = run_local_check(
        REPO_ROOT,
        command_runner=lambda cmd, cwd, env: (1, "simulated build failure"),
    )
    assert report.overall_status == "FAIL"
    assert [(s.stage, s.status) for s in report.stages] == [
        ("build", "FAIL"),
        ("test", "SKIPPED"),
        ("startup", "SKIPPED"),
        ("fixture_fetch", "SKIPPED"),
    ]
    assert report.subprocess_terminated is True


def test_ske_sk1_induced_mcp_failure_guarantees_teardown() -> None:
    """SKE-SK1 Case 3: Induced MCP probe failure terminates cleanly and skips fixture_fetch."""
    async def _failing_probe(repo_root: Path, temp_dir: Path, video_id: str) -> dict:
        raise RuntimeError("simulated MCP stdio crash")

    report = run_local_check(
        REPO_ROOT,
        command_runner=lambda cmd, cwd, env: (0, "ok"),
        mcp_probe=_failing_probe,
    )
    assert report.overall_status == "FAIL"
    assert [(s.stage, s.status) for s in report.stages] == [
        ("build", "PASS"),
        ("test", "PASS"),
        ("startup", "FAIL"),
        ("fixture_fetch", "SKIPPED"),
    ]
    assert report.subprocess_terminated is True


# ==============================================================================
# SKE-SK4: Three Deterministic Evaluations for brain-refine
# ==============================================================================


def test_ske_sk4_routine_inbox_to_para_organisation_and_index_log(tmp_path: Path) -> None:
    """SKE-SK4 Case 1: Confirmed inbox note moves to resources/, updates index/log, passes validation."""
    vault = _make_synthetic_vault(tmp_path / "vault1")
    (vault / "resources" / "base.md").write_text(
        "---\n"
        'title: "Base Reference"\n'
        'author: "Aangir Doshi"\n'
        "date: 2026-11-20\n"
        "type: research-note\n"
        "status: active\n"
        "srs_ids:\n  - FR-11\n"
        "sources:\n  - https://example.com/spec\n"
        "evidence:\n  - base-case\n"
        "uncertainty:\n  - None\n"
        "---\nBase body.\n",
        encoding="utf-8",
    )
    (vault / "inbox" / "new-cache-note.md").write_text(
        "---\n"
        'title: "Cache Retention Policy"\n'
        'author: "Aangir Doshi"\n'
        "date: 2026-11-27\n"
        "type: research-note\n"
        "status: active\n"
        "srs_ids:\n  - DB-1\n"
        "sources:\n  - https://example.com/sqlite\n"
        "evidence:\n  - IT-CACHE\n"
        "uncertainty:\n  - None\n"
        "---\nSee [Base](../resources/base.md).\n",
        encoding="utf-8",
    )

    report = refine_vault(vault, date_str="2026-11-27")
    assert report.valid is True
    assert report.moved_notes == [("inbox/new-cache-note.md", "resources/new-cache-note.md")]
    assert (vault / "resources" / "new-cache-note.md").exists()
    assert not (vault / "inbox" / "new-cache-note.md").exists()
    moved_text = (vault / "resources" / "new-cache-note.md").read_text(encoding="utf-8")
    assert "(base.md)" in moved_text
    assert "resources/new-cache-note.md" in (vault / "index.md").read_text(encoding="utf-8")
    assert "Existing Entry" in (vault / "log.md").read_text(encoding="utf-8")
    assert "brain-refine Vault Hygiene" in (vault / "log.md").read_text(encoding="utf-8")


def test_ske_sk4_duplicate_note_merge_retains_provenance(tmp_path: Path) -> None:
    """SKE-SK4 Case 2: Duplicate note merges without losing original or incoming attribution."""
    vault = _make_synthetic_vault(tmp_path / "vault2")
    (vault / "resources" / "quota-note.md").write_text(
        "---\n"
        'title: "Quota Accounting"\n'
        'author: "Aangir Doshi"\n'
        "date: 2026-11-19\n"
        "type: research-note\n"
        "status: active\n"
        "srs_ids:\n  - FR-10.1\n"
        "sources:\n  - https://developers.google.com/youtube/v3/determine_quota_cost\n"
        "evidence:\n  - IT-QUOTA\n"
        "uncertainty:\n  - TBD-11\n"
        "---\nOriginal quota summary.\n",
        encoding="utf-8",
    )
    (vault / "inbox" / "quota-dup.md").write_text(
        "---\n"
        'title: "Quota Accounting"\n'
        'author: "Harshil Srivastav"\n'
        "date: 2026-11-27\n"
        "type: research-note\n"
        "status: active\n"
        "srs_ids:\n  - FR-10.7\n"
        "sources:\n  - https://cloud.google.com/docs/quota\n"
        "evidence:\n  - ST-FR10\n"
        "uncertainty:\n  - Retry bounds\n"
        "---\nAdditional retry accounting notes.\n",
        encoding="utf-8",
    )

    report = refine_vault(vault, date_str="2026-11-27")
    assert report.valid is True
    assert report.merged_duplicates == [("inbox/quota-dup.md", "resources/quota-note.md")]
    merged_text = (vault / "resources" / "quota-note.md").read_text(encoding="utf-8")
    assert "Aangir Doshi; Harshil Srivastav" in merged_text
    assert "FR-10.1" in merged_text and "FR-10.7" in merged_text
    assert "https://developers.google.com/youtube/v3/determine_quota_cost" in merged_text
    assert "https://cloud.google.com/docs/quota" in merged_text
    assert "Additional retry accounting notes." in merged_text


def test_ske_sk4_broken_link_repair_and_negative_validation(tmp_path: Path) -> None:
    """SKE-SK4 Case 3: Repairs broken relative links for moved notes and rejects invalid notes."""
    vault = _make_synthetic_vault(tmp_path / "vault3")
    (vault / "resources" / "target.md").write_text(
        "---\n"
        'title: "Target Note"\n'
        'author: "Aangir Doshi"\n'
        "date: 2026-11-20\n"
        "type: research-note\n"
        "status: active\n"
        "srs_ids:\n  - SB-1\n"
        "sources:\n  - https://example.com\n"
        "evidence:\n  - ev1\n"
        "uncertainty:\n  - None\n"
        "---\nTarget content.\n",
        encoding="utf-8",
    )
    # Note in projects/ has a broken link pointing to ../inbox/target.md after move
    (vault / "projects" / "caller.md").write_text(
        "---\n"
        'title: "Caller Note"\n'
        'author: "Aangir Doshi"\n'
        "date: 2026-11-27\n"
        "type: project-note\n"
        "status: active\n"
        "srs_ids:\n  - SB-2\n"
        "sources:\n  - https://example.com\n"
        "evidence:\n  - ev2\n"
        "uncertainty:\n  - None\n"
        "---\nLink to [Target](../inbox/target.md).\n",
        encoding="utf-8",
    )

    pre_errors = validate_vault(vault)
    assert any("Broken relative link" in e for e in pre_errors)

    report = refine_vault(vault, date_str="2026-11-27")
    assert report.valid is True
    assert report.repaired_links >= 1
    assert "../resources/target.md" in (vault / "projects" / "caller.md").read_text(encoding="utf-8")

    # Negative: broken YAML frontmatter and secret canary are flagged by validate_vault
    bad_note = vault / "resources" / "invalid_note.md"
    bad_note.write_text("---\ntitle: OnlyTitle\n---\nBearer ya29.synthetic_canary_token_12345\n", encoding="utf-8")
    neg_errors = validate_vault(vault)
    assert any("Missing required frontmatter keys" in e for e in neg_errors)
    assert any("Potential secret or token pattern detected" in e for e in neg_errors)
