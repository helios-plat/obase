"""Tests for obase.collector_base."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from obase.collector_base import BaseExternalCollector, CollectorError


class _MockDiagnostic:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def incr(self, key: str) -> None:
        self.calls.append(("incr", key))

    async def set(self, key: str, value: str) -> None:
        self.calls.append(("set", key))


class _GoodCollector(BaseExternalCollector):
    source = "test_source"
    interval_seconds = 1

    async def fetch(self) -> dict[str, Any]:
        return {"data": 42}

    async def write(self, data: dict[str, Any]) -> None:
        pass


class _FailFetchCollector(BaseExternalCollector):
    source = "fail_fetch"

    async def fetch(self) -> dict[str, Any]:
        raise RuntimeError("fetch error")

    async def write(self, data: dict[str, Any]) -> None:
        pass


class _FailWriteCollector(BaseExternalCollector):
    source = "fail_write"

    async def fetch(self) -> dict[str, Any]:
        return {"ok": True}

    async def write(self, data: dict[str, Any]) -> None:
        raise RuntimeError("write error")


@pytest.mark.asyncio
async def test_run_once_success():
    diag = _MockDiagnostic()
    c = _GoodCollector(diagnostic_writer=diag)
    result = await c.run_once()
    assert result is True
    assert any("fetch_count" in k for _, k in diag.calls)


@pytest.mark.asyncio
async def test_run_once_fetch_failure_retries():
    diag = _MockDiagnostic()
    c = _FailFetchCollector(diagnostic_writer=diag)
    result = await c.run_once()
    assert result is False
    assert any("error_count" in k for _, k in diag.calls)


@pytest.mark.asyncio
async def test_run_once_write_failure():
    diag = _MockDiagnostic()
    c = _FailWriteCollector(diagnostic_writer=diag)
    result = await c.run_once()
    assert result is False


@pytest.mark.asyncio
async def test_run_cancelled():
    c = _GoodCollector(interval_seconds=0)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_constructor_overrides():
    c = _GoodCollector(source="override", interval_seconds=99)
    assert c.source == "override"
    assert c.interval_seconds == 99


def test_collector_error_is_exception():
    assert issubclass(CollectorError, Exception)
