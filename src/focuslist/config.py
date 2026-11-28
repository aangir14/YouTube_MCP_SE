"""Configuration management and central defaults for FocusList."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from focuslist.ranking_weights import DEFAULT_SCORING_WEIGHTS

ProviderMode = Literal["fixture", "live", "fault"]


class Settings(BaseSettings):
    """Central configuration for FocusList MCP server and CLI."""

    model_config = SettingsConfigDict(
        env_prefix="FOCUSLIST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provider Mode: default to safe offline fixture mode for dev and CI
    provider: ProviderMode = Field(
        default="fixture",
        description="Active provider backend: 'fixture' (offline), 'live' (official API), 'fault' (testing)",
    )

    # Database & Storage
    db_path: Path = Field(
        default=Path("focuslist.db"),
        description="Path to SQLite database file (WAL mode with foreign keys)",
    )
    fixture_dir: Path = Field(
        default=Path("tests/fixtures"),
        description="Directory containing synthetic JSON replay fixtures",
    )

    scoring_weights: dict[str, dict[str, float]] = Field(default_factory=dict)

    # Quota Limits & Safety Margin (SRS FR-10, NFR-QUOTA-01)
    daily_general_quota: int = Field(
        default=10000,
        ge=1,
        description="Daily general quota units allocation (baseline 10,000 units/day)",
    )
    daily_search_quota: int = Field(
        default=100,
        ge=1,
        description="Daily search requests allocation (baseline 100 searches/day)",
    )
    quota_safety_margin: float = Field(
        default=0.05,
        ge=0.0,
        lt=0.5,
        description="Safety margin buffer (default 5% / 500 units retained)",
    )
    request_unit_cap: int = Field(
        default=2600,
        ge=1,
        description="Maximum general units permitted in a single tool operation",
    )
    scheduled_live_unit_cap: int = Field(
        default=500,
        ge=1,
        description="Enforced quota ceiling for scheduled live smoke CI runs",
    )
    scheduled_live_search_cap: int = Field(
        default=5,
        ge=1,
        description="Enforced search ceiling for scheduled live smoke CI runs",
    )

    # Cache Lifetimes in Seconds (SRS FR-11.4)
    cache_ttl_video_seconds: int = Field(
        default=86400,  # 24 hours
        ge=60,
        description="Cache TTL for public video and channel metadata",
    )
    cache_ttl_user_seconds: int = Field(
        default=21600,  # 6 hours
        ge=60,
        description="Cache TTL for authorized user likes, subscriptions, playlists",
    )
    cache_ttl_category_seconds: int = Field(
        default=604800,  # 7 days
        ge=3600,
        description="Cache TTL for YouTube category taxonomy",
    )
    cache_ttl_max_seconds: int = Field(
        default=2592000,  # 30 days
        ge=86400,
        description="Hard maximum retention for any cached record",
    )

    # Network & Timeouts (SRS COM-5)
    request_timeout_seconds: float = Field(
        default=15.0,
        gt=0.0,
        description="Default HTTP request timeout in seconds (COM-5 standard)",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Maximum retry attempts for transient 5xx or network errors",
    )

    # OAuth & Security Storage Settings (SRS FR-9.2, FR-9.4)
    oauth_client_file: Path | None = Field(
        default=None,
        description="Path to client_secret.json (loaded externally, never committed)",
    )
    auth_store_dir: Path | None = Field(
        default=None,
        description="Optional override for user-only credential and signing-key directory",
    )

    # Gateway & CI Guards
    cache_enabled: bool = Field(
        default=True,
        description="Enable SQLite response caching in ProviderGateway",
    )
    scheduled_live_mode: bool = Field(
        default=False,
        description="Enforce scheduled live CI caps (500 general units, 5 searches)",
    )

    # Diagnostics & Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR",
    )

    @field_validator("quota_safety_margin")
    @classmethod
    def validate_margin(cls, v: float) -> float:
        if not (0.0 <= v < 0.5):
            raise ValueError("quota_safety_margin must be between 0.0 and 0.5")
        return v

    @field_validator("scoring_weights", mode="before")
    @classmethod
    def validate_scoring_weights(cls, supplied: object) -> dict[str, dict[str, float]]:
        if not isinstance(supplied, dict) or supplied.keys() - DEFAULT_SCORING_WEIGHTS.keys():
            raise ValueError("Scoring weights must use the named FocusList rankers.")
        active = {ranker: dict(weights) for ranker, weights in DEFAULT_SCORING_WEIGHTS.items()}
        for ranker, weights in supplied.items():
            if not isinstance(weights, dict) or weights.keys() != active[ranker].keys():
                raise ValueError(f"Supply every named feature for {ranker}.")
            if any(type(value) not in (int, float) or not 0 <= value <= 1
                   for value in weights.values()) or not math.isclose(
                math.fsum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-12,
            ):
                raise ValueError(f"Weights for {ranker} must be in [0, 1] and sum to one.")
            active[ranker] = {name: float(weights[name]) for name in active[ranker]}
        return active


_default_settings: Settings | None = None


def get_settings(reset: bool = False) -> Settings:
    """Acquire the central application settings singleton."""
    global _default_settings
    if _default_settings is None or reset:
        _default_settings = Settings()
    return _default_settings
