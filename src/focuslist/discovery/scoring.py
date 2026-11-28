"""Shared local text normalization, TF-IDF vectorization, and trace helpers (FR-1–FR-3, FR-6)."""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeVar

from typing_extensions import TypedDict

from focuslist.context import RequestContext
from focuslist.errors import AuthRequiredError, FocusListError, QuotaBudgetExceededError
from focuslist.metadata import primary_language
from focuslist.platform.auth import AuthManager
from focuslist.platform.gateway import ProviderGateway
from focuslist.platform.provider import VideoProvider

_T = TypeVar("_T")

ENGLISH_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)


def tokenize_text(text: str, language: str | None) -> list[str]:
    """Normalize NFKC/casefold, split on non-alphanumeric runs, and filter English stop words."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = "".join(c if c.isalnum() else " " for c in normalized).split()
    if primary_language(language) == "en":
        return [word for word in words if word not in ENGLISH_STOP_WORDS]
    return words


def build_tfidf_vectors(
    documents: Mapping[str, tuple[str, str | None]],
) -> dict[str, dict[str, float]]:
    """Compute L2-normalized TF-IDF vectors over a fixed document map {doc_id: (text, lang)}."""
    tokenized = {
        doc_id: Counter(tokenize_text(text, lang)) for doc_id, (text, lang) in documents.items()
    }
    doc_freq = Counter(term for counts in tokenized.values() for term in counts)
    doc_count = len(tokenized)
    vectors: dict[str, dict[str, float]] = {}
    for doc_id, counts in tokenized.items():
        weights = {
            term: count * (math.log((1 + doc_count) / (1 + doc_freq[term])) + 1.0)
            for term, count in counts.items()
        }
        norm = math.sqrt(math.fsum(value * value for value in weights.values()))
        vectors[doc_id] = {term: value / norm for term, value in weights.items()} if norm else {}
    return vectors


def mean_normalized_vector(vectors: Iterable[dict[str, float]]) -> dict[str, float]:
    """Compute the L2-normalized mean of non-empty TF-IDF vectors."""
    summed: dict[str, float] = {}
    count = 0
    for vec in vectors:
        if not vec:
            continue
        count += 1
        for term, weight in vec.items():
            summed[term] = summed.get(term, 0.0) + weight
    if count == 0:
        return {}
    mean_vec = {term: val / count for term, val in summed.items()}
    norm = math.sqrt(math.fsum(val * val for val in mean_vec.values()))
    return {term: val / norm for term, val in mean_vec.items()} if norm else {}


def cosine_and_shared_terms(
    left: dict[str, float],
    right: dict[str, float],
    *,
    max_terms: int = 5,
) -> tuple[float, list[str]]:
    """Return clamped cosine similarity and top shared terms by pairwise product descending."""
    if not left or not right:
        return 0.0, []
    products = {term: weight * right[term] for term, weight in left.items() if term in right}
    if not products:
        return 0.0, []
    cosine = min(1.0, math.fsum(products.values()))
    shared = sorted(products, key=lambda term: (-products[term], term))[:max_terms]
    return cosine, shared


def build_feature_trace(
    raw: Mapping[str, float],
    weights: Mapping[str, float],
) -> tuple[dict[str, dict[str, float]], float]:
    """Build per-factor trace dicts and rounded score matching contributions within 1e-6."""
    trace = {
        name: {
            "raw": float(raw[name]),
            "weight": float(weight),
            "contribution": float(raw[name]) * float(weight),
        }
        for name, weight in weights.items()
    }
    score = round(math.fsum(factor["contribution"] for factor in trace.values()), 6)
    return trace, score


def format_reason(
    trace: Mapping[str, Mapping[str, float]],
    *,
    prefix: str = "Strongest signals: ",
    empty_msg: str = "No positive similarity signals in the available metadata.",
    suffix: str = "",
    max_length: int = 200,
) -> str:
    """Format a deterministic <=200-char reason string from highest positive contributions."""
    positives = sorted(
        (name for name in trace if trace[name]["contribution"] > 0),
        key=lambda name: (-trace[name]["contribution"], name),
    )
    if not positives:
        base = empty_msg
    else:
        base = prefix + ", ".join(name.replace("_", " ") for name in positives[:3]) + "."
    full = f"{base} {suffix}".strip() if suffix else base
    if len(full) <= max_length:
        return full
    return full[: max_length - 3].rstrip() + "..."


class ScoreExplanation(TypedDict):
    score: float
    components: dict[str, float]
    feature_trace: dict[str, dict[str, float]]
    shared_terms: list[str]
    missing_fields: list[str]
    low_confidence: bool
    reason: str


def explain_score(
    raw: Mapping[str, float],
    weights: Mapping[str, float],
    *,
    shared_terms: Sequence[str] = (),
    missing_fields: Sequence[str] = (),
    low_confidence: bool = False,
) -> ScoreExplanation:
    """Build the common FR-6 response without calling a provider."""
    trace, score = build_feature_trace(raw, weights)
    missing = sorted(set(missing_fields))
    return {
        "score": score,
        "components": dict(weights),
        "feature_trace": trace,
        "shared_terms": list(dict.fromkeys(shared_terms))[:5],
        "missing_fields": missing,
        "low_confidence": low_confidence,
        "reason": format_reason(trace),
    }


def resolve_authorized_account(
    context: RequestContext,
    auth_manager: AuthManager | None = None,
) -> str:
    """Resolve the active authorized account ID or raise AUTH_REQUIRED before provider I/O."""
    if context.has_read_consent is False:
        raise AuthRequiredError()
    if context.account_id and context.account_id.strip():
        return context.account_id.strip()
    if auth_manager is not None:
        status = auth_manager.get_status()
        if status.authenticated and status.account_id:
            return status.account_id
        raise AuthRequiredError()
    if context.settings.provider == "fixture":
        return "fixture_learner"
    raise AuthRequiredError()


def run_tool_with_envelope(
    context: RequestContext,
    provider: VideoProvider,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a service operation and populate MetaEnvelope with quota/cache counters."""
    before_units = context.quota_used
    before_searches = context.search_calls_used
    before_hits = context.cache_hits
    try:
        result = operation()
    except FocusListError as exc:
        payload = context.failure(exc).model_dump()
    else:
        payload = context.success(result).model_dump()

    payload["meta"]["quota_used"] = context.quota_used - before_units
    payload["meta"]["search_calls"] = context.search_calls_used - before_searches
    payload["meta"]["cache_hits"] = context.cache_hits - before_hits
    if isinstance(provider, ProviderGateway):
        payload["meta"]["quota_remaining"] = (
            provider.quota_manager.get_status().general_units_remaining
        )
    return payload


