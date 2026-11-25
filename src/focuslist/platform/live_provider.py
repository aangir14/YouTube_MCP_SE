"""Live official YouTube Data API v3 provider implementation (SRS FR-11.1–FR-11.3, C13)."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from focuslist.config import Settings, get_settings
from focuslist.errors import (
    AuthExpiredError,
    AuthRequiredError,
    ChannelUnavailableError,
    FocusListError,
    NetworkTimeoutError,
    QuotaExhaustedError,
    RateLimitedError,
    UpstreamFailureError,
    UpstreamUnavailableError,
    VideoUnavailableError,
)
from focuslist.metadata import (
    format_duration_iso,
    normalise_activity_record,
    normalise_channel_record,
    normalise_video_record,
    parse_duration_seconds,
    parse_utc_datetime,
    select_video_language,
)
from focuslist.platform.provider import VideoProvider
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    VideoRecord,
    sanitize_untrusted_text,
)

_MAX_BATCH_SIZE = 50
_DEFAULT_PAGE_CAP = 5


def _safe_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = int(value)
        return num if num >= 0 else None
    except (TypeError, ValueError):
        return None


def _parse_optional_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_utc_datetime(value)
    except FocusListError:
        return None


def _extract_http_error_info(exc: Any) -> tuple[int | None, str]:
    """Extract status code and error reason safely without exposing raw response bodies."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = ""
    content = getattr(exc, "content", None)
    if isinstance(content, (bytes, bytearray)):
        try:
            payload = json.loads(content.decode("utf-8", errors="ignore"))
            errors = payload.get("error", {}).get("errors", [])
            if errors and isinstance(errors, list) and isinstance(errors[0], dict):
                reason = str(errors[0].get("reason", ""))
        except (ValueError, TypeError, AttributeError):
            reason = ""
    return status, reason


