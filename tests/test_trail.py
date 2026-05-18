from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from obase.fs import FS
from obase.trail import Trail, load_trail, query_trail


class TestTrailEmit:
    def test_emit_creates_jsonl(self, tmp_path):
        trail = Trail("run1")
        trail.emit("test_event", key="val", num=42)
        assert trail.path.exists()
        line = json.loads(trail.path.read_text().strip())
        assert line["event"] == "test_event"
        assert line["key"] == "val"
        assert line["num"] == 42
        assert "ts" in line
        assert "run_id" in line

    def test_emit_flattens_kwargs(self, tmp_path):
        """kwargs go directly into top-level JSON, not nested in 'data'."""
        trail = Trail("run2")
        trail.emit("my_event", foo="bar", baz=99)
        line = json.loads(trail.path.read_text().strip())
        assert "data" not in line
        assert line["foo"] == "bar"
        assert line["baz"] == 99

    def test_emit_multiple_lines(self):
        trail = Trail("run3")
        trail.emit("e1", x=1)
        trail.emit("e2", x=2)
        lines = trail.path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "e1"
        assert json.loads(lines[1])["event"] == "e2"

    def test_save_stage_input_output(self):
        trail = Trail("run4")
        trail.save_stage_input("stage1", {"a": 1})
        trail.save_stage_output("stage1", {"b": 2})
        records = load_trail("run4")
        assert records[0]["event"] == "stage_input"
        assert records[1]["event"] == "stage_output"

    def test_finalize(self):
        trail = Trail("run5")
        trail.finalize("completed", extra="info")
        records = load_trail("run5")
        assert records[0]["state"] == "completed"
        assert records[0]["extra"] == "info"


class TestLoadTrail:
    def test_load_empty_run(self):
        records = load_trail("nonexistent-run-id-xyz")
        assert records == []

    def test_load_round_trip(self):
        trail = Trail("rt-run")
        trail.emit("event_a", value=1)
        trail.emit("event_b", value=2)
        records = load_trail("rt-run")
        assert len(records) == 2
        assert records[0]["value"] == 1
        assert records[1]["value"] == 2


class TestQueryTrail:
    def test_query_by_event_type(self, isolated_working_dir):
        trail1 = Trail("qrun1")
        trail1.emit("alpha", x=1)
        trail1.emit("beta", x=2)

        trail2 = Trail("qrun2")
        trail2.emit("alpha", x=3)

        results = query_trail(working_dir=isolated_working_dir, event_type="alpha")
        assert len(results) == 2
        assert all(r["event"] == "alpha" for r in results)

    def test_query_by_run_id_pattern(self, isolated_working_dir):
        Trail("abc-run").emit("ev", val=1)
        Trail("xyz-run").emit("ev", val=2)

        results = query_trail(working_dir=isolated_working_dir, run_id_pattern="abc")
        assert len(results) == 1
        assert results[0]["val"] == 1

    def test_query_by_after(self, isolated_working_dir):
        import time
        trail = Trail("time-run")
        trail.emit("early", val=0)
        time.sleep(0.05)
        cutoff = datetime.now(timezone.utc)
        time.sleep(0.05)
        trail.emit("late", val=1)

        results = query_trail(working_dir=isolated_working_dir, after=cutoff)
        assert len(results) == 1
        assert results[0]["val"] == 1

    def test_query_returns_sorted(self, isolated_working_dir):
        t1 = Trail("sort-run-a")
        t1.emit("ev", seq=1)
        t2 = Trail("sort-run-b")
        t2.emit("ev", seq=2)

        results = query_trail(working_dir=isolated_working_dir)
        seqs = [r["seq"] for r in results]
        assert seqs == sorted(seqs)
