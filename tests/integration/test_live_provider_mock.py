"""Offline integration tests for LiveVideoProvider using mocked Google API service (C13)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from googleapiclient.errors import HttpError

from focuslist.config import Settings
from focuslist.context import RequestContext
from focuslist.discovery.videos import VideoDiscovery
from focuslist.errors import (
    AuthExpiredError,
    AuthRequiredError,
    ChannelUnavailableError,
    NetworkTimeoutError,
    QuotaExhaustedError,
    RateLimitedError,
    UpstreamFailureError,
    UpstreamUnavailableError,
    VideoUnavailableError,
)
from focuslist.platform.live_provider import LiveVideoProvider


class _FakeResp:
    def __init__(self, status: int, reason: str = "") -> None:
        self.status = status
        self.reason = reason


class _FakeRequest:
    def __init__(self, payload: Any = None, exc: Exception | None = None) -> None:
        self._payload = payload
        self._exc = exc

    def execute(self) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._payload


class _FakeEndpoint:
    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def list(self, **kwargs: Any) -> _FakeRequest:
        return self._handler(**kwargs)


class _FakeYouTubeService:
    def __init__(self, channel_id: str = "UC_ch_001") -> None:
        self.channel_id = channel_id
        self.video_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.channel_calls: list[dict[str, Any]] = []
        self.playlist_item_calls: list[dict[str, Any]] = []
        self.subscription_calls: list[dict[str, Any]] = []
        self.playlist_calls: list[dict[str, Any]] = []
        self.category_calls: list[dict[str, Any]] = []
        self.forced_exc: Exception | None = None
        self.raw_override: Any = None

    def videos(self) -> _FakeEndpoint:
        def _handle(**kwargs: Any) -> _FakeRequest:
            self.video_calls.append(kwargs)
            if self.forced_exc is not None:
                return _FakeRequest(exc=self.forced_exc)
            if self.raw_override is not None:
                return _FakeRequest(payload=self.raw_override)
            if kwargs.get("myRating") == "like":
                return _FakeRequest(
                    payload={
                        "items": [
                            {"id": "like_vid_001", "snippet": {"channelId": "UC_ch_001"}},
                        ],
                        "nextPageToken": None,
                    }
                )
            ids = [i for i in str(kwargs.get("id", "")).split(",") if i]
            items = []
            for vid in ids:
                if vid == "priv_vid_00":
                    items.append({"id": vid, "status": {"privacyStatus": "private"}})
                    continue
                items.append(
                    {
                        "id": vid,
                        "snippet": {
                            "title": f"Title \u200b{vid}",
                            "channelId": self.channel_id,
                            "channelTitle": "Test Channel",
                            "description": "Structured lecture.",
                            "publishedAt": "2026-05-01T10:00:00Z",
                            "tags": ["python", "cs"],
                            "categoryId": "27",
                            "defaultAudioLanguage": "en-US",
                            "liveBroadcastContent": "none",
                        },
                        "contentDetails": {
                            "duration": "PT10M",
                            "caption": "true",
                            "contentRating": {},
                        },
                        "status": {"privacyStatus": "public"},
                        "statistics": {"viewCount": "100", "likeCount": "10"},
                    }
                )
            return _FakeRequest(payload={"items": items})

        return _FakeEndpoint(_handle)

    def search(self) -> _FakeEndpoint:
        def _handle(**kwargs: Any) -> _FakeRequest:
            self.search_calls.append(kwargs)
            if self.forced_exc is not None:
                return _FakeRequest(exc=self.forced_exc)
            page_idx = len(self.search_calls)
            max_res = int(kwargs.get("maxResults", 50))
            items = [
                {"id": {"videoId": f"srch_{page_idx}_{i:04d}"}} for i in range(max_res)
            ]
            # Always emit nextPageToken to prove page/item cap stops pagination
            return _FakeRequest(payload={"items": items, "nextPageToken": f"tok_{page_idx}"})

        return _FakeEndpoint(_handle)

    def channels(self) -> _FakeEndpoint:
        def _handle(**kwargs: Any) -> _FakeRequest:
            self.channel_calls.append(kwargs)
            if self.forced_exc is not None:
                return _FakeRequest(exc=self.forced_exc)
            return _FakeRequest(
                payload={
                    "items": [
                        {
                            "id": self.channel_id,
                            "snippet": {
                                "title": "Test Channel",
                                "customUrl": "@testchan",
                                "description": "Educational CS.",
                                "defaultLanguage": "en",
                            },
                            "statistics": {
                                "subscriberCount": "999",
                                "hiddenSubscriberCount": True,
                                "videoCount": "42",
                            },
                            "topicDetails": {"topicCategories": ["https://en.wikipedia.org/wiki/CS"]},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU_ch_001"}},
                        }
                    ]
                }
            )

        return _FakeEndpoint(_handle)

    def playlistItems(self) -> _FakeEndpoint:
        def _handle(**kwargs: Any) -> _FakeRequest:
            self.playlist_item_calls.append(kwargs)
            return _FakeRequest(
                payload={"items": [{"contentDetails": {"videoId": "upl_vid_001"}}]}
            )

        return _FakeEndpoint(_handle)

    def subscriptions(self) -> _FakeEndpoint:
        def _handle(**kwargs: Any) -> _FakeRequest:
            self.subscription_calls.append(kwargs)
            return _FakeRequest(
                payload={
                    "items": [
                        {
                            "snippet": {
                                "resourceId": {"channelId": "UC_sub_001"},
                                "publishedAt": "2026-04-01T00:00:00Z",
                            }
                        }
                    ]
                }
            )

        return _FakeEndpoint(_handle)

    def playlists(self) -> _FakeEndpoint:
        def _handle(**kwargs: Any) -> _FakeRequest:
            self.playlist_calls.append(kwargs)
            return _FakeRequest(
                payload={
                    "items": [
                        {
                            "id": "PL_own_001",
                            "snippet": {"title": "My List"},
                            "contentDetails": {"itemCount": 3},
                            "status": {"privacyStatus": "private"},
                        }
                    ]
                }
            )

        return _FakeEndpoint(_handle)

    def videoCategories(self) -> _FakeEndpoint:
        def _handle(**kwargs: Any) -> _FakeRequest:
            self.category_calls.append(kwargs)
            return _FakeRequest(
                payload={"items": [{"id": "27", "snippet": {"title": "Education"}}]}
            )

        return _FakeEndpoint(_handle)


def _http_error(status: int, reason: str = "") -> HttpError:
    body = json.dumps(
        {"error": {"code": status, "errors": [{"reason": reason}], "message": "raw secret body"}}
    ).encode("utf-8")
    return HttpError(_FakeResp(status, reason), body)


def test_live_provider_requires_auth_when_no_credentials() -> None:
    provider = LiveVideoProvider()
    with pytest.raises(AuthRequiredError):
        provider.get_video_details(["vid_1234567"])


def test_live_provider_batching_sanitization_and_private_filtering() -> None:
    svc = _FakeYouTubeService()
    observed: list[tuple[str, int]] = []
    provider = LiveVideoProvider(
        service=svc,
        attempt_observer=lambda ep, n: observed.append((ep, n)),
    )

    ids = [f"vid_{i:07d}" for i in range(60)] + ["priv_vid_00", "vid_0000000"]
    videos = provider.get_video_details(ids)

    # 61 unique IDs -> 2 batched videos.list calls (50 + 11), private item dropped
    assert len(svc.video_calls) == 2
    assert len(videos) == 60
    assert videos[0].duration_seconds == 600
    assert videos[0].language == "en-us"
    assert videos[0].untrusted is True
    assert "\u200b" not in videos[0].title
    assert provider.network_attempts == 2
    assert observed == [("videos.list", 1), ("videos.list", 1)]


def test_live_provider_search_caps_pages_even_with_next_page_token() -> None:
    svc = _FakeYouTubeService()
    provider = LiveVideoProvider(service=svc)

    results = provider.search_candidates("recursion", max_results=75)
    # 75 items -> 2 search pages (50 + 25), then 2 batched detail calls (50 + 25)
    assert len(svc.search_calls) == 2
    assert len(svc.video_calls) == 2
    assert len(results) == 75
    assert provider.network_attempts == 4


def test_fr1_uses_two_search_pages_and_six_general_units_on_mock_transport() -> None:
    service = _FakeYouTubeService(channel_id="UC" + "a" * 22)
    provider = LiveVideoProvider(service=service)
    discovery = VideoDiscovery(provider, RequestContext(settings=Settings(provider="live")))

    response = discovery.tool_response(lambda: discovery.similar("seed_vid001", limit=50))

    assert response["result"]["candidate_count"] == 101
    assert response["result"]["eligible_count"] == 101
    assert response["result"]["count"] == 50
    assert response["meta"]["quota_used"] == 6
    assert response["meta"]["search_calls"] == 2
    assert [call["maxResults"] for call in service.search_calls] == [50, 50]
    assert all("pageToken" not in call for call in service.search_calls)
    assert len(service.channel_calls) == len(service.playlist_item_calls) == 1
    assert [len(call["id"].split(",")) for call in service.video_calls] == [1, 50, 50, 1]
    assert provider.network_attempts == 8


def test_live_provider_channel_account_and_categories_parity() -> None:
    svc = _FakeYouTubeService()
    provider = LiveVideoProvider(service=svc)

    ch = provider.get_channel_details(handle="@testchan")
    assert ch is not None
    assert ch.channel_id == "UC_ch_001"
    assert ch.subscriber_count is None  # hiddenSubscriberCount=True respected

    uploads = provider.get_channel_recent_uploads("UC_ch_001", max_results=10)
    assert len(uploads) == 1 and uploads[0].video_id == "upl_vid_001"

    likes = provider.get_user_likes("acc_1", max_results=10)
    assert len(likes) == 1 and likes[0].timestamp_provenance == "unknown"

    subs = provider.get_user_subscriptions("acc_1", max_results=10)
    assert len(subs) == 1 and subs[0].timestamp_provenance == "genuine"

    playlists = provider.get_user_playlists("acc_1", max_results=10)
    assert playlists[0]["playlist_id"] == "PL_own_001"

    cats = provider.get_categories("US")
    assert cats == [{"id": "27", "title": "Education"}]

    assert provider.check_channel_eligibility("acc_1") is True


@pytest.mark.parametrize(
    ("exc", "expected_cls", "is_channel"),
    [
        (_http_error(401, "authError"), AuthExpiredError, False),
        (_http_error(403, "quotaExceeded"), QuotaExhaustedError, False),
        (_http_error(403, "rateLimitExceeded"), RateLimitedError, False),
        (_http_error(403, "forbidden"), AuthRequiredError, False),
        (_http_error(404, "notFound"), VideoUnavailableError, False),
        (_http_error(404, "notFound"), ChannelUnavailableError, True),
        (_http_error(429, "tooManyRequests"), RateLimitedError, False),
        (_http_error(500, "backendError"), UpstreamFailureError, False),
        (_http_error(503, "serviceUnavailable"), UpstreamUnavailableError, False),
        (TimeoutError("timed out"), NetworkTimeoutError, False),
    ],
)
def test_live_provider_safe_error_mapping_without_raw_bodies(
    exc: Exception,
    expected_cls: type[Exception],
    is_channel: bool,
) -> None:
    svc = _FakeYouTubeService()
    svc.forced_exc = exc
    provider = LiveVideoProvider(service=svc)

    with pytest.raises(expected_cls) as exc_info:
        if is_channel:
            provider.get_channel_details(channel_id="UC_ch_001")
        else:
            provider.get_video_details(["vid_1234567"])

    assert "raw secret body" not in str(exc_info.value)


def test_live_provider_rejects_malformed_response_payload() -> None:
    svc = _FakeYouTubeService()
    svc.raw_override = ["not", "a", "dict"]
    provider = LiveVideoProvider(service=svc)

    with pytest.raises(UpstreamFailureError):
        provider.get_video_details(["vid_1234567"])
