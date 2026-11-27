"""Injectable clock seam for deterministic time operations and testing."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class _UsPacificTz(tzinfo):
    """Portable US Pacific (PST/PDT) tzinfo fallback when system tzdata is absent."""

    @staticmethod
    def _dst_bounds_local(year: int) -> tuple[datetime, datetime]:
        # 2nd Sunday of March at 02:00 local wall time
        march_1 = datetime(year, 3, 1)
        days_to_first_sun = (6 - march_1.weekday()) % 7
        dst_start = march_1 + timedelta(days=days_to_first_sun + 7, hours=2)

        # 1st Sunday of November at 02:00 local wall time
        nov_1 = datetime(year, 11, 1)
        days_to_first_nov_sun = (6 - nov_1.weekday()) % 7
        dst_end = nov_1 + timedelta(days=days_to_first_nov_sun, hours=2)
        return dst_start, dst_end

    def _is_dst(self, dt: datetime) -> bool:
        # Compute strictly from naive wall-clock fields to avoid recursive utcoffset calls
        wall = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
        start, end = self._dst_bounds_local(wall.year)
        if getattr(dt, "fold", 0) == 1 and (end - timedelta(hours=1)) <= wall < end:
            return False
        return start <= wall < end

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(hours=-8)
        return timedelta(hours=-7 if self._is_dst(dt) else -8)

    def dst(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        return timedelta(hours=1 if self._is_dst(dt) else 0)

    def tzname(self, dt: datetime | None) -> str:
        if dt is None:
            return "PST"
        return "PDT" if self._is_dst(dt) else "PST"


def _resolve_pacific_tz() -> tzinfo:
    try:
        return ZoneInfo("America/Los_Angeles")
    except ZoneInfoNotFoundError:
        return _UsPacificTz()


PACIFIC_TZ: tzinfo = _resolve_pacific_tz()


def pacific_date_for(dt: datetime) -> str:
    """Return YYYY-MM-DD in America/Los_Angeles for a UTC/aware datetime."""
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return aware.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d")


def next_pacific_midnight_utc(dt: datetime) -> datetime:
    """Return the exact UTC timestamp of the next midnight in America/Los_Angeles."""
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    local = aware.astimezone(PACIFIC_TZ)
    next_day = (local + timedelta(days=1)).date()
    midnight_naive = datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0)
    # Build aware Pacific midnight handling both ZoneInfo and fallback tzinfo
    if isinstance(PACIFIC_TZ, ZoneInfo):
        return midnight_naive.replace(tzinfo=PACIFIC_TZ).astimezone(UTC)
    # Resolve exact offset at local midnight (00:00 is outside 01:00-03:00 DST fold/gap)
    probe_utc = midnight_naive.replace(tzinfo=UTC) + timedelta(hours=8)
    offset = PACIFIC_TZ.utcoffset(probe_utc) or timedelta(hours=-8)
    return (midnight_naive - offset).replace(tzinfo=UTC)


@runtime_checkable
class Clock(Protocol):
    """Protocol for time acquisition, allowing dependency injection for deterministic testing."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC datetime."""
        ...

    def now_epoch(self) -> int:
        """Return the current Unix timestamp in integer seconds."""
        ...


class SystemClock:
    """Production clock using real system wall time."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def now_epoch(self) -> int:
        return int(time.time())


class FakeClock:
    """Deterministic clock for automated tests, simulations, and reproducible benchmarks."""

    def __init__(self, initial_time: datetime | None = None) -> None:
        if initial_time is None:
            self._current_time = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)
        else:
            if initial_time.tzinfo is None:
                self._current_time = initial_time.replace(tzinfo=UTC)
            else:
                self._current_time = initial_time.astimezone(UTC)

    def now(self) -> datetime:
        return self._current_time

    def now_epoch(self) -> int:
        return int(self._current_time.timestamp())

    def advance(self, delta: float | timedelta) -> datetime:
        """Advance the simulated clock by the specified seconds or timedelta."""
        if isinstance(delta, (int, float)):
            delta = timedelta(seconds=delta)
        self._current_time += delta
        return self._current_time

    def set_time(self, new_time: datetime) -> None:
        """Explicitly set the simulated clock to a given timestamp."""
        if new_time.tzinfo is None:
            self._current_time = new_time.replace(tzinfo=UTC)
        else:
            self._current_time = new_time.astimezone(UTC)
