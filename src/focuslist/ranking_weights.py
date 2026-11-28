"""Named SRS defaults for the four ranking paths."""

VIDEO_WEIGHTS = {
    "text_cosine": 0.50, "tag_overlap": 0.15, "category_match": 0.10,
    "duration_fit": 0.10, "language_match": 0.10, "same_channel": 0.05,
}
CHANNEL_WEIGHTS = {
    "text_cosine": 0.60, "topic_overlap": 0.20, "language_match": 0.10, "size_fit": 0.10,
}
RECOMMENDATION_WEIGHTS = {
    "profile_similarity": 0.60, "freshness": 0.15, "duration_fit": 0.15, "channel_affinity": 0.10,
}
FR5_WEIGHTS = {
    "topic_match": 0.65, "caption_availability": 0.10, "freshness": 0.10,
    "capped_quality": 0.10, "known_language": 0.05,
}

DEFAULT_SCORING_WEIGHTS = {
    "similar_videos": VIDEO_WEIGHTS,
    "similar_channels": CHANNEL_WEIGHTS,
    "recommend_videos": RECOMMENDATION_WEIGHTS,
    "propose_playlist": FR5_WEIGHTS,
}
