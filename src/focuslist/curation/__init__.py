"""Curation service package (Ayush Patel - C09, C12, C15, C18, C21, C24, C27, C30).

Contains duration constraint solving, playlist proposal generation,
confirmation lifecycle, and write orchestration.
"""

from focuslist.curation.constraints import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_MIN_ITEM_DURATION_SECONDS,
    DEFAULT_TOLERANCE,
    HARD_MAX_ITEMS,
    PlaylistProposalRequest,
    ValidatedPlaylistConstraints,
    validate_proposal_arguments,
)
from focuslist.curation.proposals import (
    ProposalSignerHook,
    QuotaPreflightHook,
    propose_playlist_action,
)
from focuslist.curation.solver import (
    FR5_WEIGHTS,
    ConstraintViolation,
    ScoredCandidate,
    SelectedPlaylistItem,
    SolverResult,
    filter_eligible_candidates,
    greedy_baseline_select,
    score_candidates_fr5,
    solve_playlist,
)

__all__ = [
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_MIN_ITEM_DURATION_SECONDS",
    "DEFAULT_TOLERANCE",
    "FR5_WEIGHTS",
    "HARD_MAX_ITEMS",
    "ConstraintViolation",
    "PlaylistProposalRequest",
    "ProposalSignerHook",
    "QuotaPreflightHook",
    "ScoredCandidate",
    "SelectedPlaylistItem",
    "SolverResult",
    "ValidatedPlaylistConstraints",
    "filter_eligible_candidates",
    "greedy_baseline_select",
    "propose_playlist_action",
    "score_candidates_fr5",
    "solve_playlist",
    "validate_proposal_arguments",
]
