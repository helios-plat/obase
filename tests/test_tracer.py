"""Tests for obase.observability.tracer."""

from __future__ import annotations

import pytest

from obase.observability.tracer import Span, Tracer, get_tracer


class TestGetTracer:
    def test_returns_tracer_instance(self):
        t = get_tracer()
        assert isinstance(t, Tracer)

    def test_returns_same_instance_on_repeated_calls(self):
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2

    def test_custom_service_name_on_first_call(self):
        # Reset and create with custom name
        import obase.observability.tracer as mod

        original = mod._default_tracer
        mod._default_tracer = None
        try:
            t = get_tracer("my-service")
            assert t.service_name == "my-service"
        finally:
            mod._default_tracer = original


class TestTracerSpanContextManager:
    def setup_method(self):
        self.tracer = Tracer("test-service")

    def test_span_context_manager_creates_span(self):
        with self.tracer.span("test.op") as s:
            assert isinstance(s, Span)

    def test_span_name_matches(self):
        with self.tracer.span("my.operation") as s:
            assert s.name == "my.operation"

    def test_span_ends_after_context_exits(self):
        with self.tracer.span("test.op") as s:
            pass
        assert s.end_time is not None

    def test_span_duration_ms_positive_after_end(self):
        with self.tracer.span("test.op") as s:
            pass
        assert s.duration_ms is not None
        assert s.duration_ms >= 0.0

    def test_initial_attributes_set_via_kwargs(self):
        with self.tracer.span("test.op", url="http://example.com", method="GET") as s:
            assert s.attributes["url"] == "http://example.com"
            assert s.attributes["method"] == "GET"

    def test_get_spans_contains_span(self):
        with self.tracer.span("recorded.op") as s:
            pass
        spans = self.tracer.get_spans()
        assert s in spans

    def test_multiple_spans_recorded(self):
        with self.tracer.span("op.one"):
            pass
        with self.tracer.span("op.two"):
            pass
        assert len(self.tracer.get_spans()) == 2

    def test_exception_sets_status_error(self):
        with pytest.raises(ValueError):
            with self.tracer.span("failing.op") as s:
                raise ValueError("boom")
        assert s.status == "error"

    def test_exception_sets_error_message_attribute(self):
        with pytest.raises(RuntimeError):
            with self.tracer.span("failing.op") as s:
                raise RuntimeError("something went wrong")
        assert s.attributes["error.message"] == "something went wrong"

    def test_exception_still_propagates(self):
        with pytest.raises(KeyError):
            with self.tracer.span("op"):
                raise KeyError("missing")

    def test_nested_spans_have_correct_parent(self):
        with self.tracer.span("outer") as outer:
            with self.tracer.span("inner") as inner:
                pass
        assert inner.parent is outer
        assert outer.parent is None

    def test_clear_removes_all_spans(self):
        with self.tracer.span("op"):
            pass
        self.tracer.clear()
        assert self.tracer.get_spans() == []

    def test_get_spans_returns_copy(self):
        with self.tracer.span("op"):
            pass
        spans1 = self.tracer.get_spans()
        spans2 = self.tracer.get_spans()
        assert spans1 is not spans2


class TestSpan:
    def test_set_attribute_stores_value(self):
        s = Span("test")
        s.set_attribute("key", "value")
        assert s.attributes["key"] == "value"

    def test_set_attribute_returns_self(self):
        s = Span("test")
        result = s.set_attribute("k", "v")
        assert result is s

    def test_add_event_appends_to_events(self):
        s = Span("test")
        s.add_event("my.event", {"count": 5})
        assert len(s.events) == 1
        assert s.events[0]["name"] == "my.event"
        assert s.events[0]["attributes"]["count"] == 5

    def test_add_event_returns_self(self):
        s = Span("test")
        result = s.add_event("ev")
        assert result is s

    def test_add_event_without_attributes(self):
        s = Span("test")
        s.add_event("ev")
        assert s.events[0]["attributes"] == {}

    def test_set_status_error(self):
        s = Span("test")
        s.set_status("error")
        assert s.status == "error"

    def test_set_status_cancelled(self):
        s = Span("test")
        s.set_status("cancelled")
        assert s.status == "cancelled"

    def test_set_status_returns_self(self):
        s = Span("test")
        result = s.set_status("ok")
        assert result is s

    def test_default_status_is_ok(self):
        s = Span("test")
        assert s.status == "ok"

    def test_end_sets_end_time(self):
        s = Span("test")
        assert s.end_time is None
        s.end()
        assert s.end_time is not None

    def test_duration_ms_none_before_end(self):
        s = Span("test")
        assert s.duration_ms is None

    def test_duration_ms_positive_after_end(self):
        s = Span("test")
        s.end()
        assert s.duration_ms >= 0.0

    def test_parent_is_none_by_default(self):
        s = Span("test")
        assert s.parent is None

    def test_parent_assigned_correctly(self):
        parent = Span("parent")
        child = Span("child", parent=parent)
        assert child.parent is parent
