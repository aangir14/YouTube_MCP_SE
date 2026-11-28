"""Centralized quota estimator, atomic SQLite ledger manager, and Pacific rollover (C16).

Implements SRS FR-10.1–10.9, NFR-QUOTA-01, TQ-5, TQ-6, and TBD-11 baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from focuslist.clock import Clock, next_pacific_midnight_utc, pacific_date_for
from focuslist.config import Settings, get_settings
from focuslist.errors import (
    InvalidArgumentsError,
    QuotaBudgetExceededError,
    QuotaExhaustedError,
)
from focuslist.platform.storage import FocusListStorage

# Centralized per-method / endpoint baseline costs: (general_units, search_calls)
# Verified against YouTube Data API v3 Quota Calculator (TBD-11):
# Search calls are tracked in FocusList's 100-search daily bucket alongside general units.
METHOD_COSTS: dict[str, tuple[int, int]] = {
    "videos.list": (1, 0),
    "get_video_details": (1, 0),
    "search.list": (0, 1),
    "search_video_ids": (0, 1),
    "search_channel_ids": (0, 1),
    "search_candidates": (0, 1),
    "channels.list": (1, 0),
    "get_channel_details": (1, 0),
    "get_channels_details": (1, 0),
    "check_channel_eligibility": (1, 0),
    "owned_channel_ids": (1, 0),
    "playlistItems.list": (1, 0),
    "get_channel_upload_ids": (1, 0),
    "get_channel_recent_uploads": (1, 0),
    "get_playlist_items": (1, 0),
    "list_playlist_items_for_reconciliation": (1, 0),
    "playlists.list": (1, 0),
    "get_user_playlists": (1, 0),
    "find_created_playlist": (1, 0),
    "subscriptions.list": (1, 0),
    "get_user_subscriptions": (1, 0),
    "get_user_likes": (1, 0),
    "videoCategories.list": (1, 0),
    "get_categories": (1, 0),
    "playlists.insert": (50, 0),
    "create_playlist": (50, 0),
    "playlistItems.insert": (50, 0),
    "insert_playlist_item": (50, 0),
    "playlists.delete": (50, 0),
    "delete_playlist": (50, 0),
}

# Baseline operation ceilings from SRS Section 4.10, NFR-QUOTA-01, and Plan Section 3
OPERATION_BASELINES: dict[str, tuple[int, int]] = {
    "get_video_details": (1, 0),
    "similar_videos": (6, 2),
    "similar_channels": (25, 3),
    "recommend_videos": (40, 3),
    "analyse_engagement": (60, 0),
    "propose_playlist": (15, 3),
    "confirm_playlist": (651, 0),  # 51 + 50 * N (default N=12 per Appendix B.3)
    "resume_playlist": (2, 0),  # bounded creation marker lookup and reconciliation snapshot
    "undo_playlist": (50, 0),
    "analyse_playlist": (3, 0),  # 2 * ceil(n/50) + 1 (default n=50)
    "audit_playlist": (3, 0),  # 2 * ceil(n/50) + 1 (default n=50)
    "estimate_quota": (0, 0),
    "get_quota_status": (0, 0),
    "auth_status": (0, 0),
}

KNOWN_TOOLS = frozenset(OPERATION_BASELINES.keys())


@dataclass(frozen=True, slots=True)
class QuotaStatusSnapshot:
    """Point-in-time snapshot of the local Pacific-day quota ledger."""

    pacific_date: str
    daily_general_limit: int
    safety_margin_units: int
    effective_general_ceiling: int
    general_units_used: int
    general_units_reserved: int
    general_units_remaining: int
    effective_general_remaining: int
    daily_search_limit: int
    search_calls_used: int
    search_calls_reserved: int
    search_calls_remaining: int
    effective_searches_remaining: int
    cache_hits: int
    general_exhausted: bool
    search_exhausted: bool
    is_exhausted: bool
    request_unit_cap: int
    scheduled_live_unit_cap: int
    scheduled_live_search_cap: int
    reset_time_utc: datetime

    def to_tool_dict(self) -> dict[str, Any]:
        """Serialize to public lower_snake_case dictionary for MCP/CLI status."""
        return {
            "pacific_date": self.pacific_date,
            "daily_general_limit": self.daily_general_limit,
            "safety_margin_units": self.safety_margin_units,
            "effective_general_ceiling": self.effective_general_ceiling,
            "general_units_used": self.general_units_used,
            "general_units_reserved": self.general_units_reserved,
            "general_units_remaining": self.general_units_remaining,
            "effective_general_remaining": self.effective_general_remaining,
            "daily_search_limit": self.daily_search_limit,
            "search_calls_used": self.search_calls_used,
            "search_calls_reserved": self.search_calls_reserved,
            "search_calls_remaining": self.search_calls_remaining,
            "effective_searches_remaining": self.effective_searches_remaining,
            "cache_hits": self.cache_hits,
            "general_exhausted": self.general_exhausted,
            "search_exhausted": self.search_exhausted,
            "is_exhausted": self.is_exhausted,
            "request_unit_cap": self.request_unit_cap,
            "scheduled_live_unit_cap": self.scheduled_live_unit_cap,
            "scheduled_live_search_cap": self.scheduled_live_search_cap,
            "reset_time_utc": self.reset_time_utc.isoformat(),
            "rollover_schedule": "Midnight Pacific Time (America/Los_Angeles)",
        }


@dataclass(frozen=True, slots=True)
class OperationEstimate:
    """Local dry-run quota estimate for a target MCP tool call."""

    target_tool: str
    estimated_general_units: int
    estimated_search_calls: int
    max_units_with_retries: int
    max_searches_with_retries: int
    cache_hits: int
    feasible: bool
    reason: str
    request_unit_cap: int
    effective_general_remaining: int
    effective_searches_remaining: int

    def to_tool_dict(self) -> dict[str, Any]:
        return {
            "target_tool": self.target_tool,
            "estimated_general_units": self.estimated_general_units,
            "estimated_search_calls": self.estimated_search_calls,
            "max_units_with_retries": self.max_units_with_retries,
            "max_searches_with_retries": self.max_searches_with_retries,
            "cache_hits": self.cache_hits,
            "cache_hit_possible": True,
            "feasible": self.feasible,
            "reason": self.reason,
            "request_unit_cap": self.request_unit_cap,
            "effective_general_remaining": self.effective_general_remaining,
            "effective_searches_remaining": self.effective_searches_remaining,
        }


@dataclass
class QuotaReservation:
    """Active atomic reservation against the daily SQLite quota ledger."""

    pacific_date: str
    reserved_units: int
    reserved_searches: int
    units_remaining_reserved: int = field(init=False)
    searches_remaining_reserved: int = field(init=False)
    units_charged: int = 0
    searches_charged: int = 0
    released: bool = False

    def __post_init__(self) -> None:
        self.units_remaining_reserved = self.reserved_units
        self.searches_remaining_reserved = self.reserved_searches


class QuotaManager:
    """Enforces atomic preflight checks, reservations, attempt charges, and Pacific rollover."""

    def __init__(
        self,
        storage: FocusListStorage,
        settings: Settings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.storage = storage
        self.settings = settings or get_settings()
        self.clock: Clock = clock or storage.clock

    def _safety_margin_units(self) -> int:
        return math.ceil(self.settings.daily_general_quota * self.settings.quota_safety_margin)

    def _ensure_ledger_row(self, conn: Any, pacific_date: str, now_epoch: int) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO quota_ledger (
                pacific_date, units_used, units_reserved, searches_used,
                searches_reserved, cache_hits, general_exhausted, search_exhausted, updated_at
            ) VALUES (?, 0, 0, 0, 0, 0, 0, 0, ?)
            """,
            (pacific_date, now_epoch),
        )

    def get_status(self) -> QuotaStatusSnapshot:
        """Read current Pacific-day balances from SQLite with zero network calls."""
        now_dt = self.clock.now()
        pdate = pacific_date_for(now_dt)
        now_epoch = self.clock.now_epoch()

        with self.storage.transaction(immediate=False) as conn:
            row = conn.execute(
                "SELECT * FROM quota_ledger WHERE pacific_date = ?",
                (pdate,),
            ).fetchone()
            if row is None:
                units_used = 0
                units_reserved = 0
                searches_used = 0
                searches_reserved = 0
                cache_hits = 0
                gen_exh = False
                srch_exh = False
            else:
                units_used = int(row["units_used"])
                units_reserved = int(row["units_reserved"])
                searches_used = int(row["searches_used"])
                searches_reserved = int(row["searches_reserved"])
                cache_hits = int(row["cache_hits"])
                gen_exh = bool(row["general_exhausted"])
                srch_exh = bool(row["search_exhausted"])
                _ = now_epoch

        margin = self._safety_margin_units()
        eff_ceiling = max(0, self.settings.daily_general_quota - margin)
        gen_rem = max(0, self.settings.daily_general_quota - units_used)
        eff_gen_rem = max(0, eff_ceiling - units_used - units_reserved)
        srch_rem = max(0, self.settings.daily_search_quota - searches_used)
        eff_srch_rem = max(0, self.settings.daily_search_quota - searches_used - searches_reserved)

        return QuotaStatusSnapshot(
            pacific_date=pdate,
            daily_general_limit=self.settings.daily_general_quota,
            safety_margin_units=margin,
            effective_general_ceiling=eff_ceiling,
            general_units_used=units_used,
            general_units_reserved=units_reserved,
            general_units_remaining=gen_rem,
            effective_general_remaining=eff_gen_rem,
            daily_search_limit=self.settings.daily_search_quota,
            search_calls_used=searches_used,
            search_calls_reserved=searches_reserved,
            search_calls_remaining=srch_rem,
            effective_searches_remaining=eff_srch_rem,
            cache_hits=cache_hits,
            general_exhausted=gen_exh,
            search_exhausted=srch_exh,
            is_exhausted=gen_exh or srch_exh or eff_gen_rem == 0,
            request_unit_cap=self.settings.request_unit_cap,
            scheduled_live_unit_cap=self.settings.scheduled_live_unit_cap,
            scheduled_live_search_cap=self.settings.scheduled_live_search_cap,
            reset_time_utc=next_pacific_midnight_utc(now_dt),
        )

    def reserve(
        self,
        worst_case_units: int,
        worst_case_searches: int = 0,
        *,
        scheduled_live_mode: bool | None = None,
    ) -> QuotaReservation:
        """Atomically validate and reserve worst-case budget before outbound calls."""
        if worst_case_units < 0 or worst_case_searches < 0:
            raise InvalidArgumentsError("Quota reservation amounts must be non-negative.")

        live_cap_active = (
            self.settings.scheduled_live_mode
            if scheduled_live_mode is None
            else scheduled_live_mode
        )
        if worst_case_units > self.settings.request_unit_cap:
            raise QuotaBudgetExceededError(
                f"Operation requires {worst_case_units} general units, exceeding the "
                f"per-request cap of {self.settings.request_unit_cap} units."
            )

        now_dt = self.clock.now()
        pdate = pacific_date_for(now_dt)
        now_epoch = self.clock.now_epoch()
        eff_ceiling = max(0, self.settings.daily_general_quota - self._safety_margin_units())

        with self.storage.transaction(immediate=True) as conn:
            self._ensure_ledger_row(conn, pdate, now_epoch)
            row = conn.execute(
                "SELECT * FROM quota_ledger WHERE pacific_date = ?",
                (pdate,),
            ).fetchone()
            assert row is not None
            units_used = int(row["units_used"])
            units_reserved = int(row["units_reserved"])
            searches_used = int(row["searches_used"])
            searches_reserved = int(row["searches_reserved"])
            gen_exh = bool(row["general_exhausted"])
            srch_exh = bool(row["search_exhausted"])

            if worst_case_units > 0 and gen_exh:
                raise QuotaExhaustedError(
                    "General YouTube quota bucket is marked exhausted until midnight Pacific."
                )
            if worst_case_searches > 0 and srch_exh:
                raise QuotaExhaustedError(
                    "Search quota bucket is marked exhausted until midnight Pacific."
                )

            eff_gen_rem = max(0, eff_ceiling - units_used - units_reserved)
            eff_srch_rem = max(0, self.settings.daily_search_quota - searches_used - searches_reserved)

            if worst_case_units > eff_gen_rem:
                raise QuotaBudgetExceededError(
                    f"Operation requires {worst_case_units} units, exceeding remaining effective "
                    f"general allowance ({eff_gen_rem} units after 5% safety margin)."
                )
            if worst_case_searches > eff_srch_rem:
                raise QuotaBudgetExceededError(
                    f"Operation requires {worst_case_searches} searches, exceeding remaining "
                    f"search allowance ({eff_srch_rem} searches)."
                )

            if live_cap_active:
                if units_used + units_reserved + worst_case_units > self.settings.scheduled_live_unit_cap:
                    raise QuotaBudgetExceededError(
                        f"Scheduled live CI unit cap ({self.settings.scheduled_live_unit_cap}) exceeded."
                    )
                if (
                    searches_used + searches_reserved + worst_case_searches
                    > self.settings.scheduled_live_search_cap
                ):
                    raise QuotaBudgetExceededError(
                        f"Scheduled live CI search cap ({self.settings.scheduled_live_search_cap}) exceeded."
                    )

            conn.execute(
                """
                UPDATE quota_ledger
                SET units_reserved = units_reserved + ?,
                    searches_reserved = searches_reserved + ?,
                    updated_at = ?
                WHERE pacific_date = ?
                """,
                (worst_case_units, worst_case_searches, now_epoch, pdate),
            )

        return QuotaReservation(
            pacific_date=pdate,
            reserved_units=worst_case_units,
            reserved_searches=worst_case_searches,
        )

    def charge_attempt(
        self,
        units: int,
        searches: int = 0,
        *,
        reservation: QuotaReservation | None = None,
    ) -> None:
        """Charge an actual outbound attempt or page to the Pacific quota ledger."""
        if units < 0 or searches < 0:
            raise InvalidArgumentsError("Quota charge amounts must be non-negative.")
        if units == 0 and searches == 0:
            return

        now_epoch = self.clock.now_epoch()
        pdate = (
            reservation.pacific_date
            if reservation is not None
            else pacific_date_for(self.clock.now())
        )

        unit_rel = 0
        srch_rel = 0
        if reservation is not None and not reservation.released:
            unit_rel = min(units, reservation.units_remaining_reserved)
            srch_rel = min(searches, reservation.searches_remaining_reserved)
            reservation.units_remaining_reserved -= unit_rel
            reservation.searches_remaining_reserved -= srch_rel
            reservation.units_charged += units
            reservation.searches_charged += searches

        with self.storage.transaction(immediate=True) as conn:
            self._ensure_ledger_row(conn, pdate, now_epoch)
            conn.execute(
                """
                UPDATE quota_ledger
                SET units_used = units_used + ?,
                    units_reserved = MAX(0, units_reserved - ?),
                    searches_used = searches_used + ?,
                    searches_reserved = MAX(0, searches_reserved - ?),
                    updated_at = ?
                WHERE pacific_date = ?
                """,
                (units, unit_rel, searches, srch_rel, now_epoch, pdate),
            )

    def can_afford_retry(
        self,
        units: int,
        searches: int = 0,
        *,
        reservation: QuotaReservation | None = None,
    ) -> bool:
        """Verify atomically whether a retry attempt fits remaining cap and daily budgets."""
        now_dt = self.clock.now()
        pdate = reservation.pacific_date if reservation is not None else pacific_date_for(now_dt)
        now_epoch = self.clock.now_epoch()
        eff_ceiling = max(0, self.settings.daily_general_quota - self._safety_margin_units())

        if reservation is not None and reservation.units_charged + units > self.settings.request_unit_cap:
            return False

        with self.storage.transaction(immediate=True) as conn:
            self._ensure_ledger_row(conn, pdate, now_epoch)
            row = conn.execute(
                "SELECT * FROM quota_ledger WHERE pacific_date = ?",
                (pdate,),
            ).fetchone()
            assert row is not None
            if units > 0 and bool(row["general_exhausted"]):
                return False
            if searches > 0 and bool(row["search_exhausted"]):
                return False

            # Subtract remaining reservation from already-reserved so we don't double-count
            other_reserved_u = int(row["units_reserved"]) - (
                reservation.units_remaining_reserved if reservation else 0
            )
            other_reserved_s = int(row["searches_reserved"]) - (
                reservation.searches_remaining_reserved if reservation else 0
            )
            used_u = int(row["units_used"])
            used_s = int(row["searches_used"])

            if used_u + max(0, other_reserved_u) + units > eff_ceiling:
                return False
            if used_s + max(0, other_reserved_s) + searches > self.settings.daily_search_quota:
                return False
            if self.settings.scheduled_live_mode:
                if used_u + max(0, other_reserved_u) + units > self.settings.scheduled_live_unit_cap:
                    return False
                if used_s + max(0, other_reserved_s) + searches > self.settings.scheduled_live_search_cap:
                    return False
        return True

    def release_reservation(self, reservation: QuotaReservation | None) -> None:
        """Release any unused portion of a reservation upon completion or failure."""
        if reservation is None or reservation.released:
            return
        rem_u = reservation.units_remaining_reserved
        rem_s = reservation.searches_remaining_reserved
        reservation.units_remaining_reserved = 0
        reservation.searches_remaining_reserved = 0
        reservation.released = True
        if rem_u == 0 and rem_s == 0:
            return

        now_epoch = self.clock.now_epoch()
        with self.storage.transaction(immediate=True) as conn:
            conn.execute(
                """
                UPDATE quota_ledger
                SET units_reserved = MAX(0, units_reserved - ?),
                    searches_reserved = MAX(0, searches_reserved - ?),
                    updated_at = ?
                WHERE pacific_date = ?
                """,
                (rem_u, rem_s, now_epoch, reservation.pacific_date),
            )

    def record_cache_hit(self, count: int = 1) -> None:
        """Increment zero-cost cache hit counter in today's Pacific ledger."""
        if count <= 0:
            return
        now_dt = self.clock.now()
        pdate = pacific_date_for(now_dt)
        now_epoch = self.clock.now_epoch()
        with self.storage.transaction(immediate=True) as conn:
            self._ensure_ledger_row(conn, pdate, now_epoch)
            conn.execute(
                """
                UPDATE quota_ledger
                SET cache_hits = cache_hits + ?, updated_at = ?
                WHERE pacific_date = ?
                """,
                (count, now_epoch, pdate),
            )

    def mark_exhausted(self, bucket: Literal["general", "search", "both"]) -> None:
        """Mark general and/or search bucket exhausted for the current Pacific day."""
        pdate = pacific_date_for(self.clock.now())
        now_epoch = self.clock.now_epoch()
        gen = 1 if bucket in {"general", "both"} else 0
        srch = 1 if bucket in {"search", "both"} else 0
        with self.storage.transaction(immediate=True) as conn:
            self._ensure_ledger_row(conn, pdate, now_epoch)
            conn.execute(
                """
                UPDATE quota_ledger
                SET general_exhausted = MAX(general_exhausted, ?),
                    search_exhausted = MAX(search_exhausted, ?),
                    updated_at = ?
                WHERE pacific_date = ?
                """,
                (gen, srch, now_epoch, pdate),
            )


