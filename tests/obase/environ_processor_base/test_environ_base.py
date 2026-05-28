"""Tests for obase.environ_processor_base."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from obase.environ_processor_base import BaseEnvironProcessor, EnvironProcessorError


class _MockDiagnostic:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def incr(self, key: str) -> None:
        self.calls.append(("incr", key))

    async def set(self, key: str, value: str) -> None:
        self.calls.append(("set", key))


class _GoodProcessor(BaseEnvironProcessor):
    domain = "test"
    interval_seconds = 1

    async def load_external(self) -> dict[str, Any]:
        return {"raw": 1}

    async def compute_environ(self, external_data: dict[str, Any]) -> dict[str, Any]:
        return {"processed": external_data["raw"] * 2}

    async def write_environ(self, environ_data: dict[str, Any]) -> None:
        pass


class _EmptyLoadProcessor(BaseEnvironProcessor):
    domain = "empty"

    async def load_external(self) -> dict[str, Any]:
        return {}

    async def compute_environ(self, external_data: dict[str, Any]) -> dict[str, Any]:
        return {"x": 1}

    async def write_environ(self, environ_data: dict[str, Any]) -> None:
        pass


class _FailComputeProcessor(BaseEnvironProcessor):
    domain = "fail"

    async def load_external(self) -> dict[str, Any]:
        return {"data": 1}

    async def compute_environ(self, external_data: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("compute error")

    async def write_environ(self, environ_data: dict[str, Any]) -> None:
        pass


@pytest.mark.asyncio
async def test_run_once_success():
    diag = _MockDiagnostic()
    p = _GoodProcessor(diagnostic_writer=diag, startup_delay_seconds=0)
    result = await p.run_once()
    assert result is True
    assert any("last_run_ts" in k for _, k in diag.calls)


@pytest.mark.asyncio
async def test_run_once_empty_load_skips():
    p = _EmptyLoadProcessor(startup_delay_seconds=0)
    result = await p.run_once()
    assert result is False


@pytest.mark.asyncio
async def test_run_once_compute_failure():
    diag = _MockDiagnostic()
    p = _FailComputeProcessor(diagnostic_writer=diag, startup_delay_seconds=0)
    result = await p.run_once()
    assert result is False
    assert any("error_count" in k for _, k in diag.calls)


@pytest.mark.asyncio
async def test_run_cancelled():
    p = _GoodProcessor(interval_seconds=0, startup_delay_seconds=0)
    task = asyncio.create_task(p.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_constructor_overrides():
    p = _GoodProcessor(domain="custom", interval_seconds=42, startup_delay_seconds=0)
    assert p.domain == "custom"
    assert p.interval_seconds == 42


def test_environ_processor_error_is_exception():
    assert issubclass(EnvironProcessorError, Exception)
