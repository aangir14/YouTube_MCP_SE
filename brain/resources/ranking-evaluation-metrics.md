---
title: "Ranking Evaluation Metrics"
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
  - TBD-4
  - TBD-8
sources:
  - "FocusList_SRS_Condensed.docx"
  - "https://ir-measur.es/en/latest/measures.html#p"
  - "https://ir-measur.es/en/latest/measures.html#rr"
evidence:
  - "docs/testing/acceptance-cases.md#qa-relevance"
  - "docs/testing/acceptance-cases.md#ut-score"
  - "docs/testing/acceptance-cases.md#st-fr6"
uncertainty:
  - "C08 defines the final judgement policy and evaluation depth. C26 measures performance and records the decision on default weights and the provisional 0.60 target."
---

# Ranking Evaluation Metrics

[Condensed SRS §§4.6, 6.4, 6.6 and Appendix C](../../FocusList_SRS_Condensed.docx) · [Course brief §§2 and 4](../../Project_1_YouTube_MCP.pdf) · [C05 plan](../../FocusList_Commit_Plan.md#c05-document-discovery-and-analytics-evidence) · [Traceability](../../docs/requirements-traceability.md)

## Definitions and evidence

The SRS requires at least 20 labelled public seeds and comparison of metadata TF-IDF alone against the weighted ranker on identical candidates. The SRS glossary and the [ir-measures precision](https://ir-measur.es/en/latest/measures.html#p) and [reciprocal rank](https://ir-measur.es/en/latest/measures.html#rr) definitions support the following proposed evaluation protocol.

- Compute precision@5 per seed as the count of relevant results in the first five ranks divided by five. Use a fixed denominator so lists with fewer than five results do not gain credit for unfilled ranks. Report how often lists have fewer than five results.
- Compute reciprocal rank per seed as 1 divided by the one-based rank of the first relevant result, or zero if no relevant result appears in the evaluated ranking. Mean reciprocal rank (MRR) is the arithmetic mean of those per-seed values. Evaluate both methods to the same depth and disclose that depth. Average precision@5 across the same seeds.
- Freeze the eligible candidate IDs, binary relevance judgements, evaluation depth and preprocessing inputs before comparing. Label for topic and learning relevance using public metadata and a written rubric, independent of rank and popularity. Distinguish unjudged candidates from candidates judged irrelevant. Prefer full judging at the evaluated depth. Report unjudged coverage and agree on a policy in C08 before calculating results.
- Use identical candidates and the same stable tie rule for both methods. Per-seed evidence should record ordered IDs, labels and metrics alongside the aggregate, rubric and fixture revision. Record relevant defaults and exact reproduction steps in C26. The provisional precision@5 threshold of 0.60 is an evaluation target under TBD-4.

## Worked fixture for QA-RELEVANCE

Use two synthetic seeds and the same five judged candidates per seed in both orders. Here `1` means relevant and `0` means judged irrelevant. These numbers are arithmetic expectations for a future fixture.

| Seed | TF-IDF order by judgement | TF-IDF precision@5 and RR | Weighted order by judgement | Weighted precision@5 and RR |
| --- | --- | --- | --- | --- |
| A | 0, 1, 0, 1, 0 | 0.40 and 0.50 | 1, 0, 1, 0, 0 | 0.40 and 1.00 |
| B | 0, 0, 0, 0, 0 | 0.00 and 0.00 | 0, 0, 0, 0, 0 | 0.00 and 0.00 |
| Mean | | 0.20 and 0.25 | | 0.20 and 0.50 |

The same two relevant results move earlier for seed A, changing MRR while precision@5 stays constant. A separate two-candidate fixture with judgments `0, 1` yields precision@5 of 0.20 and reciprocal rank of 0.50 under the proposed short-list rule. Repeating a run against fixed inputs yields the same order and metrics. Link explanations and component checks through [UT-SCORE](../../docs/testing/acceptance-cases.md#ut-score) and [ST-FR6](../../docs/testing/acceptance-cases.md#st-fr6), and report comparison outcomes under [QA-RELEVANCE](../../docs/testing/acceptance-cases.md#qa-relevance).

## Open decisions

TBD-8 remains open until C08 freezes at least 20 labelled public seeds and the candidate and judgement sets. TBD-4 remains open until C26 reports actual paired results and the team records its decision on weights and the 0.60 target. No dataset, rankings or measured results were produced by this note.
