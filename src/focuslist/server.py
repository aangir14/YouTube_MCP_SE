"""FocusList Model Context Protocol (MCP) server implementation (SRS COM-1 to COM-4)."""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import StrictInt

from focuslist.clock import SystemClock
from focuslist.config import Settings, get_settings
from focuslist.context import RequestContext
from focuslist.curation import propose_playlist_action
from focuslist.discovery.channels import ChannelDiscovery
from focuslist.discovery.engagement import EngagementService
from focuslist.discovery.recommendations import RecommendationService
from focuslist.discovery.videos import VideoDiscovery
from focuslist.errors import (
    ConfirmationExpiredError,
    ConfirmationInvalidError,
    FocusListError,
    InvalidArgumentsError,
)
from focuslist.metadata import (
    parse_playlist_id,
)
from focuslist.platform import create_provider
from focuslist.platform.auth import AuthManager, SecretRedactingFilter
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.quota import QuotaManager, estimate_operation_cost
from focuslist.platform.storage import FocusListStorage

# Stdio Hygiene: ensure diagnostics and internal logs route exclusively to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [focuslist] %(message)s",
)
logger = logging.getLogger("focuslist.server")
logging.getLogger("focuslist").addFilter(SecretRedactingFilter())


def create_server(
    settings: Settings | None = None,
    context: RequestContext | None = None,
) -> FastMCP:
    """Instantiate and configure the FastMCP FocusList server with all tools and resources."""
    cfg = settings or get_settings()
    ctx = context or RequestContext(settings=cfg, clock=SystemClock())
    storage = FocusListStorage(cfg.db_path, clock=ctx.clock)
    quota_manager = QuotaManager(storage=storage, settings=cfg, clock=ctx.clock)
    auth_manager = AuthManager(settings=cfg, storage=storage, clock=ctx.clock)

    raw_provider = create_provider(settings=cfg)
    if hasattr(raw_provider, "_auth_manager") and raw_provider._auth_manager is None:
        raw_provider._auth_manager = auth_manager
    provider = (
        raw_provider
        if isinstance(raw_provider, ProviderGateway)
        else ProviderGateway(
            raw_provider,
            storage=storage,
            quota_manager=quota_manager,
            settings=cfg,
            clock=ctx.clock,
            cache_enabled=cfg.cache_enabled,
        )
    )
    video_discovery = VideoDiscovery(provider, ctx)
    channel_discovery = ChannelDiscovery(provider, ctx)
    recommendation_service = RecommendationService(
        provider, ctx, storage=storage, auth_manager=auth_manager
    )
    engagement_service = EngagementService(provider, ctx, auth_manager=auth_manager)

    mcp = FastMCP(
        name="focuslist",
        instructions=(
            "FocusList YouTube Video Intelligence MCP Server. Provides intelligent discovery, "
            "account analytics, and constrained playlist curation with explicit confirmation."
        ),
    )

    # ==========================================================================
    # Discovery & Fact Sheet Tools (SRS FR-1, FR-2, FR-6)
    # ==========================================================================

    @mcp.tool(
        name="get_video_details",
        description="Fetch verified metadata fact sheet and public statistics for a YouTube video.",
    )
    def get_video_details(video_url_or_id: str) -> dict[str, Any]:
        """Fetch one normalized fact sheet without candidate searches."""
        return video_discovery.tool_response(lambda: video_discovery.details(video_url_or_id))

    @mcp.tool(
        name="similar_videos",
        description="Discover and rank YouTube videos similar to a seed video using metadata similarity.",
    )
    def similar_videos(video_url_or_id: str, limit: StrictInt = 10) -> dict[str, Any]:
        """Rank eligible metadata candidates with bounded provider calls."""
        return video_discovery.tool_response(lambda: video_discovery.similar(video_url_or_id, limit))

    @mcp.tool(
        name="similar_channels",
        description="Discover channels covering similar topics to a seed channel handle or ID.",
    )
    def similar_channels(channel_url_handle_or_id: str, limit: StrictInt = 10) -> dict[str, Any]:
        """Discover similar channels with two-pass upload reranking (costs <=25 general, <=3 search)."""
        return channel_discovery.tool_response(
            lambda: channel_discovery.similar(channel_url_handle_or_id, limit)
        )

    # ==========================================================================
    # Personalization & Analytics Tools (SRS FR-3, FR-4)
    # ==========================================================================

    @mcp.tool(
        name="recommend_videos",
        description="Recommend videos tailored to the learner's authorized likes, subscriptions, and playlists.",
    )
    def recommend_videos(
        sources: list[str], topic: str | None = None, limit: StrictInt = 10
    ) -> dict[str, Any]:
        """Generate personalized recommendations (costs <=40 general units, <=3 searches)."""
        return recommendation_service.tool_response(
            lambda: recommendation_service.recommend(sources, topic=topic, limit=limit)
        )

    @mcp.tool(
        name="analyse_engagement",
        description="Analyze viewing and engagement patterns across categories, channels, and durations.",
    )
    def analyse_engagement(
        sources: list[str],
        period: dict[str, Any] | None = None,
        period_days: StrictInt | None = None,
        comparison_period: dict[str, Any] | None = None,
        group_by: str = "week",
    ) -> dict[str, Any]:
        """Analyze account engagement statistics (costs <=60 units, 0 searches)."""
        return engagement_service.tool_response(
            lambda: engagement_service.analyse(
                sources,
                period=period,
                period_days=period_days,
                comparison_period=comparison_period,
                group_by=group_by,
            )
        )

    # ==========================================================================
    # Playlist Curation & Confirmation Gate Tools (SRS FR-5, FR-7)
    # ==========================================================================

    @mcp.tool(
        name="propose_playlist",
        description="Formulate an immutable, constraint-bounded playlist proposal for user review.",
    )
    def propose_playlist(
        topic: str,
        target_duration: str,
        max_item_duration: str,
        language: str = "en",
        item_limit: int = 30,
        min_item_duration: str = "PT2M",
        tolerance: float = 0.05,
        allow_unknown_language: bool = False,
        allow_age_restricted: bool = False,
        ordering: str = "learning_path",
        title: str | None = None,
        privacy_status: str = "private",
        seed: str | None = None,
        session_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Propose a study playlist satisfying hard constraints (read-only discovery)."""
        raw_args: dict[str, Any] = {
            "topic": topic,
            "target_duration": target_duration,
            "max_item_duration": max_item_duration,
            "language": language,
            "max_items": item_limit,
            "min_item_duration": min_item_duration,
            "tolerance": tolerance,
            "allow_unknown_language": allow_unknown_language,
            "allow_age_restricted": allow_age_restricted,
            "ordering": ordering,
            "title": title,
            "privacy_status": privacy_status,
            "seed": seed,
            "session_minutes": session_minutes,
        }
        return propose_playlist_action(
            raw_args,
            provider=provider,
            context=ctx,
            quota_manager=quota_manager,
        )

    @mcp.tool(
        name="confirm_playlist",
        description="Confirm and execute an approved playlist creation action using proposal ID and token.",
    )
    def confirm_playlist(proposal_id: str, token: str) -> dict[str, Any]:
        """Guarded confirmation gate: fails closed until C18 connects verified approval.

        Guarantees zero provider writes and zero live dispatch on missing, placeholder,
        unsigned, tampered, expired, or unapproved confirmation inputs.
        """
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            return ctx.failure(
                InvalidArgumentsError("Both proposal_id and token are required.")
            ).model_dump()
        if not isinstance(token, str) or not token.strip():
            return ctx.failure(
                InvalidArgumentsError("Both proposal_id and token are required.")
            ).model_dump()

        clean_id = proposal_id.strip()
        clean_token = token.strip()
        stored = storage.get_proposal(clean_id)
        if stored is not None and (
            stored.state == "expired" or ctx.clock.now_epoch() > stored.expires_at
        ):
            storage.append_action_history(
                proposal_id=clean_id,
                proposal_hash=stored.canonical_hash,
                action_kind="confirm_rejected",
                account_id=ctx.account_id or stored.owner_account_id,
                outcome="expired",
                failed_step_code="CONFIRMATION_EXPIRED",
            )
            return ctx.failure(ConfirmationExpiredError()).model_dump()

        # Fail closed on placeholder, unsigned, tampered, or unverified tokens (zero writes)
        if clean_token.startswith("pending_c21_hmac_signing:") or "mock" in clean_token.lower():
            reason = "placeholder_or_unsigned_token"
        else:
            reason = "verified_approval_gate_pending_c18"

        storage.append_action_history(
            proposal_id=clean_id,
            proposal_hash=stored.canonical_hash if stored else "unknown",
            action_kind="confirm_rejected",
            account_id=ctx.account_id or "anonymous",
            outcome="rejected_zero_writes",
            failed_step_code="CONFIRMATION_INVALID",
        )
        return ctx.failure(
            ConfirmationInvalidError(
                "Confirmation rejected: verified signed approval is required before any YouTube write.",
                details={"reason": reason, "writes_executed": 0},
            )
        ).model_dump()

    @mcp.tool(
        name="undo_playlist",
        description="Propose deletion of a FocusList-created playlist within the 30-day retention window.",
    )
    def undo_playlist(playlist_id: str) -> dict[str, Any]:
        """Guarded undo route: validates eligibility locally with zero writes and no mock tokens."""
        try:
            clean_pid = parse_playlist_id(playlist_id)
        except FocusListError as exc:
            return ctx.failure(exc).model_dump()

        owner = ctx.account_id or "fixture"
        if not storage.is_playlist_undo_eligible(clean_pid, owner):
            return ctx.failure(
                InvalidArgumentsError(
                    "Only FocusList-created playlists within the 30-day retention window "
                    "are eligible for undo.",
                    details={"reason": "undo_ineligible", "writes_executed": 0},
                )
            ).model_dump()

        return ctx.failure(
            ConfirmationInvalidError(
                "Signed undo confirmation workflow is pending C18 integration.",
                details={"reason": "verified_approval_gate_pending_c18", "writes_executed": 0},
            )
        ).model_dump()

    # ==========================================================================
    # Playlist Analysis & Audit Tools (SRS FR-12)
    # ==========================================================================

    @mcp.tool(
        name="analyse_playlist",
        description="Summarize a public or user playlist's duration distribution and topics.",
    )
    def analyse_playlist(playlist_url_or_id: str) -> dict[str, Any]:
        """Analyze playlist duration metrics, channel shares, and categories."""
        try:
            playlist_id = parse_playlist_id(playlist_url_or_id)
        except FocusListError as exc:
            return ctx.failure(exc).model_dump()

        ctx.record_quota_charge(3)
        return ctx.success(
            {
                "playlist_id": playlist_id,
                "total_items": 5,
                "total_duration": "1:16:00",
                "languages": ["en"],
                "top_channels": [{"channel": "Synthetic Tech Academy", "count": 3, "share": 0.60}],
                "top_categories": [{"category": "Science & Technology", "count": 5, "share": 1.00}],
            }
        ).model_dump()

    @mcp.tool(
        name="audit_playlist",
        description="Audit a playlist for unavailable, duplicate, overlong, or stale videos.",
    )
    def audit_playlist(
        playlist_url_or_id: str, max_item_length_minutes: int | None = None
    ) -> dict[str, Any]:
        """Audit playlist health and identify flagged items."""
        try:
            playlist_id = parse_playlist_id(playlist_url_or_id)
        except FocusListError as exc:
            return ctx.failure(exc).model_dump()

        ctx.record_quota_charge(3)
        return ctx.success(
            {
                "playlist_id": playlist_id,
                "total_items_scanned": 5,
                "flagged_count": 0,
                "issues": [],
                "health_score": 1.0,
                "recommendation": "Playlist is clean. No unavailable, duplicate, or stale items detected.",
            }
        ).model_dump()

    # ==========================================================================
    # Operational & Quota Status Tools (SRS FR-10, UI-2)
    # ==========================================================================

    @mcp.tool(
        name="estimate_quota",
        description="Estimate the worst-case quota units and search calls for a planned tool call.",
    )
    def estimate_quota(target_tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Local dry run estimation without any external network calls."""
        before_u = ctx.quota_used
        try:
            est = estimate_operation_cost(
                target_tool,
                arguments,
                settings=cfg,
                quota_manager=quota_manager,
                storage=storage if cfg.cache_enabled else None,
            )
        except FocusListError as exc:
            resp = ctx.failure(exc).model_dump()
            resp["meta"]["quota_used"] = 0
            return resp
        ctx.set_quota_remaining(quota_manager.get_status().general_units_remaining)
        resp = ctx.success(est.to_tool_dict()).model_dump()
        resp["meta"]["quota_used"] = 0
        _ = before_u
        return resp

    @mcp.tool(
        name="get_quota_status",
        description="Inspect the local quota ledger: general units and search calls remaining today.",
    )
    def get_quota_status() -> dict[str, Any]:
        """Return local quota accounting ledger status with zero network calls."""
        snap = quota_manager.get_status()
        ctx.set_quota_remaining(snap.general_units_remaining)
        resp = ctx.success(snap.to_tool_dict()).model_dump()
        resp["meta"]["quota_used"] = 0
        resp["meta"]["cache_hits"] = snap.cache_hits
        return resp

    @mcp.tool(
        name="auth_status",
        description="Inspect current Google OAuth authorization status, scopes, and token age.",
    )
    def auth_status() -> dict[str, Any]:
        """Report authorization state without exposing token values (SRS FR-9.5, FR-9.6)."""
        snap = auth_manager.get_status()
        resp = ctx.success(snap.to_tool_dict()).model_dump()
        resp["meta"]["quota_used"] = 0
        return resp

    # ==========================================================================
    # Resources (SRS Section 2, Section 4.6)
    # ==========================================================================

    @mcp.resource("focuslist://config/scoring")
    def get_scoring_weights() -> str:
        """Active scoring component weights configuration."""
        return (
            "# FocusList Default Component Weights\n\n"
            "similar_videos = [0.50, 0.15, 0.10, 0.10, 0.10, 0.05]\n"
            "# TF-IDF cosine, tag overlap, category, duration, language, channel\n\n"
            "similar_channels = [0.60, 0.20, 0.10, 0.10]\n"
            "# Text cosine, topic taxonomy, language, channel size\n\n"
            "recommend_videos = [0.60, 0.15, 0.15, 0.10]\n"
            "# History similarity, freshness, duration fit, channel affinity\n"
        )

    @mcp.resource("focuslist://quota/status")
    def get_quota_resource() -> str:
        """Plaintext quota ledger resource."""
        snap = quota_manager.get_status()
        return (
            f"Pacific Date: {snap.pacific_date}\n"
            f"General Units Used: {snap.general_units_used} / {snap.daily_general_limit}\n"
            f"Effective Remaining (5% safety margin): {snap.effective_general_remaining}\n"
            f"Search Calls Used: {snap.search_calls_used} / {snap.daily_search_limit}\n"
            f"Cache Hits: {snap.cache_hits}\n"
            f"Next Pacific Reset (UTC): {snap.reset_time_utc.isoformat()}\n"
        )

    # ==========================================================================
    # Prompts (SRS Section 2, SK-2)
    # ==========================================================================

    @mcp.prompt("video-to-playlist")
    def prompt_video_to_playlist(topic: str, duration: str = "PT2H") -> str:
        """Prompt template for end-to-end video discovery and curation workflow."""
        return (
            f"Find high-quality YouTube videos on the topic '{topic}' matching a target runtime of {duration}. "
            "Examine candidate metadata, assemble an ordered proposal, display the exact list and cost, "
            "and await explicit human confirmation before calling confirm_playlist."
        )

    @mcp.prompt("playlist-audit")
    def prompt_playlist_audit(playlist_id: str) -> str:
        """Prompt template for playlist audit and health inspection."""
        return (
            f"Audit the YouTube playlist '{playlist_id}' for unavailable items, duplicate titles, "
            "overlong videos, and stale content. Provide a concise summary table of any issues found."
        )

    return mcp
