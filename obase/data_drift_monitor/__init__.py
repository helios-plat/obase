"""data_drift_monitor — Monitor data distribution drift across sources."""
from __future__ import annotations
import time
from typing import Any

class DataDriftMonitorError(Exception):
    """Base error for data_drift_monitor."""

class DataDriftMonitor:
    """Monitor data distributions for drift detection.

    Example:
        >>> m = DataDriftMonitor(threshold=0.1)
        >>> m.check([1,2,3], [4,5,6])
        {'drifted': True, ...}
    """
    def __init__(self, *, threshold: float = 0.1) -> None:
        self._threshold = threshold
        self._history: list[dict] = []

    def check(self, reference: list[float], current: list[float]) -> dict:
        """Check for drift between reference and current distributions."""
        if not reference or not current:
            return {"drifted": False, "score": 0}
        ref_mean = sum(reference) / len(reference)
        cur_mean = sum(current) / len(current)
        score = abs(cur_mean - ref_mean) / max(abs(ref_mean), 1e-10)
        result = {"drifted": score > self._threshold, "score": round(score, 6), "timestamp": time.time()}
        self._history.append(result)
        return result

    @property
    def history(self) -> list[dict]:
        return self._history
