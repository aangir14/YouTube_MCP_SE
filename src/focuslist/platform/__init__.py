"""Platform gateway and provider abstractions for YouTube operations."""

from __future__ import annotations

from pathlib import Path

from focuslist.config import Settings, get_settings
from focuslist.platform.fault_provider import FaultInjectionProvider
from focuslist.platform.fixture_provider import FixtureVideoProvider
from focuslist.platform.live_provider import LiveVideoProvider
from focuslist.platform.provider import VideoProvider


def create_provider(
    settings: Settings | None = None,
    fixture_dir: Path | str | None = None,
) -> VideoProvider:
    """Construct the configured VideoProvider according to active settings."""
    cfg = settings or get_settings()
    mode = cfg.provider

    if mode == "fixture":
        fdir = Path(fixture_dir) if fixture_dir else cfg.fixture_dir
        return FixtureVideoProvider(fixture_dir=fdir)
    elif mode == "live":
        return LiveVideoProvider(settings=cfg)
    elif mode == "fault":
        fdir = Path(fixture_dir) if fixture_dir else cfg.fixture_dir
        base = FixtureVideoProvider(fixture_dir=fdir)
        return FaultInjectionProvider(target_provider=base)
    else:
        raise ValueError(f"Unknown provider mode: {mode}")


__all__ = [
    "FaultInjectionProvider",
    "FixtureVideoProvider",
    "LiveVideoProvider",
    "VideoProvider",
    "create_provider",
]
