---
title: Playlist Constraints and Deterministic Duration Solver Architecture
author: Ayush Patel
date: 2026-11-24
type: research-note
status: active
srs_ids:
  - FR-5.1
  - FR-5.2
  - FR-5.3
  - FR-5.4
  - FR-5.5
  - FR-5.6
  - FR-5.7
  - FR-5.15
  - NFR-PERF
  - TQ-1
sources:
  - "docs/curation-walkthrough.md"
  - "FocusList_SRS_Condensed.docx"
  - "Project_1_YouTube_MCP.pdf"
evidence:
  - "docs/testing/acceptance-cases.md#ut-solver"
  - "docs/testing/acceptance-cases.md#neg-constraint"
  - "docs/curation-walkthrough.md#scenario-cw-01-baseline-2-hour-english-playlist-on-recursion"
  - "docs/curation-walkthrough.md#scenario-cw-04-infeasible-target-with-nearest-achievable-runtime"
uncertainty:
  - "Optimal dynamic programming pruning thresholds when candidate pool exceeds 300 videos"
  - "Exact learner preference balance between maximizing total duration fill vs minimizing total item count"
---

# Playlist Constraints and Deterministic Duration Solver Architecture

## 1. Architectural Scope and Problem Formulation

In FocusList, playlist curation is an automated, constraint-driven combinatorial optimization problem. Per requirements **FR-5.1–FR-5.7, FR-5.15** and **Implementation Plan Section 5**, a learner submits high-level pedagogical requirements (topic, target runtime, max video length, language), and the curation engine deterministically selects a feasible, highly relevant subset of videos from an untrusted candidate pool.

Unlike heuristic or greedy video selection that can produce erratic durations or include low-quality filler, FocusList guarantees:
1. **Hard constraint enforcement**: Every video in the playlist strictly satisfies all per-item constraints (duration $\le \text{max\_item\_duration}$, duration $\ge \text{min\_item\_duration}$, verified language).
2. **Global runtime bounded within tolerance**: Total playlist runtime must fall within $[T \times (1 - \tau), T \times (1 + \tau)]$, where $T$ is the target duration and $\tau$ is tolerance (default 5%).
3. **Pure mathematical determinism**: Given identical candidate sets and constraints, the solver emits identical ordered sets with reproducible tie-breaking.
4. **Zero silent degradation**: If a target is mathematically unreachable, the solver explicitly reports infeasibility and the nearest achievable duration rather than violating hard constraints.

```
+--------------------------------------------------------------------------+
|                       Learner Natural Request                            |
|        (Topic: "recursion", Target: PT2H, Max: PT20M, Lang: "en")       |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                     1. Local Parameter Validation                        |
|       (1 <= len(topic) <= 200, positive ISO-8601, min <= max)           |
+--------------------------------------------------------------------------+
                                     | (Zero API calls on error)
                                     v
+--------------------------------------------------------------------------+
|                      2. Hard Filtering & Scrubbing                       |
|   (Filter private, unavailable, live, upcoming, age-restricted, lang)   |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                  3. Pure Deterministic Duration Solver                   |
|     (DP / Bounded Knapsack over Integer Seconds with Tie-Breaking)       |
+--------------------------------------------------------------------------+
          |                                              |
     (Feasible)                                     (Infeasible)
          v                                              v
+-------------------------+              +---------------------------------+
| Formulate Proposal &    |              | Report Infeasibility Breakdown  |
| Signed HMAC Token       |              | & Nearest Achievable Total      |
+-------------------------+              +---------------------------------+
```

---

## 2. Parameter Validation Contracts (FR-5.1–5.3, FR-5.15)

Parameter validation is strictly local and executed **before** any provider discovery calls or quota reservations:

| Parameter | Type / Format | Validation Rule | Default Value | Error on Failure |
| :--- | :--- | :--- | :--- | :--- |
| `topic` | `string` | $1 \le \text{len}(\text{topic}) \le 200$, non-whitespace | Required | `INVALID_ARGUMENTS` |
| `target_duration` | ISO-8601 string | Positive duration $> 0$, parsed to integer seconds | Required | `INVALID_ARGUMENTS` |
| `max_item_duration` | ISO-8601 string | Positive duration $> 0$, parsed to integer seconds | Required | `INVALID_ARGUMENTS` |
| `min_item_duration` | ISO-8601 string | Positive duration $\ge 0$; must satisfy $\text{min} \le \text{max}$ | `PT2M` (120s) | `CONSTRAINT_CONFLICT` |
| `tolerance` | `float` | $0.0 \le \tau \le 0.25$ ($\pm 0\%$ to $\pm 25\%$) | `0.05` ($\pm 5\%$) | `INVALID_ARGUMENTS` |
| `language` | ISO-639-1 code | 2-letter lowercase code (e.g. `"en"`, `"es"`) | `"en"` | `INVALID_ARGUMENTS` |
| `max_items` | `integer` | $1 \le N \le 50$ (hard ceiling per SRS 6.4) | `30` (TBD-9) | `INVALID_ARGUMENTS` |
| `ordering` | `string` enum | `"learning_path"`, `"relevance"`, `"chronological"` | `"learning_path"` | `INVALID_ARGUMENTS` |
| `privacy` | `string` enum | `"private"`, `"unlisted"`, `"public"` | `"private"` | `INVALID_ARGUMENTS` |

