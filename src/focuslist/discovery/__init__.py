"""Discovery, recommendation, and engagement analytics services (FR-1–FR-4, FR-6)."""

from focuslist.discovery.channels import (
    CHANNEL_WEIGHTS,
    ChannelDiscovery,
    rank_similar_channels_two_pass,
)
from focuslist.discovery.engagement import HISTOGRAM_BINS, EngagementService
from focuslist.discovery.recommendations import (
    RECOMMENDATION_WEIGHTS,
    WATCH_HISTORY_DISCLOSURE,
    RecommendationService,
)
from focuslist.discovery.videos import VIDEO_WEIGHTS, VideoDiscovery, rank_similar_videos

__all__ = [
    "CHANNEL_WEIGHTS",
    "HISTOGRAM_BINS",
    "RECOMMENDATION_WEIGHTS",
    "VIDEO_WEIGHTS",
    "WATCH_HISTORY_DISCLOSURE",
    "ChannelDiscovery",
    "EngagementService",
    "RecommendationService",
    "VideoDiscovery",
    "rank_similar_channels_two_pass",
    "rank_similar_videos",
]
