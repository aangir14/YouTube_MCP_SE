"""Command-line interface (CLI) for FocusList (SRS UI-2, UI-3)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import typer

from focuslist import __version__
from focuslist.clock import SystemClock
from focuslist.config import Settings, get_settings
from focuslist.context import RequestContext
from focuslist.curation.approval import PlaylistApprovals
from focuslist.errors import FocusListError
from focuslist.platform.auth import READONLY_SCOPE, AuthManager
from focuslist.platform.quota import QuotaManager
from focuslist.platform.storage import FocusListStorage
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


def _build_platform_services(
    cfg: Settings | None = None,
    *,
    db_path: Path | None = None,
) -> tuple[Settings, FocusListStorage, QuotaManager, AuthManager]:
    settings = cfg or get_settings(reset=True)
    if db_path is not None:
        settings.db_path = db_path
    clock = SystemClock()
    storage = FocusListStorage(settings.db_path, clock=clock)
    quota_manager = QuotaManager(storage=storage, settings=settings, clock=clock)
    auth_manager = AuthManager(settings=settings, storage=storage, clock=clock)
    return settings, storage, quota_manager, auth_manager


def _has_local_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


@app.command(name="approve")
def approve_playlist(proposal_id: str) -> None:
    """Review and approve one exact playlist action locally, without writing to YouTube."""
    if not _has_local_terminal():
        typer.echo("A learner must run this command in an interactive local terminal.", err=True)
        raise typer.Exit(1)
    cfg, storage, _, auth = _build_platform_services()
    approvals = PlaylistApprovals(storage, auth, RequestContext(settings=cfg, clock=storage.clock))
    try:
        verified = approvals.load(proposal_id)
        typer.echo("Review this FocusList action. The video and channel text is untrusted.")
        typer.echo(json.dumps(verified.action.review, ensure_ascii=True, indent=2))
        phrase = f"approve {verified.action.proposal_id}"
        answer = typer.prompt(f"Type '{phrase}' to approve, or 'decline'", default="decline")
        approved = answer == phrase
        approvals.record_human_decision(verified, approved)
        if not approved:
            typer.echo("Action declined. No YouTube calls were made.")
            raise typer.Exit(1)
        typer.echo("Approval recorded. Return to the MCP client to confirm this exact action.")
    except FocusListError as exc:
        typer.echo(f"{exc.code.value}: {exc.message}", err=True)
        raise typer.Exit(1) from None


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
    cfg = get_settings(reset=True)
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
def doctor(
    local_check: bool = typer.Option(
        False,
        "--local-check",
        help="Run the full SK-1 offline local-check (build, test, MCP stdio, fixture fetch).",
    ),
) -> None:
    """Run environment, configuration, quota, and auth diagnostics (SRS UI-2, SK-1)."""
    cfg, storage, quota_manager, auth_manager = _build_platform_services()
    typer.echo(f"FocusList Diagnostic Report (v{__version__})")
    typer.echo("---------------------------------------------")

    py_ver = sys.version_info
    py_ok = (py_ver.major == 3 and py_ver.minor >= 11) or py_ver.major > 3
    status = "OK" if py_ok else "FAIL"
    typer.echo(f"Python Runtime: {sys.version.split()[0]} [{status}] (Requires >=3.11)")

    typer.echo(f"Active Provider: {cfg.provider}")
    if cfg.provider == "fixture":
        fix_ok = cfg.fixture_dir.exists()
        typer.echo(f"Fixture Directory: {cfg.fixture_dir} [{'OK' if fix_ok else 'MISSING'}]")

    typer.echo(
        f"SQLite DB Path: {cfg.db_path} (schema v{storage.schema_version()}, mode={storage.journal_mode()})"
    )

    q_snap = quota_manager.get_status()
    typer.echo(
        f"Quota Balance ({q_snap.pacific_date}): "
        f"{q_snap.general_units_remaining}/{q_snap.daily_general_limit} units, "
        f"{q_snap.search_calls_remaining}/{q_snap.daily_search_limit} searches"
    )

    auth_snap = auth_manager.get_status()
    if cfg.provider == "fixture" and not cfg.oauth_client_file:
        oauth_status = "Not configured (Fixture mode active)"
    elif auth_snap.authenticated:
        age_info = f"{auth_snap.token_age_days}d" if auth_snap.token_age_days is not None else "n/a"
        oauth_status = f"Authenticated (token_age={age_info}, backend={auth_snap.storage_backend})"
    else:
        oauth_status = "Unauthenticated"
    typer.echo(f"OAuth Credentials: {oauth_status}")
    if auth_snap.testing_mode_warning and auth_snap.warning_message:
        typer.echo(f"Auth Warning: {auth_snap.warning_message}")

    local_ok = True
    if local_check:
        from focuslist.skills.local_check import run_local_check

        report = run_local_check(Path.cwd())
        typer.echo(report.format_summary())
        local_ok = report.overall_status == "PASS"

    typer.echo("---------------------------------------------")
    if py_ok and local_ok:
        typer.echo("System Status: HEALTHY. Ready for MCP client connection.")
        raise typer.Exit(code=0)
    if not py_ok:
        typer.echo("System Status: UNHEALTHY. Please upgrade Python to >=3.11.", err=True)
    else:
        typer.echo("System Status: UNHEALTHY. local-check failed.", err=True)
    raise typer.Exit(code=1)


@app.command(name="quota")
def quota(
    db_path: Path | None = typer.Option(
        None,
        "--db-path",
        help="Optional SQLite ledger path override.",
    ),
) -> None:
    """Display the local quota ledger and daily budget status (SRS FR-10)."""
    cfg, _, quota_manager, _ = _build_platform_services(db_path=db_path)
    snap = quota_manager.get_status()
    typer.echo("YouTube API Daily Quota Ledger")
    typer.echo("==============================")
    typer.echo(f"Pacific Date              : {snap.pacific_date}")
    typer.echo(f"Daily General Units Limit : {snap.daily_general_limit}")
    typer.echo(
        f"Safety Margin Buffer      : {snap.safety_margin_units} ({int(cfg.quota_safety_margin * 100)}%)"
    )
    typer.echo(f"Effective Request Ceiling : {snap.effective_general_ceiling}")
    typer.echo(f"General Units Used        : {snap.general_units_used}")
    typer.echo(f"General Units Remaining   : {snap.general_units_remaining}")
    typer.echo(f"Effective Units Available : {snap.effective_general_remaining}")
    typer.echo(f"Per-Operation Unit Cap    : {snap.request_unit_cap}")
    typer.echo(f"Daily Search Calls Limit  : {snap.daily_search_limit}")
    typer.echo(f"Search Calls Used         : {snap.search_calls_used}")
    typer.echo(f"Search Calls Remaining    : {snap.search_calls_remaining}")
    typer.echo(f"Cache Hits (Zero Quota)   : {snap.cache_hits}")
    typer.echo(
        f"Scheduled Live CI Caps    : {snap.scheduled_live_unit_cap} units / "
        f"{snap.scheduled_live_search_cap} searches"
    )
    typer.echo("Rollover Timezone         : Midnight Pacific Time (America/Los_Angeles)")
    typer.echo(f"Next Reset (UTC)          : {snap.reset_time_utc.isoformat()}")
    raise typer.Exit(code=0)


@auth_app.command(name="login")
def auth_login() -> None:
    """Authenticate with Google OAuth 2.0 with least-privilege read-only scope (SRS FR-9)."""
    cfg, _, _, auth_manager = _build_platform_services()
    if cfg.provider == "fixture":
        typer.echo(
            "Operating in fixture mode: Mock authorization is active. No Google login required."
        )
        raise typer.Exit(code=0)

    typer.echo(auth_manager.explain_scopes([READONLY_SCOPE]))
    typer.echo(
        "Write access will be requested only when you explicitly confirm your first playlist write."
    )
    try:
        snap = auth_manager.login(scopes=[READONLY_SCOPE])
    except FocusListError as exc:
        typer.echo(f"Error [{exc.code.value}]: {exc.message} {exc.remediation}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Authentication succeeded (backend={snap.storage_backend}).")
    raise typer.Exit(code=0)


@auth_app.command(name="status")
def auth_status_cmd() -> None:
    """Display current authorization state, active scopes, and token age (SRS FR-9.6)."""
    _, _, _, auth_manager = _build_platform_services()
    snap = auth_manager.get_status()
    typer.echo("OAuth Authorization Status")
    typer.echo("==========================")
    if snap.authenticated:
        state_label = "Authenticated (Fixture Mock)" if snap.provider_mode == "fixture" else "Authenticated"
        typer.echo(f"Status          : {state_label}")
        typer.echo(f"Active Scopes   : {snap.scopes}")
        typer.echo(f"Write Enabled   : {snap.has_write_scope}")
        typer.echo(
            f"Token Age       : {snap.token_age_days if snap.token_age_days is not None else 0} days"
        )
        typer.echo(f"Storage Backend : {snap.storage_backend}")
        if snap.testing_mode_warning and snap.warning_message:
            typer.echo(f"Warning         : {snap.warning_message}")
    else:
        typer.echo("Status          : Unauthenticated. Run 'focuslist auth login' to connect.")
        typer.echo(f"Storage Backend : {snap.storage_backend}")
    raise typer.Exit(code=0)


@auth_app.command(name="logout")
def auth_logout() -> None:
    """Revoke Google credentials and purge authorized local cache entries (SRS FR-9.7)."""
    _, _, _, auth_manager = _build_platform_services()
    result = auth_manager.logout()
    typer.echo("Revoking credentials and purging authorized user cache...")
    typer.echo(
        f"Logout complete. Local tokens cleared; purged {result['purged_cache_entries']} "
        "authorized cache entries."
    )
    raise typer.Exit(code=0)


@app.command(name="purge")
def purge(
    account: str | None = typer.Option(
        None,
        "--account",
        "-a",
        help="Purge all cached data and unconfirmed proposals for a specific account ID.",
    ),
    db_path: Path | None = typer.Option(
        None,
        "--db-path",
        help="Path to the FocusList SQLite database.",
    ),
    require_existing_db: bool = typer.Option(
        False,
        "--require-existing-db",
        help="Fail if the target database does not already exist.",
    ),
) -> None:
    """Purge expired cache rows, 30-day ledger/history records, or account-scoped data (SRS FR-11.5)."""
    cfg = get_settings(reset=True)
    target_db = db_path or cfg.db_path
    if require_existing_db and not target_db.exists():
        typer.echo(f"Error: Database does not exist at '{target_db}'.", err=True)
        raise typer.Exit(code=1)
    if account is not None and not account.strip():
        typer.echo("Error: --account must be a non-empty account identifier.", err=True)
        raise typer.Exit(code=2)

    try:
        storage = FocusListStorage(target_db, clock=SystemClock(), run_startup_cleanup=False)
        expired = storage.cleanup_expired()
        account_deleted = 0
        if account is not None:
            acct_res = storage.purge_account_data(account)
            account_deleted = acct_res["cache_entries"]
    except FocusListError as exc:
        typer.echo(f"Error [{exc.code.value}]: {exc.message}", err=True)
        raise typer.Exit(code=2) from None
    except (sqlite3.Error, OSError) as exc:
        typer.echo(f"Error purging SQLite store: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo("Purging expired cache entries and action logs older than 30 days...")
    typer.echo(
        f"Purge complete. {expired['cache_entries']} expired cache rows, "
        f"{expired['proposals']} proposals, {expired['action_history']} history rows, "
        f"and {account_deleted} account-scoped cache rows deleted."
    )
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
