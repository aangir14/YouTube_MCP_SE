"""Unit tests for injectable clock implementations."""

from datetime import UTC, datetime, timedelta

from focuslist.clock import FakeClock, SystemClock


def test_system_clock() -> None:
    """Verify SystemClock returns current timezone-aware UTC datetime and positive epoch."""
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.tzinfo == UTC
    assert clock.now_epoch() > 1700000000


def test_fake_clock_advancement() -> None:
    """Verify FakeClock advances deterministically."""
    init_time = datetime(2026, 11, 23, 10, 0, 0, tzinfo=UTC)
    clock = FakeClock(init_time)
    assert clock.now() == init_time
    assert clock.now_epoch() == int(init_time.timestamp())

    # Advance 90 seconds
    clock.advance(90)
    assert clock.now() == datetime(2026, 11, 23, 10, 1, 30, tzinfo=UTC)
    assert clock.now_epoch() == int(init_time.timestamp()) + 90

    # Advance using timedelta
    clock.advance(timedelta(hours=2))
    assert clock.now() == datetime(2026, 11, 23, 12, 1, 30, tzinfo=UTC)


def test_fake_clock_set_time() -> None:
    """Verify FakeClock can be set to explicit timestamps."""
    clock = FakeClock()
    target = datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC)
    clock.set_time(target)
    assert clock.now() == target
