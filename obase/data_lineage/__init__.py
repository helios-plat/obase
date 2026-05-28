"""data_lineage — Track data transformation lineage."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any


class DataLineageError(Exception):
    """Base error for data_lineage."""


class DataLineage:
    """Track data transformation lineage (source → transform → output).

    Example:
        >>> lineage = DataLineage()
        >>> lineage.record("binance_api", "normalize_ohlcv", "abc123")
        >>> len(lineage.records)
        1
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def record(
        self,
        source: str,
        transform: str,
        output_hash: str,
        *,
        metadata: dict | None = None,
    ) -> None:
        """Record a lineage step.

        Args:
            source: Data source identifier.
            transform: Transformation applied.
            output_hash: Hash of output data.
            metadata: Optional extra metadata.
        """
        self._records.append({
            "timestamp": time.time(),
            "source": source,
            "transform": transform,
            "output_hash": output_hash,
            "metadata": metadata,
        })

    @property
    def records(self) -> list[dict[str, Any]]:
        """Get all lineage records."""
        return self._records

    @staticmethod
    def hash_data(data: Any) -> str:
        """Compute SHA-256 hash of data for lineage tracking.

        Args:
            data: Data to hash (JSON-serializable).

        Returns:
            64-char hex hash.
        """
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()
