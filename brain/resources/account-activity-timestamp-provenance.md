---
title: "Account Activity Timestamp Provenance"
author: "Harshil Srivastav"
date: 2026-11-22
type: research-note
status: active
srs_ids:
  - FR-3
  - FR-4
  - TQ-3
  - TBD-3
sources:
  - "https://developers.google.com/youtube/data/reference/rest/v3/videos/list"
  - "https://developers.google.com/youtube/data/reference/rest/v3/videos"
  - "https://developers.google.com/youtube/data/reference/rest/v3/videos/getRating"
  - "https://developers.google.com/youtube/data/reference/rest/v3/channels"
  - "https://developers.google.com/youtube/data/reference/rest/v3/playlistItems"
  - "https://developers.google.com/youtube/data/reference/rest/v3/subscriptions/list"
  - "https://developers.google.com/youtube/data/reference/rest/v3/subscriptions"
evidence:
  - "docs/testing/acceptance-cases.md#st-fr4"
  - "docs/testing/acceptance-cases.md#st-fr3"
  - "docs/testing/acceptance-cases.md#neg-profile"
uncertainty:
  - "TBD-3 remains open. No authorised Liked Videos response was inspected, and the documented playlist-add timestamp alone does not establish a like event."
---

# Account Activity Timestamp Provenance

[Condensed SRS §4.4 and Appendix C](../../FocusList_SRS_Condensed.docx) · [Course brief §2](../../Project_1_YouTube_MCP.pdf) · [C05 plan](../../FocusList_Commit_Plan.md#c05-document-discovery-and-analytics-evidence) · [Traceability](../../docs/requirements-traceability.md)

## Documented source dates

| Account source | Field and meaning | FR-4 interpretation |
| --- | --- | --- |
| Likes | Authorised [videos list](https://developers.google.com/youtube/data/reference/rest/v3/videos/list) with `myRating=like` returns video resources. [Get rating](https://developers.google.com/youtube/data/reference/rest/v3/videos/getRating) returns a rating and video ID without a rating datetime. [Channels](https://developers.google.com/youtube/data/reference/rest/v3/channels) identifies the Liked Videos playlist. The generic [playlist item](https://developers.google.com/youtube/data/reference/rest/v3/playlistItems) `snippet.publishedAt` is the playlist-add date. | The documented response confirms liked membership. A Liked Videos add date does not by itself prove when the user liked the video. Until that equivalence is substantiated, keep the like event date unknown. |
| Items in selected playlists | [Playlist item](https://developers.google.com/youtube/data/reference/rest/v3/playlistItems) `snippet.publishedAt` is when the item was added. Its `contentDetails.videoPublishedAt` is the video's publication time. | Prefer the add timestamp for the playlist observation. A playlist’s own creation date and the item's position are not substitutes. |
| Subscriptions | Authorised [subscriptions list](https://developers.google.com/youtube/data/reference/rest/v3/subscriptions/list) with `mine=true` returns the user's subscriptions. [Subscription](https://developers.google.com/youtube/data/reference/rest/v3/subscriptions) `snippet.publishedAt` is when that subscription was created. | Bucket a dated subscription as a subscription event. A channel creation date or a recent upload's publication date describes another resource. Neither supplies a missing subscription date. |
| Video publication | [Video](https://developers.google.com/youtube/data/reference/rest/v3/videos) `snippet.publishedAt` reports video publication, with documented exceptions for private or unlisted videos. | Use a valid publication timestamp as a labelled proxy for a video-backed observation when the usable source-event date is absent. Preserve its origin and never interpret it as watch history. |

## Planned fallback and disclosure

1. Keep the source-event date and video publication date distinct. For an observation with a usable source-event date, select that date for the trend and retain its event type. For a video-backed observation without a usable event date, select a valid publication date and mark the observation as a publication fallback. An absent or invalid event timestamp remains unknown in the underlying source record.
2. If both dates are unavailable, or a subscription has no usable event timestamp, keep the observation undated and exclude it from time buckets and period deltas. Report the number omitted from trends. C08 defines how undated rows appear in nonperiod source summaries and fixes the response fields, bucket boundaries and deduplication rules under the SRS. Never substitute the fetch clock or treat list order as time.
3. Show when a bucket or comparison includes fallback observations, with counts by source and date basis so a mixed bucket is identifiable. Suggested warning when used: “Some like or playlist add dates were unavailable. Marked trend points use the video's publication date as an estimate of timing. They do not show when you liked or added the video.” Suggested undated warning: “Some items had no usable timestamp and were excluded from trends.” C08 owns the wire schema and final wording.

## Planned deterministic fixtures

Extend [ST-FR4](../../docs/testing/acceptance-cases.md#st-fr4) with isolated synthetic variants. For the explicit-period variant use September and October 2026 UTC month windows and timestamps well inside those windows. Leave existing share and delta assertions intact in the original case.

| Fixture observation | Expected bucket and evidence |
| --- | --- |
| Selected playlist item added `2026-10-08T12:00:00Z`, video published `2026-09-13T12:00:00Z`. | October using playlist-add basis. September gets no duplicate observation and no fallback warning fires for this item. |
| Liked membership from `myRating=like` with publication `2026-09-14T12:00:00Z` and no verified like event. | September using publication basis, event date remains unknown and fallback warning is present. Mock recent discovery order must not move it to October. |
| Subscription created `2026-10-10T12:00:00Z` with a mock channel upload dated in September. | October using subscription-creation basis. The upload is not a subscription observation. |
| Playlist-add date missing, video publication valid in October. An unrelated liked row has neither date and another subscription has no usable creation date. | October reports a mixed event/publication bucket if combined with the dated cases. The two undated rows are separately reported and add zero time-bucket observations. |
| Future contract fixture supplies a documented, verified like event dated in October and video publication in September. | Prefer the October event with no fallback for this record. This is a synthetic precedence case, not evidence that the present live API provides the event. |

Assert no search attempts, no writes and at most 60 general units in fixture accounting. Assert partial-data messaging for a period with fewer than ten observations and null percentage change for a zero or empty baseline, as in C02.

## Open decision

Keep TBD-3 open for Harshil. An authorised, sanitised check would need to establish whether a liked-data source reliably exposes a time that corresponds to the like action, including add, remove and re-like semantics if relevant. There was no such check in C05. C23 can implement the disclosed publication fallback using the C08 contract without assuming a verified like event.
