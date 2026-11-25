"""Unit tests for shared models, text sanitization, and response envelopes."""

from focuslist.types import (
    ErrorEnvelope,
    ErrorInfo,
    MetaEnvelope,
    ResultEnvelope,
    VideoRecord,
    format_duration_display,
    sanitize_untrusted_text,
)


def test_sanitize_untrusted_text() -> None:
    """Verify control characters and zero-width spaces are stripped, and long text is truncated."""
    raw = "Hello\x00World\u200b! \x1fThis is a test.\ufeff"
    cleaned = sanitize_untrusted_text(raw)
    assert "\x00" not in cleaned
    assert "\u200b" not in cleaned
    assert "\ufeff" not in cleaned
    assert cleaned == "HelloWorld! This is a test."

    # Truncation test
    long_text = "A" * 600
    truncated = sanitize_untrusted_text(long_text, max_length=500)
    assert len(truncated) == 500
    assert truncated.endswith("...")


def test_format_duration_display() -> None:
    """Verify duration display formatting adheres to UI-5 (mm:ss or h:mm:ss)."""
    assert format_duration_display(0) == "00:00"
    assert format_duration_display(45) == "00:45"
    assert format_duration_display(600) == "10:00"
    assert format_duration_display(900) == "15:00"
    assert format_duration_display(3600) == "1:00:00"
    assert format_duration_display(7325) == "2:02:05"


def test_video_record_model() -> None:
    """Verify VideoRecord construction and duration formatting property."""
    v = VideoRecord(
        video_id="syn_vid0001",
        canonical_url="https://www.youtube.com/watch?v=syn_vid0001",
        title="Recursion in Python",
        channel_id="UCsyn_chan_0000000000001",
        channel_title="Tech Academy",
        duration_seconds=900,
        duration_iso="PT15M0S",
    )
    assert v.duration_display == "15:00"
    assert v.untrusted is True


def test_result_envelope_serialization() -> None:
    """Verify ResultEnvelope conforms to SRS COM-1 to COM-4 standard JSON shape."""
    envelope = ResultEnvelope(
        result={"videos": ["syn_vid0001"]},
        meta=MetaEnvelope(
            quota_used=1,
            quota_remaining=9999,
            cache_hits=0,
            provider="fixture",
        ),
    )
    data = envelope.model_dump()
    assert "result" in data
    assert "meta" in data
    assert data["meta"]["quota_used"] == 1
    assert data["meta"]["provider"] == "fixture"


def test_error_envelope_serialization() -> None:
    """Verify ErrorEnvelope conforms to SRS UI-4 standard JSON shape."""
    envelope = ErrorEnvelope(
        error=ErrorInfo(
            code="QUOTA_BUDGET_EXCEEDED",
            message="Requested cost exceeds budget.",
            remediation="Wait for Pacific midnight reset.",
            retryable=False,
        ),
        meta=MetaEnvelope(quota_used=0, quota_remaining=50),
    )
    data = envelope.model_dump()
    assert "error" in data
    assert data["error"]["code"] == "QUOTA_BUDGET_EXCEEDED"
    assert data["error"]["retryable"] is False
