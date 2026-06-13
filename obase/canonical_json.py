"""obase.canonical_json — Deterministic JSON serialisation.

Produces stable bytes for any dict/list/primitive, including numpy scalars.
Sort keys ensures key-order independence; output is always UTF-8 encoded.
"""
from __future__ import annotations

import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for *obj*.

    numpy scalars/arrays are coerced to native Python types before
    serialisation so the output is identical regardless of the numeric
    backend in use.

    Args:
        obj: Any JSON-serialisable value (dict, list, str, int, float, bool,
            None) plus numpy integers, floats, and ndarrays.

    Returns:
        UTF-8 encoded JSON bytes with sorted keys.

    Raises:
        TypeError: If *obj* contains non-serialisable types other than numpy.
    """

    def _default(o: Any) -> Any:
        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            raise TypeError(f"Object of type {type(o).__name__} is not JSON serialisable") from None
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serialisable")

    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=_default).encode()