class LiveVideoProvider(VideoProvider):
    """Official YouTube Data API v3 read-only adapter (C13).

    Confines all Google client library imports strictly to this module.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        credentials: Any | None = None,
        credential_provider: Callable[[], Any] | None = None,
        http_transport: Any | None = None,
        service: Any | None = None,
        attempt_observer: Callable[[str, int], None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._credentials = credentials
        self._credential_provider = credential_provider
        self._http_transport = http_transport
        self._service = service
        self._attempt_observer = attempt_observer

        self.call_counts: dict[str, int] = defaultdict(int)
        self.requests: int = 0
        self.network_attempts: int = 0

        # Confined imports: verified at initialization
        try:
            import google.auth  # noqa: F401
            import googleapiclient.discovery
            import googleapiclient.errors  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                f"Google API client libraries are required for LiveVideoProvider: {e}"
            ) from e

    def _build_verified_http(self, credentials: Any) -> Any:
        """Construct an authorized HTTPS transport with verified TLS and shared timeout."""
        if self._http_transport is not None:
            return self._http_transport
        import google_auth_httplib2
        import httplib2

        base_http = httplib2.Http(
            timeout=self.settings.request_timeout_seconds,
            disable_ssl_certificate_validation=False,
        )
        return google_auth_httplib2.AuthorizedHttp(credentials, http=base_http)

    def _ensure_service(self) -> Any:
        """Resolve injected credentials/service or raise AuthRequiredError."""
        if self._service is not None:
            return self._service

        if self._credentials is None and self._credential_provider is not None:
            self._credentials = self._credential_provider()

        if self._credentials is None:
            raise AuthRequiredError(
                "Live YouTube operations require an authorized Google account. "
                "Run 'focuslist auth login' to authenticate, or switch to fixture mode."
            )

        import googleapiclient.discovery

        http = self._build_verified_http(self._credentials)
        self._service = googleapiclient.discovery.build(
            "youtube", "v3", http=http, cache_discovery=False
        )
        return self._service

    def _execute_request(
        self,
        endpoint_name: str,
        request_obj: Any,
        *,
        is_channel: bool = False,
    ) -> dict[str, Any]:
        """Execute a single Google API request, recording attempt and mapping errors safely."""
        from googleapiclient.errors import HttpError

        self.network_attempts += 1
        if self._attempt_observer is not None:
            self._attempt_observer(endpoint_name, 1)

        try:
            response = request_obj.execute()
        except TimeoutError as exc:
            raise NetworkTimeoutError(
                f"YouTube API request to '{endpoint_name}' timed out."
            ) from exc
        except HttpError as exc:
            status, reason = _extract_http_error_info(exc)
            if status == 401:
                raise AuthExpiredError(
                    "OAuth access token was rejected (HTTP 401). Re-authenticate."
                ) from exc
            if status == 403:
                if reason in {"quotaExceeded", "dailyLimitExceeded"}:
                    raise QuotaExhaustedError(
                        "YouTube Data API daily quota exhausted (HTTP 403)."
                    ) from exc
                if reason in {"rateLimitExceeded", "userRateLimitExceeded"}:
                    raise RateLimitedError(
                        "YouTube Data API rate limit exceeded (HTTP 403)."
                    ) from exc
                raise AuthRequiredError(
                    "YouTube Data API access forbidden for current credentials (HTTP 403)."
                ) from exc
            if status == 404:
                if is_channel:
                    raise ChannelUnavailableError(
                        "Requested YouTube channel was not found (HTTP 404)."
                    ) from exc
                raise VideoUnavailableError(
                    "Requested YouTube resource was not found (HTTP 404)."
                ) from exc
            if status == 429:
                raise RateLimitedError("YouTube Data API rate limit exceeded (HTTP 429).") from exc
            if status == 503:
                raise UpstreamUnavailableError(
                    "YouTube Data API service temporarily unavailable (HTTP 503)."
                ) from exc
            raise UpstreamFailureError(
                f"YouTube Data API returned an upstream error (HTTP {status or 'unknown'})."
            ) from exc
        except FocusListError:
            raise
        except Exception as exc:
            raise UpstreamFailureError(
                f"Unexpected failure executing YouTube API '{endpoint_name}'."
            ) from exc

        if not isinstance(response, dict):
            raise UpstreamFailureError(
                f"Malformed response payload from YouTube API '{endpoint_name}'."
            )
        return response

    def _map_video_item(self, item: dict[str, Any]) -> VideoRecord | None:
        """Map a YouTube `videos.list` item into a normalized VideoRecord."""
        vid = item.get("id")
        if isinstance(vid, dict):
            vid = vid.get("videoId")
        if not isinstance(vid, str) or not vid:
            return None

        snippet = item.get("snippet") or {}
        content = item.get("contentDetails") or {}
        status = item.get("status") or {}
        stats = item.get("statistics") or {}

        # Private/deleted placeholders lack usable public status
        privacy = status.get("privacyStatus")
        if privacy in {"private", "deleted"}:
            return None

        dur_iso_raw = content.get("duration")
        dur_seconds: int | None = None
        if isinstance(dur_iso_raw, str) and dur_iso_raw:
            try:
                dur_seconds = parse_duration_seconds(dur_iso_raw)
            except FocusListError:
                dur_seconds = None

        live_flag = snippet.get("liveBroadcastContent", "none")
        lang, lang_prov = select_video_language(
            snippet.get("defaultAudioLanguage"),
            snippet.get("defaultLanguage"),
        )
        caption_raw = content.get("caption")
        has_captions = (
            True if caption_raw == "true" else (False if caption_raw == "false" else None)
        )
        age_restricted = (
            (content.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted"
        )

        record = VideoRecord(
            video_id=vid,
            canonical_url=f"https://www.youtube.com/watch?v={vid}",
            title=sanitize_untrusted_text(snippet.get("title") or ""),
            channel_id=str(snippet.get("channelId") or ""),
            channel_title=sanitize_untrusted_text(snippet.get("channelTitle") or ""),
            description=sanitize_untrusted_text(snippet.get("description") or ""),
            published_at=_parse_optional_utc(snippet.get("publishedAt")),
            duration_seconds=dur_seconds,
            duration_iso=format_duration_iso(dur_seconds) if dur_seconds is not None else None,
            tags=snippet.get("tags"),
            category_id=snippet.get("categoryId"),
            language=lang,
            language_provenance=lang_prov,
            is_live=live_flag == "live",
            is_upcoming=live_flag == "upcoming",
            is_age_restricted=age_restricted,
            has_captions=has_captions,
            view_count=_safe_int(stats.get("viewCount")),
            like_count=_safe_int(stats.get("likeCount")),
            untrusted=True,
        )
        return normalise_video_record(record)

    def get_video_details(self, video_ids: list[str]) -> list[VideoRecord]:
        self.call_counts["get_video_details"] += 1
        self.requests += 1
        service = self._ensure_service()

        deduped = list(dict.fromkeys(vid for vid in video_ids if vid))
        results: list[VideoRecord] = []
        for start in range(0, len(deduped), _MAX_BATCH_SIZE):
            batch = deduped[start : start + _MAX_BATCH_SIZE]
            req = service.videos().list(
                part="snippet,contentDetails,status,statistics",
                id=",".join(batch),
                maxResults=len(batch),
            )
            resp = self._execute_request("videos.list", req)
            for item in resp.get("items", []):
                if isinstance(item, dict):
                    mapped = self._map_video_item(item)
                    if mapped is not None:
                        results.append(mapped)
        return results

    def search_candidates(self, query: str, max_results: int = 50) -> list[VideoRecord]:
        self.call_counts["search_candidates"] += 1
        self.requests += 1
        service = self._ensure_service()

        cap = max(1, min(max_results, 150))
        collected_ids: list[str] = []
        page_token: str | None = None
        pages_used = 0
        max_pages = max(1, (cap + _MAX_BATCH_SIZE - 1) // _MAX_BATCH_SIZE)

        while len(collected_ids) < cap and pages_used < max_pages:
            page_size = min(_MAX_BATCH_SIZE, cap - len(collected_ids))
            kwargs: dict[str, Any] = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": page_size,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._execute_request("search.list", service.search().list(**kwargs))
            pages_used += 1
            for item in resp.get("items", []):
                vid = (item.get("id") or {}).get("videoId") if isinstance(item, dict) else None
                if isinstance(vid, str) and vid and vid not in collected_ids:
                    collected_ids.append(vid)
                    if len(collected_ids) >= cap:
                        break
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        if not collected_ids:
            return []
        return self.get_video_details(collected_ids)

    def get_channel_details(
        self,
        channel_id: str | None = None,
        handle: str | None = None,
    ) -> ChannelRecord | None:
        self.call_counts["get_channel_details"] += 1
        self.requests += 1
        service = self._ensure_service()

        kwargs: dict[str, Any] = {"part": "snippet,statistics,topicDetails"}
        if channel_id:
            kwargs["id"] = channel_id
        elif handle:
            kwargs["forHandle"] = handle if handle.startswith("@") else f"@{handle}"
        else:
            return None

        resp = self._execute_request(
            "channels.list", service.channels().list(**kwargs), is_channel=True
        )
        items = resp.get("items", [])
        if not items or not isinstance(items[0], dict):
            return None

        item = items[0]
        cid = str(item.get("id") or "")
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        topics = (item.get("topicDetails") or {}).get("topicCategories") or []
        hidden = bool(stats.get("hiddenSubscriberCount", False))

        record = ChannelRecord(
            channel_id=cid,
            canonical_url=f"https://www.youtube.com/channel/{cid}",
            title=sanitize_untrusted_text(snippet.get("title") or ""),
            handle=snippet.get("customUrl"),
            description=snippet.get("description"),
            language=snippet.get("defaultLanguage"),
            language_provenance="metadata" if snippet.get("defaultLanguage") else "unknown",
            topic_categories=[str(t) for t in topics],
            subscriber_count=None if hidden else _safe_int(stats.get("subscriberCount")),
            video_count=_safe_int(stats.get("videoCount")),
            hidden_subscriber_count=hidden,
            untrusted=True,
        )
        return normalise_channel_record(record)

    def get_channel_recent_uploads(
        self,
        channel_id: str,
        max_results: int = 20,
    ) -> list[VideoRecord]:
        self.call_counts["get_channel_recent_uploads"] += 1
        self.requests += 1
        service = self._ensure_service()

        ch_resp = self._execute_request(
            "channels.list",
            service.channels().list(part="contentDetails", id=channel_id),
            is_channel=True,
        )
        items = ch_resp.get("items", [])
        if not items:
            return []
        uploads_id = (
            ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        )
        if not uploads_id:
            return []

        cap = max(1, min(max_results, _MAX_BATCH_SIZE))
        pl_resp = self._execute_request(
            "playlistItems.list",
            service.playlistItems().list(
                part="snippet,contentDetails", playlistId=uploads_id, maxResults=cap
            ),
        )
        video_ids = [
            str(it.get("contentDetails", {}).get("videoId") or "")
            for it in pl_resp.get("items", [])
            if isinstance(it, dict)
        ]
        video_ids = [vid for vid in video_ids if vid][:cap]
        if not video_ids:
            return []
        return self.get_video_details(video_ids)

    def get_user_likes(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self.call_counts["get_user_likes"] += 1
        self.requests += 1
        service = self._ensure_service()

        cap = max(1, min(max_results, 200))
        records: list[AccountActivityRecord] = []
        page_token: str | None = None
        pages = 0
        max_pages = 4

        while len(records) < cap and pages < max_pages:
            kwargs: dict[str, Any] = {
                "part": "snippet",
                "myRating": "like",
                "maxResults": min(_MAX_BATCH_SIZE, cap - len(records)),
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._execute_request("videos.list", service.videos().list(**kwargs))
            pages += 1
            for item in resp.get("items", []):
                if not isinstance(item, dict):
                    continue
                vid = item.get("id")
                snippet = item.get("snippet") or {}
                if isinstance(vid, str) and vid:
                    # YouTube myRating='like' omits like-event timestamps (TBD-3)
                    records.append(
                        normalise_activity_record(
                            AccountActivityRecord(
                                item_id=vid,
                                activity_type="like",
                                account_id=account_id,
                                timestamp=None,
                                timestamp_provenance="unknown",
                                channel_id=snippet.get("channelId"),
                            )
                        )
                    )
                    if len(records) >= cap:
                        break
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return records

    def get_user_subscriptions(
        self,
        account_id: str,
        max_results: int = 200,
    ) -> list[AccountActivityRecord]:
        self.call_counts["get_user_subscriptions"] += 1
        self.requests += 1
        service = self._ensure_service()

        cap = max(1, min(max_results, 200))
        records: list[AccountActivityRecord] = []
        page_token: str | None = None
        pages = 0
        max_pages = 4

        while len(records) < cap and pages < max_pages:
            kwargs: dict[str, Any] = {
                "part": "snippet",
                "mine": True,
                "maxResults": min(_MAX_BATCH_SIZE, cap - len(records)),
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._execute_request(
                "subscriptions.list", service.subscriptions().list(**kwargs)
            )
            pages += 1
            for item in resp.get("items", []):
                if not isinstance(item, dict):
                    continue
                snippet = item.get("snippet") or {}
                cid = (snippet.get("resourceId") or {}).get("channelId")
                ts = _parse_optional_utc(snippet.get("publishedAt"))
                if isinstance(cid, str) and cid:
                    records.append(
                        normalise_activity_record(
                            AccountActivityRecord(
                                item_id=cid,
                                activity_type="subscription",
                                account_id=account_id,
                                timestamp=ts,
                                timestamp_provenance="genuine" if ts is not None else "unknown",
                                channel_id=cid,
                            )
                        )
                    )
                    if len(records) >= cap:
                        break
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return records

    def get_user_playlists(
        self,
        account_id: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        self.call_counts["get_user_playlists"] += 1
        self.requests += 1
        service = self._ensure_service()

        cap = max(1, min(max_results, _MAX_BATCH_SIZE))
        resp = self._execute_request(
            "playlists.list",
            service.playlists().list(part="snippet,contentDetails,status", mine=True, maxResults=cap),
        )
        playlists: list[dict[str, Any]] = []
        for item in resp.get("items", [])[:cap]:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet") or {}
            content = item.get("contentDetails") or {}
            status = item.get("status") or {}
            playlists.append(
                {
                    "playlist_id": str(item.get("id") or ""),
                    "title": sanitize_untrusted_text(snippet.get("title") or ""),
                    "item_count": _safe_int(content.get("itemCount")) or 0,
                    "privacy": str(status.get("privacyStatus") or "private"),
                }
            )
        return playlists

    def get_categories(self, region_code: str = "US") -> list[dict[str, Any]]:
        self.call_counts["get_categories"] += 1
        self.requests += 1
        service = self._ensure_service()

        resp = self._execute_request(
            "videoCategories.list",
            service.videoCategories().list(part="snippet", regionCode=region_code),
        )
        categories: list[dict[str, Any]] = []
        for item in resp.get("items", []):
            if isinstance(item, dict):
                categories.append(
                    {
                        "id": str(item.get("id") or ""),
                        "title": sanitize_untrusted_text(
                            (item.get("snippet") or {}).get("title") or ""
                        ),
                    }
                )
        return categories

    def check_channel_eligibility(self, account_id: str) -> bool:
        self.call_counts["check_channel_eligibility"] += 1
        self.requests += 1
        service = self._ensure_service()

        resp = self._execute_request(
            "channels.list",
            service.channels().list(part="id", mine=True),
            is_channel=True,
        )
        return bool(resp.get("items"))

    def create_playlist(
        self,
        title: str,
        description: str,
        privacy: str = "private",
    ) -> str:
        self._ensure_service()
        raise NotImplementedError("Playlist write operations are deferred to C21/C27.")

    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
    ) -> str:
        self._ensure_service()
        raise NotImplementedError("Playlist write operations are deferred to C21/C27.")

    def delete_playlist(self, playlist_id: str) -> bool:
        self._ensure_service()
        raise NotImplementedError("Playlist undo operations are deferred to C30.")