### Integer Seconds Canonicalization
Durations are parsed strictly into non-negative 64-bit integer seconds:
- `PT2H` $\rightarrow 7,200\text{ seconds}$
- `PT20M` $\rightarrow 1,200\text{ seconds}$
- Floating-point seconds are prohibited to prevent floating-point rounding divergence across OS platforms.

---

## 3. Mathematical Optimization Formulation (FR-5.4, FR-5.5)

Let $C = \{v_1, v_2, \dots, v_m\}$ be the set of $m$ filtered, deduplicated candidate videos.  
Each candidate $v_i$ possesses:
- Duration in integer seconds: $d_i \in [\text{min\_item\_duration}, \text{max\_item\_duration}]$
- Normalized composite relevance score: $s_i \in [0.0, 1.0]$

The selection is modeled as a 0-1 Bounded Knapsack Problem with dual boundary constraints:
$$\text{Maximize } S = \sum_{i=1}^m s_i x_i \quad \text{where } x_i \in \{0, 1\}$$
Subject to:
$$T_{\text{lower}} \le \sum_{i=1}^m d_i x_i \le T_{\text{upper}}$$
$$\sum_{i=1}^m x_i \le N_{\text{max}}$$
Where:
- $T_{\text{lower}} = \lceil T \times (1 - \tau) \rceil$ (e.g., for 7,200s at 5%: $6,840\text{s} = 114\text{m}$)
- $T_{\text{upper}} = \lfloor T \times (1 + \tau) \rfloor$ (e.g., for 7,200s at 5%: $7,560\text{s} = 126\text{m}$)
- $N_{\text{max}} = \min(\text{max\_items}, 50)$

### Solver Algorithm: Bounded Dynamic Programming with Pruning
Because video runtimes are multiples of integer seconds and candidate pools are bounded ($m \le 150$ per FR-1), we utilize a dynamic programming table or bounded depth-first branch-and-bound search:
1. **Pre-sorting**: Sort candidates in descending order of efficiency $e_i = s_i / d_i$, with deterministic tie-breaking on:
   - Descending relevance score $s_i$
   - Descending publication timestamp (newest first)
   - Ascending canonical video ID (lexicographical string comparison)
2. **Reachable States Table**: Track reachable durations up to $T_{\text{upper}}$ using an array indexed by second.
3. **Pruning**: States exceeding $T_{\text{upper}}$ or item count $N_{\text{max}}$ are pruned immediately.

### Performance Target (NFR-PERF)
- The solver must compute a feasible 120-minute playlist from 200 candidates in $\le 2.0\text{ seconds}$ on standard runner hardware without exceeding 50 MB memory overhead.

---

## 4. Infeasibility Handling & Nearest Achievable Total (FR-5.6)

When the candidate pool cannot satisfy the dual bounds $[T_{\text{lower}}, T_{\text{upper}}]$:
1. **Refusal to Silently Degrade**: The engine will **never**:
   - Include videos exceeding `max_item_duration`.
   - Include videos in unverified languages unless explicitly configured.
   - Force an undersized playlist into a proposal.
2. **Deficit Calculation**: The engine computes the maximum achievable duration $D_{\text{max}} = \sum_{i=1}^{\min(m, N_{\text{max}})} d_i$.
3. **Structured Infeasibility Payload**:
   ```json
   {
     "status": "infeasible",
     "target_duration_seconds": 7200,
     "tolerance": 0.05,
     "achievable_duration_seconds": 850,
     "achievable_item_count": 5,
     "unmet_constraints": [
       {
         "constraint": "target_duration",
         "target_range": "6840s to 7560s (114m to 126m)",
         "achieved": "850s (14m 10s)",
         "deficit_seconds": -5990
       }
     ],
     "remediation_hint": "Available matching videos total 14m 10s. Consider increasing max_item_duration, broadening the topic search, or lowering target_duration."
   }
   ```
4. **Zero-Mutation Guarantee**: When status is `infeasible`, no HMAC proposal token is generated. No creation call can be made.

---

## 5. Traceability and Verification Mappings

| Requirement | Description | Verified Contract / Acceptance Case |
| :--- | :--- | :--- |
| **FR-5.1–5.3** | Parameter validation and local bounds | [`NEG-CONSTRAINT`](../docs/testing/acceptance-cases.md#neg-constraint), [`UT-PARSE`](../docs/testing/acceptance-cases.md#ut-parse) |
| **FR-5.4–5.5** | Deterministic selection within tolerance | [`UT-SOLVER`](../docs/testing/acceptance-cases.md#ut-solver), [`ST-FR5`](../docs/testing/acceptance-cases.md#st-fr5) |
| **FR-5.6** | Nearest achievable runtime on infeasible set | [`UT-SOLVER`](../docs/testing/acceptance-cases.md#ut-solver), [`CW-04`](../docs/curation-walkthrough.md#scenario-cw-04-infeasible-target-with-nearest-achievable-runtime) |
| **FR-5.15** | Hard cap at 50 items | [`UT-SOLVER`](../docs/testing/acceptance-cases.md#ut-solver) |
| **NFR-PERF** | Solver execution $\le 2.0\text{s}$ for 200 candidates | [`QA-RELEASE`](../docs/testing/acceptance-cases.md#qa-release) |
