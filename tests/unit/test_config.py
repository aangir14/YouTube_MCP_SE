"""Unit tests for configuration validation and defaults."""

import pytest
from pydantic import ValidationError

from focuslist.config import Settings, get_settings


def test_default_settings() -> None:
    """Verify default settings adhere to SRS baselines."""
    settings = Settings()
    assert settings.provider == "fixture"
    assert settings.daily_general_quota == 10000
    assert settings.daily_search_quota == 100
    assert settings.quota_safety_margin == 0.05
    assert settings.request_unit_cap == 2600
    assert settings.scheduled_live_unit_cap == 500
    assert settings.scheduled_live_search_cap == 5
    assert settings.cache_ttl_video_seconds == 86400
    assert settings.cache_ttl_user_seconds == 21600
    assert settings.cache_ttl_category_seconds == 604800
    assert settings.cache_ttl_max_seconds == 2592000
    assert settings.request_timeout_seconds == 15.0
    assert settings.max_retries == 3


def test_invalid_safety_margin() -> None:
    """Verify validation rejects safety margins outside [0.0, 0.5)."""
    with pytest.raises(ValidationError):
        Settings(quota_safety_margin=-0.1)

    with pytest.raises(ValidationError):
        Settings(quota_safety_margin=0.6)


def test_invalid_timeout() -> None:
    """Verify validation rejects non-positive timeout values."""
    with pytest.raises(ValidationError):
        Settings(request_timeout_seconds=0.0)

    with pytest.raises(ValidationError):
        Settings(request_timeout_seconds=-5.0)


def test_get_settings_singleton() -> None:
    """Verify get_settings returns consistent singleton instance."""
    s1 = get_settings(reset=True)
    s2 = get_settings()
    assert s1 is s2
