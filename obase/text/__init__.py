"""text — Text utilities: fuzzy matching and string helpers.

depends_on_external: rapidfuzz
"""

from __future__ import annotations

from obase.text.fuzzy_match import FuzzyMatchError, FuzzyMatchResult, fuzzy_match

__all__ = [
    "fuzzy_match",
    "FuzzyMatchResult",
    "FuzzyMatchError",
]
