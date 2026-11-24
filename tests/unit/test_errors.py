"""Unit tests for tool error registry and domain exceptions."""

from focuslist.context import RequestContext
from focuslist.errors import (
    ERROR_REGISTRY,
    ErrorCode,
    InvalidVideoIdError,
    QuotaBudgetExceededError,
)


def test_all_error_codes_registered() -> None:
    """Verify every ErrorCode has default message, remediation, and retryable flag."""
    for code in ErrorCode:
        assert code in ERROR_REGISTRY
        msg, remediation, retryable = ERROR_REGISTRY[code]
        assert isinstance(msg, str) and len(msg) > 0
        assert isinstance(remediation, str) and len(remediation) > 0
        assert isinstance(retryable, bool)


def test_focuslist_error_properties() -> None:
    """Verify FocusListError properties and to_dict serialization."""
    err = QuotaBudgetExceededError(details={"attempted_units": 3000})
    assert err.code == ErrorCode.QUOTA_BUDGET_EXCEEDED
    assert err.retryable is False
    assert "attempted_units" in err.details

    d = err.to_dict()
    assert d["code"] == "QUOTA_BUDGET_EXCEEDED"
    assert d["retryable"] is False
    assert d["details"]["attempted_units"] == 3000


def test_request_context_failure_envelope(request_context: RequestContext) -> None:
    """Verify RequestContext.failure wraps domain error into standard ErrorEnvelope."""
    err = InvalidVideoIdError("Malformed video URL passed.")
    envelope = request_context.failure(err)
    data = envelope.model_dump()
    assert data["error"]["code"] == "INVALID_VIDEO_ID"
    assert data["error"]["message"] == "Malformed video URL passed."
    assert data["error"]["retryable"] is False
    assert data["meta"]["provider"] == "fixture"
