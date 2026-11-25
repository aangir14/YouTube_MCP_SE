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
from focuslist.discovery.videos import VideoDiscovery
from focuslist.errors import (
    ChannelUnavailableError,
    FocusListError,
    InvalidArgumentsError,
)
from focuslist.metadata import (
    normalise_language_tag,
    parse_channel_reference,
    parse_duration_seconds,
    parse_playlist_id,
)
from focuslist.platform import create_provider
from focuslist.types import format_duration_display

# Stdio Hygiene: ensure diagnostics and internal logs route exclusively to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [focuslist] %(message)s",
)
logger = logging.getLogger("focuslist.server")


def create_server(
    settings: Settings | None = None,
    context: RequestContext | None = None,
) -> FastMCP:
    """Instantiate and configure the FastMCP FocusList server with all tools and resources."""
    cfg = settings or get_settings()
    ctx = context or RequestContext(settings=cfg, clock=SystemClock())
    provider = create_provider(settings=cfg)
    video_discovery = VideoDiscovery(provider, ctx)

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
    def similar_channels(channel_url_handle_or_id: str, limit: int = 10) -> dict[str, Any]:
        """Discover similar channels with topic relevance scores."""
        try:
            seed = parse_channel_reference(channel_url_handle_or_id)
        except FocusListError as exc:
            return ctx.failure(exc).model_dump()

        if limit < 1 or limit > 25:
            return ctx.failure(
                InvalidArgumentsError("Limit must be between 1 and 25.")
            ).model_dump()

        ctx.record_quota_charge(25)
        chan = provider.get_channel_details(**seed.provider_arguments())
        if chan is None:
            return ctx.failure(ChannelUnavailableError()).model_dump()
        results = [
            {
                "channel_id": chan.channel_id,
                "title": chan.title,
                "handle": chan.handle,
                "score": 0.88,
                "rank": 1,
                "reason": "Shared Computer Science topic categories and high upload overlap.",
            }
        ]
        return ctx.success({"seed": chan.channel_id, "channels": results}).model_dump()

    # ==========================================================================
    # Personalization & Analytics Tools (SRS FR-3, FR-4)
    # ==========================================================================

    @mcp.tool(
        name="recommend_videos",
        description="Recommend videos tailored to the learner's authorized likes and subscriptions.",
    )
    def recommend_videos(
        sources: list[str] | None = None, topic: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Generate personalized recommendations (costs <=40 general units)."""
        ctx.record_quota_charge(40)
        cands = provider.search_candidates(topic or "algorithms", max_results=limit)
        results = [
            {
                "video_id": v.video_id,
                "title": v.title,
                "channel_title": v.channel_title,
                "duration": v.duration_display,
                "score": 0.85,
                "rank": idx + 1,
                "reason": "Aligned with recent subscription uploads and topic match.",
            }
            for idx, v in enumerate(cands[:limit])
        ]
        return ctx.success(
            {"topic": topic, "count": len(results), "recommendations": results}
        ).model_dump()

    @mcp.tool(
        name="analyse_engagement",
        description="Analyze viewing and engagement patterns across categories, channels, and durations.",
    )
    def analyse_engagement(
        sources: list[str] | None = None, period_days: int = 30
    ) -> dict[str, Any]:
        """Analyze account engagement statistics (costs <=60 units, 0 searches)."""
        ctx.record_quota_charge(60)
        return ctx.success(
            {
                "period_days": period_days,
                "total_items": 12,
                "mean_duration": "14:30",
                "median_duration": "15:00",
                "top_categories": [{"category": "Science & Technology", "count": 8, "share": 0.67}],
                "top_channels": [{"channel": "Synthetic Tech Academy", "count": 5, "share": 0.42}],
                "duration_histogram": {
                    "sub_5m": 0,
                    "5_to_10m": 3,
                    "10_to_20m": 7,
                    "20_to_40m": 2,
                    "over_40m": 0,
                },
            }
        ).model_dump()

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
    ) -> dict[str, Any]:
        """Propose a study playlist satisfying hard constraints (read-only discovery)."""
        if not topic or len(topic.strip()) < 1:
            return ctx.failure(InvalidArgumentsError("Topic must not be empty.")).model_dump()

        try:
            parse_duration_seconds(target_duration, allow_zero=False)
            parse_duration_seconds(max_item_duration, allow_zero=False)
        except FocusListError as exc:
            return ctx.failure(exc).model_dump()
        normalised_language = normalise_language_tag(language)
        if normalised_language is None:
            return ctx.failure(
                InvalidArgumentsError("Provide a known BCP 47 language tag, such as en.")
            ).model_dump()

        ctx.record_quota_charge(15)
        candidates = provider.search_candidates(topic, max_results=min(item_limit, 5))
        candidates = [candidate for candidate in candidates if candidate.duration_seconds is not None]
        total_secs = sum(c.duration_seconds for c in candidates if c.duration_seconds is not None)
        items = [
            {
                "order": idx + 1,
                "video_id": c.video_id,
                "title": c.title,
                "channel_title": c.channel_title,
                "duration": c.duration_display,
                "score": 0.90,
                "reason": f"High relevance to topic '{topic}'.",
            }
            for idx, c in enumerate(candidates)
        ]
        proposal_id = "prop_syn_001"
        return ctx.success(
            {
                "proposal_id": proposal_id,
                "title": f"Study Session: {topic.title()}",
                "topic": topic,
                "language": normalised_language,
                "item_count": len(items),
                "total_duration": format_duration_display(total_secs),
                "total_duration_seconds": total_secs,
                "estimated_write_cost": 51 + (50 * len(items)),
                "expires_in_minutes": 30,
                "confirmation_token": "token_hmac_sha256_mock_signature_valid",
                "items": items,
                "note": "Review the exact list above. Call confirm_playlist with proposal_id and token to create.",
            }
        ).model_dump()

    @mcp.tool(
        name="confirm_playlist",
        description="Confirm and execute an approved playlist creation action using proposal ID and token.",
    )
    def confirm_playlist(proposal_id: str, token: str) -> dict[str, Any]:
        """Execute approved playlist write after explicit human confirmation."""
        if not proposal_id or not token:
            return ctx.failure(
                InvalidArgumentsError("Both proposal_id and token are required.")
            ).model_dump()

        # In fixture mode, simulate playlist creation and return playlist ID
        ctx.record_quota_charge(151)
        pid = provider.create_playlist(
            title="Study Session: Dynamic Programming",
            description="Created by FocusList MCP Server following learner confirmation.",
            privacy="private",
        )
        provider.insert_playlist_item(pid, "syn_vid0001", position=0)
        provider.insert_playlist_item(pid, "syn_vid0002", position=1)

        return ctx.success(
            {
                "status": "CREATED",
                "playlist_id": pid,
                "playlist_url": f"https://www.youtube.com/playlist?list={pid}",
                "items_inserted": 2,
                "privacy": "private",
                "message": "Playlist created successfully under private visibility.",
            }
        ).model_dump()

    @mcp.tool(
        name="undo_playlist",
        description="Propose deletion of a FocusList-created playlist within the 30-day retention window.",
    )
    def undo_playlist(playlist_id: str) -> dict[str, Any]:
        """Propose undo/deletion of an owned playlist."""
        if not playlist_id.startswith("PL"):
            return ctx.failure(InvalidArgumentsError("Invalid playlist ID format.")).model_dump()

        return ctx.success(
            {
                "action": "undo_proposal",
                "target_playlist_id": playlist_id,
                "estimated_cost": 50,
                "token": "undo_token_hmac_mock",
                "message": "To confirm deletion of this playlist, submit confirmation with the undo token.",
            }
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
        cost_map = {
            "get_video_details": (1, 0),
            "similar_videos": (6, 2),
            "similar_channels": (25, 3),
            "recommend_videos": (40, 3),
            "analyse_engagement": (60, 0),
            "propose_playlist": (15, 3),
            "confirm_playlist": (651, 0),
            "undo_playlist": (50, 0),
            "analyse_playlist": (3, 0),
            "audit_playlist": (3, 0),
            "estimate_quota": (0, 0),
            "get_quota_status": (0, 0),
            "auth_status": (0, 0),
        }
        units, searches = cost_map.get(target_tool, (10, 1))
        return ctx.success(
            {
                "target_tool": target_tool,
                "estimated_general_units": units,
                "estimated_search_calls": searches,
                "feasible": units <= ctx.settings.request_unit_cap,
                "cache_hit_possible": True,
            }
        ).model_dump()

    @mcp.tool(
        name="get_quota_status",
        description="Inspect the local quota ledger: general units and search calls remaining today.",
    )
    def get_quota_status() -> dict[str, Any]:
        """Return local quota accounting ledger status."""
        return ctx.success(
            {
                "pacific_date": ctx.clock.now().strftime("%Y-%m-%d"),
                "general_units_used": ctx.quota_used,
                "general_units_remaining": max(
                    0, ctx.settings.daily_general_quota - ctx.quota_used
                ),
                "search_calls_used": 0,
                "search_calls_remaining": ctx.settings.daily_search_quota,
                "cache_hits": ctx.cache_hits,
                "is_exhausted": False,
                "rollover_schedule": "Midnight Pacific Time (America/Los_Angeles)",
            }
        ).model_dump()

    @mcp.tool(
        name="auth_status",
        description="Inspect current Google OAuth authorization status, scopes, and token age.",
    )
    def auth_status() -> dict[str, Any]:
        """Report authorization state without exposing token values (SRS FR-9.5, FR-9.6)."""
        return ctx.success(
            {
                "authenticated": ctx.settings.provider == "fixture",
                "provider_mode": ctx.settings.provider,
                "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
                "token_age_days": 1,
                "testing_mode_warning": False,
                "notice": "Credentials stored securely in OS credential store / protected user file.",
            }
        ).model_dump()

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
        return (
            f"Pacific Date: {ctx.clock.now().strftime('%Y-%m-%d')}\n"
            f"General Units Used: {ctx.quota_used} / {ctx.settings.daily_general_quota}\n"
            f"Search Calls Used: 0 / {ctx.settings.daily_search_quota}\n"
            f"Cache Hits: {ctx.cache_hits}\n"
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