def preflight_non_gateway(
    context: RequestContext,
    provider: VideoProvider,
    general_units: int,
    search_calls: int = 0,
) -> None:
    """Enforce local preflight budget check when provider is not a ProviderGateway."""
    if isinstance(provider, ProviderGateway):
        return
    settings = context.settings
    available = (
        settings.daily_general_quota
        - math.ceil(settings.daily_general_quota * settings.quota_safety_margin)
        - context.quota_used
    )
    if (
        general_units > min(available, settings.request_unit_cap)
        or search_calls > settings.daily_search_quota - context.search_calls_used
    ):
        raise QuotaBudgetExceededError()


def read_with_accounting(
    context: RequestContext,
    provider: VideoProvider,
    operation: Callable[[], _T],
    *,
    search: bool = False,
) -> _T:
    """Run a provider read and sync attempt/cache counters to RequestContext."""
    before_attempts = provider.network_attempts
    before_hits = getattr(provider, "cache_hits", 0)
    try:
        return operation()
    finally:
        if isinstance(provider, ProviderGateway):
            context.set_quota_remaining(
                provider.quota_manager.get_status().general_units_remaining
            )
        else:
            attempts = provider.network_attempts - before_attempts
            hits = getattr(provider, "cache_hits", 0) - before_hits
            if hits > 0:
                context.record_cache_hit(hits)
            if search:
                context.record_search_charge(attempts)
            else:
                context.record_quota_charge(attempts)


def most_frequent_primary_language(languages: Sequence[str | None]) -> str | None:
    """Return the most common known primary language subtag with lexical tie-break."""
    counts: Counter[str] = Counter()
    for lang in languages:
        primary = primary_language(lang)
        if primary:
            counts[primary] += 1
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))[0]
