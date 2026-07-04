"""Tests for obase.tracing ContextVar-based API."""

from __future__ import annotations

import asyncio

from obase.tracing import current_trace_id, span, start_trace


class TestStartTrace:
    def test_trace_id_set_within_context(self):
        assert current_trace_id() is None
        with start_trace() as tid:
            assert current_trace_id() == tid
            assert len(tid) == 16

    def test_trace_id_cleared_after_context(self):
        with start_trace():
            pass
        assert current_trace_id() is None

    def test_explicit_trace_id(self):
        with start_trace("fixed-id-123") as tid:
            assert tid == "fixed-id-123"
            assert current_trace_id() == "fixed-id-123"

    def test_nested_traces_restore_outer(self):
        with start_trace("outer"):
            with start_trace("inner"):
                assert current_trace_id() == "inner"
            assert current_trace_id() == "outer"

    def test_trace_id_persists_across_await(self):
        async def _inner():
            with start_trace("persist-test") as tid:
                await asyncio.sleep(0)  # yield control
                return current_trace_id() == tid

        result = asyncio.run(_inner())
        assert result is True

    def test_concurrent_tasks_isolated(self):
        """Each asyncio Task has its own ContextVar copy — no leakage."""
        results: dict[str, str | None] = {}

        async def _task(name: str, tid: str) -> None:
            with start_trace(tid):
                await asyncio.sleep(0.01)
                results[name] = current_trace_id()

        async def _main():
            await asyncio.gather(
                _task("t1", "trace-AAA"),
                _task("t2", "trace-BBB"),
            )

        asyncio.run(_main())
        assert results["t1"] == "trace-AAA"
        assert results["t2"] == "trace-BBB"

    def test_no_trace_id_outside_context(self):
        assert current_trace_id() is None


class TestSpan:
    def test_span_creates_with_current_trace(self):
        async def _run():
            with start_trace("span-test") as tid:
                async with span("my-op") as s:
                    assert s.trace_id == tid
                    assert s.name == "my-op"

        asyncio.run(_run())

    def test_span_ends_automatically(self):
        async def _run():
            async with span("op") as s:
                pass
            assert s.end_time is not None
            assert s.duration_ms >= 0

        asyncio.run(_run())

    def test_span_explicit_trace_id(self):
        async def _run():
            async with span("op", trace_id="explicit-tid") as s:
                assert s.trace_id == "explicit-tid"

        asyncio.run(_run())

    def test_span_attributes(self):
        async def _run():
            async with span("tagged-op") as s:
                s.attributes["key"] = "value"
            assert s.attributes["key"] == "value"

        asyncio.run(_run())

    def test_span_to_dict(self):
        async def _run():
            async with span("serializable") as s:
                pass
            d = s.to_dict()
            assert "trace_id" in d
            assert "span_id" in d
            assert d["name"] == "serializable"

        asyncio.run(_run())
