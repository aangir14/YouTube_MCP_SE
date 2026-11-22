---
title: "Missing Metadata and Sparse Fixtures"
author: "Harshil Srivastav"
date: 2026-11-22
type: research-note
status: active
srs_ids:
  - FR-1
  - FR-2
  - FR-3
  - FR-4
  - FR-6
  - TQ-4
sources:
  - "Project_1_YouTube_MCP.pdf"
  - "https://developers.google.com/youtube/data/reference/rest/v3/videos"
  - "https://developers.google.com/youtube/data/reference/rest/v3/channels"
  - "https://developers.google.com/youtube/data/reference/rest/v3/search/list"
  - "https://developers.google.com/youtube/data/reference/rest/v3/videoCategories/list"
evidence:
  - "docs/testing/acceptance-cases.md#neg-metadata"
  - "docs/testing/acceptance-cases.md#neg-profile"
  - "docs/testing/acceptance-cases.md#neg-unavailable"
  - "docs/testing/acceptance-cases.md#st-fr4"
  - "docs/testing/acceptance-cases.md#st-fr6"
uncertainty:
  - "C08 owns the scoring treatment of absent inputs and the exact warning schema. The examples preserve unknown fields without defining new public error codes."
---

# Missing Metadata and Sparse Fixtures

[Condensed SRS §§4.1–4.4, 4.6 and 6.6](../../FocusList_SRS_Condensed.docx) · [Course brief §4](../../Project_1_YouTube_MCP.pdf) · [C05 plan](../../FocusList_Commit_Plan.md#c05-document-discovery-and-analytics-evidence) · [Traceability](../../docs/requirements-traceability.md)

## Source findings

- [Videos](https://developers.google.com/youtube/data/reference/rest/v3/videos) defines tags, category ID, video duration, metadata language and default audio language. The language of the title/description and the spoken language are separate signals. Public statistics may be unavailable. Google documents dislike count as owner-only, so public ranking cannot depend on it.
- [Search list](https://developers.google.com/youtube/data/reference/rest/v3/search/list) describes `relevanceLanguage` as a relevance hint that may still return other languages. An explicit language match requires independent metadata evidence under the configured SRS policy.
- [Channels](https://developers.google.com/youtube/data/reference/rest/v3/channels) provides `statistics.hiddenSubscriberCount` and channel keywords under `brandingSettings.channel.keywords`. Missing keywords and a hidden or unavailable count are unknown. [Video categories list](https://developers.google.com/youtube/data/reference/rest/v3/videoCategories/list) supplies category records for resolving category IDs to names. An unresolved category cannot be assigned a fabricated name.

## Planned deterministic fixtures

| Synthetic input | Expected result | C02 case |
| --- | --- | --- |
| Readable candidate with a known duration and title but omitted tags, description and language. A second candidate has an explicitly empty tag list. | Route both through deterministic missing-data handling. Preserve the omission for diagnostics rather than inferring tag overlap or language. Report missing fields and low confidence as appropriate. Repeat with and without an explicit language constraint and assert no unverified match is labelled verified. | [NEG-METADATA](../../docs/testing/acceptance-cases.md#neg-metadata), [ST-FR6](../../docs/testing/acceptance-cases.md#st-fr6) |
| The mock channel has `hiddenSubscriberCount: true`, no count and no keywords. A control channel explicitly reports zero subscribers. | The hidden count stays unknown and flagged. The explicit zero is distinct. Neither row acquires invented keywords. Ranking follows the same documented missing-feature policy on repeat. | [NEG-METADATA](../../docs/testing/acceptance-cases.md#neg-metadata), [ST-FR2](../../docs/testing/acceptance-cases.md#st-fr2) |
| The mock provider omits a deleted seed from batch results or explicitly marks a candidate private. | An inaccessible seed returns `VIDEO_UNAVAILABLE` without candidate search. An unavailable candidate is excluded rather than scored as an otherwise readable item with sparse metadata. | [NEG-UNAVAILABLE](../../docs/testing/acceptance-cases.md#neg-unavailable), [ST-FR1](../../docs/testing/acceptance-cases.md#st-fr1) |
| A selected authorised account source returns an empty collection, and a separate test removes consent. | Empty profile returns `NO_PROFILE_DATA` after bounded source reads with zero discovery searches. Missing consent returns `AUTH_REQUIRED` with zero provider calls. | [NEG-PROFILE](../../docs/testing/acceptance-cases.md#neg-profile) |
| FR-4 mock period has four observations. Three durations are 5, 10 and 20 minutes. One duration is missing, and one category ID has no name mapping. | Return available metrics with the under-ten warning. Duration mean is 700 seconds and median is 600 seconds over three known durations. The unknown duration contributes no histogram entry and the unknown category is disclosed without fabricating a label. Assert zero searches and at most 60 general units. Histogram edge expectations belong to C08. | [ST-FR4](../../docs/testing/acceptance-cases.md#st-fr4) |

All cases target fixture or mock execution with zero real YouTube calls and zero writes. An explicit zero is a valid observation when the API returns it. C08 defines score treatment and the report shape for unknown values. These examples are planned checks.
