"""Stratum cost tracker — simple module-level accumulator."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class CostRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


_records: list[CostRecord] = []
_lock = Lock()


def track(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    record = CostRecord(provider, model, input_tokens, output_tokens, cost_usd)
    with _lock:
        _records.append(record)
    from obase import logging as olog
    olog.emit(
        "cost_event",
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def total_cost() -> float:
    with _lock:
        return sum(r.cost_usd for r in _records)


def get_records() -> list[CostRecord]:
    with _lock:
        return list(_records)


def reset() -> None:
    with _lock:
        _records.clear()