def estimate_operation_cost(
    target_tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
    quota_manager: QuotaManager | None = None,
    storage: FocusListStorage | None = None,
) -> OperationEstimate:
    """Compute a purely local worst-case cost and feasibility estimate with zero network calls."""
    if not isinstance(target_tool, str) or target_tool not in KNOWN_TOOLS:
        valid = ", ".join(sorted(KNOWN_TOOLS))
        raise InvalidArgumentsError(
            f"Unknown target_tool '{target_tool}'. Expected one of: {valid}."
        )
    args = arguments or {}
    if not isinstance(args, dict):
        raise InvalidArgumentsError("arguments must be a JSON object when supplied.")

    cfg = settings or (quota_manager.settings if quota_manager is not None else get_settings())
    cache_hits = 0

    if target_tool == "confirm_playlist":
        prop = None
        item_count = args.get("item_count")
        if storage is not None and isinstance(args.get("proposal_id"), str):
            prop = storage.get_proposal(args["proposal_id"])
            if prop is not None:
                item_count = len(prop.ordered_video_ids)
        if item_count is None:
            item_count = 12
        if prop is not None and prop.action_kind == "undo":
            units = 50
        elif prop is not None and prop.state == "completed":
            units = 0
        elif isinstance(item_count, bool) or not isinstance(item_count, int) or not 1 <= item_count <= 50:
            raise InvalidArgumentsError("confirm_playlist item_count must be an integer in 1..50.")
        elif prop is not None and prop.action_kind == "resume":
            units = 1 + (50 * item_count)
        else:
            units = 51 + (50 * item_count)
            if prop is not None:
                review = prop.canonical_payload.get("action", {}).get("review", {})
                units += int(review.get("estimated_scope_upgrade_cost") == 1)
        searches = 0
    elif target_tool in {"analyse_playlist", "audit_playlist"}:
        item_count = args.get("item_count", 50)
        if isinstance(item_count, bool) or not isinstance(item_count, int) or not 1 <= item_count <= 500:
            raise InvalidArgumentsError(
                f"{target_tool} item_count must be an integer in 1..500."
            )
        units = (2 * math.ceil(item_count / 50)) + 1
        searches = 0
    else:
        units, searches = OPERATION_BASELINES[target_tool]
        if target_tool == "get_video_details" and storage is not None:
            ref = args.get("video_url_or_id")
            if isinstance(ref, str) and ref:
                from focuslist.errors import InvalidVideoIdError
                from focuslist.metadata import parse_video_id

                try:
                    vid = parse_video_id(ref)
                except InvalidVideoIdError:
                    vid = ""
                if vid and storage.get_cache("video_detail", {"video_id": vid}, category="video") is not None:
                    units = 0
                    cache_hits = 1

    # Worst-case retry bound for read operations (writes never blindly retry)
    no_retry = target_tool in {"confirm_playlist", "resume_playlist", "undo_playlist"}
    retry_factor = 1 if no_retry else (1 + cfg.max_retries)
    max_units_with_retries = units * retry_factor
    max_searches_with_retries = searches * retry_factor

    if quota_manager is not None:
        snap = quota_manager.get_status()
        eff_gen = snap.effective_general_remaining
        eff_srch = snap.effective_searches_remaining
        gen_exh = snap.general_exhausted
        srch_exh = snap.search_exhausted
    else:
        margin = math.ceil(cfg.daily_general_quota * cfg.quota_safety_margin)
        eff_gen = max(0, cfg.daily_general_quota - margin)
        eff_srch = cfg.daily_search_quota
        gen_exh = False
        srch_exh = False

    feasible = True
    reason = "Within daily allowance and per-request cap."
    if units > 0 and gen_exh:
        feasible = False
        reason = "General quota bucket is marked exhausted until midnight Pacific."
    elif searches > 0 and srch_exh:
        feasible = False
        reason = "Search quota bucket is marked exhausted until midnight Pacific."
    elif units > cfg.request_unit_cap:
        feasible = False
        reason = f"Estimated units ({units}) exceed per-request cap ({cfg.request_unit_cap})."
    elif units > eff_gen:
        feasible = False
        reason = (
            f"Estimated units ({units}) exceed effective remaining allowance ({eff_gen})."
        )
    elif searches > eff_srch:
        feasible = False
        reason = (
            f"Estimated searches ({searches}) exceed remaining search allowance ({eff_srch})."
        )
    elif cfg.scheduled_live_mode and (
        units > cfg.scheduled_live_unit_cap or searches > cfg.scheduled_live_search_cap
    ):
        feasible = False
        reason = (
            f"Exceeds scheduled live CI cap ({cfg.scheduled_live_unit_cap} units, "
            f"{cfg.scheduled_live_search_cap} searches)."
        )

    return OperationEstimate(
        target_tool=target_tool,
        estimated_general_units=units,
        estimated_search_calls=searches,
        max_units_with_retries=max_units_with_retries,
        max_searches_with_retries=max_searches_with_retries,
        cache_hits=cache_hits,
        feasible=feasible,
        reason=reason,
        request_unit_cap=cfg.request_unit_cap,
        effective_general_remaining=eff_gen,
        effective_searches_remaining=eff_srch,
    )
