# C12 Curation Solver Baseline & Stage 2 Verification Evidence

**Owner:** Ayush Patel (C12)  
**Date:** 2026-11-25 (IST)  
**Scope:** FR-5.1–5.8, FR-5.15, NFR-REL, TQ-1  
**Implementation:** [`src/focuslist/curation/constraints.py`](../../src/focuslist/curation/constraints.py) · [`src/focuslist/curation/solver.py`](../../src/focuslist/curation/solver.py) · [`tests/unit/test_curation_constraints_and_solver.py`](../../tests/unit/test_curation_constraints_and_solver.py)

---

## 1. Baseline Comparison: Bounded DP Solver vs Greedy-by-Score

On a fixed synthetic shortlist targeting **30 minutes** (`PT30M` = 1,800s, $\pm 5\%$ window `[1710s, 1890s]`) with `max_item_duration = PT20M` (1,200s):

| Candidate | Duration | Pre-Score | Greedy Choice | Bounded DP Choice |
| :--- | :---: | :---: | :---: | :---: |
| `vid_A000001` | 1,100s | `0.90` | **Picked** | Skipped |
| `vid_B000002` | 900s | `0.80` | Skipped (exceeds 1890s) | **Picked** |
| `vid_C000003` | 900s | `0.80` | Skipped (exceeds 1890s) | **Picked** |
| `vid_D000004` | 500s | `0.50` | **Picked** | Skipped |

- **Greedy Baseline (`greedy_baseline_select`)**: Picks `A + D` = **1,600s** (26m 40s), falling short of the 1,710s lower bound $\rightarrow$ **Infeasible** (`total_score = 1.40`).
- **FocusList DP Solver (`solve_playlist`)**: Picks `B + C` = **1,800s** (30m 00s, exact target) $\rightarrow$ **Feasible** (`total_score = 1.60`).

---

## 2. Verified Invariants & Property-Test Summary

Executed in `tests/unit/test_curation_constraints_and_solver.py` (offline, zero network or storage dependencies):
1. **Strict Argument Schema**: Unknown keys, blank/oversized topics, non-positive durations, `min > max`, `max_items > 50`, booleans in integer fields, and invalid language tags/seed IDs raise `InvalidArgumentsError`.
2. **Hard Filter Preservation**: Live, upcoming, age-restricted, duplicate, out-of-range, and language-mismatched candidates are excluded prior to selection and never relaxed on infeasible targets.
3. **Boundary & Cap Checks**: Exact `[6840s, 7560s]` tolerance bounds, 12-item 2-hour/20-minute baseline, `allow_unknown_language` warning flag, and hard 50-item cap verified.
4. **Property Harness (250 Generated Cases)**: Verified window satisfaction, item uniqueness, duration-sum consistency, and hard-filter invariants across 250 seeded randomized scenarios.
