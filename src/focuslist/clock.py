"""Injectable clock seam for deterministic time operations and testing."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


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
