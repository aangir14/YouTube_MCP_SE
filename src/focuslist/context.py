"""Execution context for FocusList tool and CLI operations."""

from __future__ import annotations

import uuid
from typing import Any

from focuslist.clock import Clock, SystemClock
from focuslist.config import Settings, get_settings
from focuslist.errors import FocusListError
from focuslist.types import ErrorEnvelope, ErrorInfo, MetaEnvelope, ResultEnvelope


class RequestContext:
    """Execution context injected into MCP handlers and CLI commands."""

    def __init__(
        self,
        settings: Settings | None = None,
        clock: Clock | None = None,
        account_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.clock = clock or SystemClock()
        self.account_id = account_id
        self.request_id = request_id or str(uuid.uuid4())
        self.quota_used = 0
        self.cache_hits = 0
        self.warnings: list[str] = []

    def record_quota_charge(self, units: int) -> None:
        """Record outbound quota units consumed during this operation."""
        self.quota_used += units

    def record_cache_hit(self, count: int = 1) -> None:
        """Record cache hits that incurred zero quota."""
        self.cache_hits += count

    def add_warning(self, warning: str) -> None:
        """Add an operational or low-confidence warning."""
        self.warnings.append(warning)

    def create_meta_envelope(self) -> MetaEnvelope:
        """Produce the MetaEnvelope snapshot for the current request context."""
        remaining = max(0, self.settings.daily_general_quota - self.quota_used)
        return MetaEnvelope(
            quota_used=self.quota_used,
            quota_remaining=remaining,
            cache_hits=self.cache_hits,
            provider=self.settings.provider,
            warnings=list(self.warnings),
        )

    def success(self, result: Any) -> ResultEnvelope:
        """Wrap result in a standard ResultEnvelope."""
        return ResultEnvelope(
            result=result,
            meta=self.create_meta_envelope(),
        )

    def failure(self, error: Exception) -> ErrorEnvelope:
        """Wrap exception in a standard ErrorEnvelope with stable error codes."""
        if isinstance(error, FocusListError):
            err_info = ErrorInfo(
                code=error.code.value,
                message=error.message,
                remediation=error.remediation,
                retryable=error.retryable,
                details=error.details,
            )
        else:
            err_info = ErrorInfo(
                code="UPSTREAM_FAILURE",
                message=str(error) or "An internal error occurred.",
                remediation="Review system logs or retry with valid arguments.",
                retryable=False,
            )
        return ErrorEnvelope(
            error=err_info,
            meta=self.create_meta_envelope(),
        )
