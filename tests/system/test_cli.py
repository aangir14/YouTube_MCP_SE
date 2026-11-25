"""System tests verifying FocusList CLI commands and exit codes (SRS UI-2, UI-3)."""

from typer.testing import CliRunner

from focuslist.cli import app

runner = CliRunner()


def test_cli_help() -> None:
    """Verify root --help returns exit code 0 and displays commands."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "FocusList" in res.output
    assert "serve" in res.output
    assert "doctor" in res.output
    assert "quota" in res.output
    assert "auth" in res.output
    assert "purge" in res.output


def test_cli_doctor() -> None:
    """Verify doctor command runs diagnostic report and exits with code 0."""
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "FocusList Diagnostic Report" in res.output
    assert "Python Runtime:" in res.output
    assert "Active Provider:" in res.output
    assert "System Status: HEALTHY" in res.output


def test_cli_quota() -> None:
    """Verify quota command displays daily limits and exits with code 0."""
    res = runner.invoke(app, ["quota"])
    assert res.exit_code == 0
    assert "YouTube API Daily Quota Ledger" in res.output
    assert "Daily General Units Limit : 10000" in res.output
    assert "Safety Margin Buffer      : 500 (5%)" in res.output
    assert "Daily Search Calls Limit  : 100" in res.output


def test_cli_auth_subcommands() -> None:
    """Verify auth login, status, and logout subcommands."""
    res_status = runner.invoke(app, ["auth", "status"])
    assert res_status.exit_code == 0
    assert "OAuth Authorization Status" in res_status.output

    res_login = runner.invoke(app, ["auth", "login"])
    assert res_login.exit_code == 0

    res_logout = runner.invoke(app, ["auth", "logout"])
    assert res_logout.exit_code == 0
    assert "Logout complete" in res_logout.output


def test_cli_purge() -> None:
    """Verify purge command runs and exits with code 0."""
    res = runner.invoke(app, ["purge"])
    assert res.exit_code == 0
    assert "Purge complete" in res.output


def test_cli_record_fixtures_help() -> None:
    """Verify record-fixtures command returns help and exits cleanly."""
    res = runner.invoke(app, ["record-fixtures", "--help"])
    assert res.exit_code == 0
    assert "Record live YouTube API responses" in res.output


def test_cli_invalid_command() -> None:
    """Verify non-existent command returns nonzero failure code."""
    res = runner.invoke(app, ["non_existent_command"])
    assert res.exit_code != 0
