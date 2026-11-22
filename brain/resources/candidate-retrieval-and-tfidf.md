---
title: "Candidate Retrieval and TF-IDF"
author: "Harshil Srivastav"
date: 2026-11-22
type: research-note
status: active
srs_ids:
  - FR-1
  - FR-2
  - FR-3
  - FR-6
  - TQ-1
  - TQ-3
  - TQ-4
  - TBD-4
sources:
  - "Project_1_YouTube_MCP.pdf"
  - "https://developers.google.com/youtube/data/reference/rest/v3/search/list"
  - "https://developers.google.com/youtube/data/reference/rest/v3/channels"
  - "https://developers.google.com/youtube/data/reference/rest/v3/playlistItems/list"
  - "https://developers.google.com/youtube/data/reference/rest/v3/videos/list"
  - "https://scikit-learn.org/stable/modules/feature_extraction.html#tfidf-term-weighting"
  - "https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html"
evidence:
  - "docs/testing/acceptance-cases.md#st-fr1"
  - "docs/testing/acceptance-cases.md#st-fr2"
  - "docs/testing/acceptance-cases.md#st-fr3"
  - "docs/testing/acceptance-cases.md#neg-input"
  - "docs/testing/acceptance-cases.md#neg-unavailable"
  - "docs/testing/acceptance-cases.md#ut-score"
uncertainty:
  - "C08 must define the corpus, tokenizer, channel text aggregation and empty-vector behavior. C26 measures the defaults under TBD-4."
---

# Candidate Retrieval and TF-IDF

[Condensed SRS §§4.1–4.3, 4.6 and 6.4](../../FocusList_SRS_Condensed.docx) · [Course brief §§2 and 4](../../Project_1_YouTube_MCP.pdf) · [C05 plan](../../FocusList_Commit_Plan.md#c05-document-discovery-and-analytics-evidence) · [Traceability](../../docs/requirements-traceability.md)

## Source findings

- The course brief requires metadata-based similarity because the official API supplies neither related-item rankings nor watch history. Use the official provider to gather bounded candidates, then score locally.
- [Search list](https://developers.google.com/youtube/data/reference/rest/v3/search/list) provides query and resource-type filters and page tokens. [Channels](https://developers.google.com/youtube/data/reference/rest/v3/channels) exposes the uploads playlist ID. [Playlist items list](https://developers.google.com/youtube/data/reference/rest/v3/playlistItems/list) provides playlist entries. [Videos list](https://developers.google.com/youtube/data/reference/rest/v3/videos/list) fetches requested resource parts by video ID. Search results are candidate references. Hydrate the metadata required for eligibility and scoring through the provider.
- [TF-IDF term weighting](https://scikit-learn.org/stable/modules/feature_extraction.html#tfidf-term-weighting) explains term frequency and corpus-dependent inverse document frequency. [Cosine similarity](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html) is a normalized dot product. Use a shared vocabulary and IDF for each comparison. These references explain the method. Dependency and preprocessing choices remain with C08.

## SRS baseline

| Flow | Candidate set and bounds | Local ranking |
| --- | --- | --- |
| FR-1 similar videos | Up to two searches and one seed uploads page. Deduplicate by video ID, exclude the seed, cap at 150 distinct candidates and batch details. | Text cosine, tag overlap, category, duration, language and channel use weights 0.50, 0.15, 0.10, 0.10, 0.10 and 0.05 in that order. Ties use newest publication then ID. Return 10 by default and at most 50. |
| FR-2 similar channels | Profile the seed using at most 20 recent uploads. Use at most three searches and 100 distinct candidates excluding the seed. Exclude inaccessible channels or channels without public uploads. | Text cosine, topic, language and channel size use 0.60, 0.20, 0.10 and 0.10. Rerank the top 10 using recent uploads. Return 10 by default and at most 25. |
| FR-3 recommendations | Use only selected authorised sources, capped at 200 likes, 200 subscriptions and five playlists with 100 items each. Use at most three searches and uploads from five relevant subscribed channels. Exclude liked and loaded-playlist IDs. | Profile similarity, freshness, duration fit and channel affinity use 0.60, 0.20, 0.10 and 0.10. Give reasons from up to three influential items or channels. |

FR-6 explanations use the same feature values as the score. Keep component totals within 0.000001, include at most five shared terms, cap the reason at 200 characters and avoid explanation-time network calls. Missing features are covered in the [sparse metadata note](missing-metadata-and-sparse-fixtures.md).

## Planned deterministic fixtures

| Inputs | Expected behavior | C02 case |
| --- | --- | --- |
| One synthetic seed represented by watch, short-link, Shorts, embed and raw ID forms. A separate malformed ID of ten characters. | Valid forms resolve to the same seed and ordered results. The malformed ID returns `INVALID_VIDEO_ID` with zero provider calls, outbound attempts and writes. | [ST-FR1](../../docs/testing/acceptance-cases.md#st-fr1), [NEG-INPUT](../../docs/testing/acceptance-cases.md#neg-input) |
| Two valid mocked result pages repeat one candidate and echo the seed. Batched details omit a deleted candidate. Two remaining candidates have equal scores and equal publication times. | Include the repeated candidate once, omit seed and unavailable candidate and break the tie by ID. A separate inaccessible seed returns `VIDEO_UNAVAILABLE` before candidate search. Assert retrieval caps and zero writes. | [ST-FR1](../../docs/testing/acceptance-cases.md#st-fr1), [NEG-UNAVAILABLE](../../docs/testing/acceptance-cases.md#neg-unavailable) |
| Mock channel results echo the seed, duplicate one channel and include a channel with zero public uploads. Mock recommendation candidates include an already-liked ID and a loaded-playlist ID. | Exclude each ineligible result. Channel reranking looks up recent uploads only for the top ten. Recommendations respect source selection and caps. Both make zero writes. | [ST-FR2](../../docs/testing/acceptance-cases.md#st-fr2), [ST-FR3](../../docs/testing/acceptance-cases.md#st-fr3) |
| Frozen nonzero vectors for identical and orthogonal synthetic text feature inputs. | Cosine is 1 and 0 respectively, before applying weights. Assert bounded score and explanation agreement. | [UT-SCORE](../../docs/testing/acceptance-cases.md#ut-score) |

## Open decisions

C08 records the exact metadata fields, normalization, corpus, missing-feature policy, and channel/recommendation tie rules. C26 compares the published defaults on a frozen evaluation set under TBD-4. The fixtures above are specifications for those commits. No relevance or provider run is claimed here.
