"""Fuzzy string matching backed by rapidfuzz.

depends_on_external: rapidfuzz
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process


class FuzzyMatchResult(BaseModel):
    """Single fuzzy match result.

    Attributes:
        candidate: The matched candidate string.
        score: Normalised similarity score in [0.0, 1.0].

    Example:
        >>> r = FuzzyMatchResult(candidate="Apple", score=0.95)
        >>> r.score
        0.95
    """

    candidate: str
    score: float = Field(ge=0.0, le=1.0)


class FuzzyMatchError(ValueError):
    """Raised when fuzzy_match receives invalid arguments."""


def fuzzy_match(
    *,
    query: str,
    candidates: list[str],
    threshold: float = 0.8,
    top_k: int = 1,
) -> list[FuzzyMatchResult]:
    """Return the top-k candidates that fuzzy-match *query* above *threshold*.

    Uses ``rapidfuzz.fuzz.WRatio`` which selects the best sub-algorithm
    (token_sort / token_set / partial_ratio) per pair, making it robust for
    short labels, Chinese text, and partially-ordered tokens.

    Args:
        query: The string to search for.
        candidates: Pool of strings to match against.
        threshold: Minimum score (inclusive) to include a result, in [0.0, 1.0].
            Defaults to 0.8.
        top_k: Maximum number of results to return, sorted by score descending.
            Must be ≥ 1.

    Returns:
        List of :class:`FuzzyMatchResult` sorted by ``score`` descending,
        containing at most *top_k* items.  Empty list when nothing clears
        *threshold*.

    Raises:
        FuzzyMatchError: If *threshold* is outside [0.0, 1.0] or *top_k* < 1.

    Example:
        >>> fuzzy_match(query="Apple", candidates=["Apple", "Apricot", "Banana"])
        [FuzzyMatchResult(candidate='Apple', score=1.0)]

        >>> fuzzy_match(query="苹果", candidates=["苹果公司", "香蕉", "苹果"], threshold=0.7)
        [FuzzyMatchResult(candidate='苹果', score=1.0)]
    """
    if not (0.0 <= threshold <= 1.0):
        raise FuzzyMatchError(f"threshold must be in [0.0, 1.0], got {threshold!r}")
    if top_k < 1:
        raise FuzzyMatchError(f"top_k must be ≥ 1, got {top_k!r}")
    if not candidates:
        return []

    # rapidfuzz returns scores in [0, 100]; normalise to [0.0, 1.0].
    threshold_pct = threshold * 100.0
    hits = process.extract(
        query,
        candidates,
        scorer=fuzz.WRatio,
        score_cutoff=threshold_pct,
        limit=top_k,
    )
    return [
        FuzzyMatchResult(candidate=match, score=round(score / 100.0, 6)) for match, score, _ in hits
    ]
