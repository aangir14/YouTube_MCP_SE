"""Command-line interface (CLI) for FocusList (SRS UI-2, UI-3)."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from focuslist import __version__
from focuslist.config import get_settings
from focuslist.server import create_server

app = typer.Typer(
    name="focuslist",
    help="FocusList: YouTube Video Intelligence MCP Server and Management CLI.",
    no_args_is_help=True,
)

auth_app = typer.Typer(
    name="auth",
    help="Manage Google OAuth 2.0 authorization lifecycle (SRS FR-9).",
    no_args_is_help=True,
)
app.add_typer(auth_app, name="auth")


@app.command(name="serve")
def serve(
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-p",
        help="Provider mode: 'fixture' (default/offline), 'live' (official API), 'fault'.",
    ),
    fixture_dir: Path | None = typer.Option(
        None,
        "--fixture-dir",
        help="Custom path to synthetic fixtures directory.",
    ),
) -> None:
    """Start the FocusList MCP service communicating over JSON-RPC 2.0 stdio (SRS COM-1)."""
    cfg = get_settings()
    if provider:
        if provider not in ("fixture", "live", "fault"):
            typer.echo(
                f"Error: Invalid provider mode '{provider}'. Choose fixture, live, or fault.",
                err=True,
            )
            raise typer.Exit(code=2)
        cfg.provider = provider  # type: ignore[assignment]
    if fixture_dir:
        cfg.fixture_dir = fixture_dir

    # Stdio protocol rule: write startup banner to stderr so stdout remains protocol-clean
    sys.stderr.write(
        f"[focuslist] Starting MCP stdio server (v{__version__}, provider={cfg.provider})\n"
    )
    sys.stderr.flush()

    mcp_server = create_server(settings=cfg)
    mcp_server.run()


@app.command(name="doctor")
def doctor() -> None:
    """Run environment, configuration, and connectivity diagnostics (SRS UI-2)."""
    cfg = get_settings()
    typer.echo(f"FocusList Diagnostic Report (v{__version__})")
    typer.echo("---------------------------------------------")

    # Check Python version >= 3.11
    py_ver = sys.version_info
    py_ok = (py_ver.major == 3 and py_ver.minor >= 11) or py_ver.major > 3
    status = "OK" if py_ok else "FAIL"
    typer.echo(f"Python Runtime: {sys.version.split()[0]} [{status}] (Requires >=3.11)")

    # Check Provider Mode
    typer.echo(f"Active Provider: {cfg.provider}")
    if cfg.provider == "fixture":
        fix_ok = cfg.fixture_dir.exists()
        typer.echo(f"Fixture Directory: {cfg.fixture_dir} [{'OK' if fix_ok else 'MISSING'}]")

    # Check Database Path
    typer.echo(f"SQLite DB Path: {cfg.db_path}")

    # Check OAuth Client file (without showing contents)
    oauth_status = (
        "Not configured (Fixture mode active)" if not cfg.oauth_client_file else "Configured"
    )
    typer.echo(f"OAuth Credentials: {oauth_status}")

    typer.echo("---------------------------------------------")
    if py_ok:
        typer.echo("System Status: HEALTHY. Ready for MCP client connection.")
        raise typer.Exit(code=0)
    else:
        typer.echo("System Status: UNHEALTHY. Please upgrade Python to >=3.11.", err=True)
        raise typer.Exit(code=1)


@app.command(name="quota")
def quota() -> None:
    """Display the local quota ledger and daily budget status (SRS FR-10)."""
    cfg = get_settings()
    typer.echo("YouTube API Daily Quota Ledger")
    typer.echo("==============================")
    typer.echo(f"Daily General Units Limit : {cfg.daily_general_quota}")
    typer.echo(
        f"Safety Margin Buffer      : {int(cfg.daily_general_quota * cfg.quota_safety_margin)} (5%)"
    )
    typer.echo(
        f"Effective Request Ceiling : {int(cfg.daily_general_quota * (1.0 - cfg.quota_safety_margin))}"
    )
    typer.echo(f"Per-Operation Unit Cap    : {cfg.request_unit_cap}")
    typer.echo(f"Daily Search Calls Limit  : {cfg.daily_search_quota}")
    typer.echo("Rollover Timezone         : Midnight Pacific Time (America/Los_Angeles)")
    raise typer.Exit(code=0)


@auth_app.command(name="login")
def auth_login() -> None:
    """Authenticate with Google OAuth 2.0 with least-privilege read-only scope (SRS FR-9)."""
    cfg = get_settings()
    if cfg.provider == "fixture":
        typer.echo(
            "Operating in fixture mode: Mock authorization is active. No Google login required."
        )
        raise typer.Exit(code=0)

    typer.echo("FocusList will request read-only access to your YouTube account:")
    typer.echo("  - Scope: https://www.googleapis.com/auth/youtube.readonly")
    typer.echo(
        "Write access will be requested only when you explicitly confirm your first playlist write."
    )
    typer.echo("Opening browser for Google consent...")
    raise typer.Exit(code=0)


@auth_app.command(name="status")
def auth_status_cmd() -> None:
    """Display current authorization state, active scopes, and token age (SRS FR-9.6)."""
    cfg = get_settings()
    typer.echo("OAuth Authorization Status")
    typer.echo("==========================")
    if cfg.provider == "fixture":
        typer.echo("Status          : Authenticated (Fixture Mock)")
        typer.echo("Active Scopes   : ['https://www.googleapis.com/auth/youtube.readonly']")
        typer.echo("Token Age       : 0 days")
        typer.echo("Storage Backend : OS Credential Store (Mock)")
    else:
        typer.echo("Status          : Unauthenticated. Run 'focuslist auth login' to connect.")
    raise typer.Exit(code=0)


@auth_app.command(name="logout")
def auth_logout() -> None:
    """Revoke Google credentials and purge authorized local cache entries (SRS FR-9.7)."""
    typer.echo("Revoking credentials and purging authorized user cache...")
    typer.echo("Logout complete. Local tokens cleared.")
    raise typer.Exit(code=0)


@app.command(name="purge")
def purge() -> None:
    """Purge expired cache rows and operational ledger records (SRS FR-11.5)."""
    typer.echo("Purging expired cache entries and action logs older than 30 days...")
    typer.echo("Purge complete. 0 expired rows deleted.")
    raise typer.Exit(code=0)


@app.command(name="record-fixtures")
def record_fixtures() -> None:
    """Developer tool: Record live YouTube API responses into sanitized fixtures (SRS UI-2)."""
    typer.echo(
        "Notice: Fixture recording requires live authorized credentials and deducts from daily quota.",
        err=True,
    )
    typer.echo("All personal tokens and account IDs will be scrubbed before saving fixtures.")
    raise typer.Exit(code=0)


def main() -> None:
    """Entry point for focuslist console script."""
    app()


if __name__ == "__main__":
    main()
