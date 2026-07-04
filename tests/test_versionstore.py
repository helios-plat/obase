"""Tests for obase.versionstore."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from obase.versionstore import jsonl_append, jsonl_latest, jsonl_read


class TestJsonlAppend:
    async def test_creates_file(self, tmp_path: Path) -> None:
        p = tmp_path / "new.jsonl"
        await jsonl_append(path=p, entry={"id": "a", "v": 1})
        assert p.exists()
        assert p.read_text().strip() == '{"id": "a", "v": 1}'

    async def test_appends_to_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        await jsonl_append(path=p, entry={"id": "a"})
        await jsonl_append(path=p, entry={"id": "b"})
        lines = p.read_text().strip().split("\n")
        assert len(lines) == 2

    async def test_creates_parents(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "dir" / "log.jsonl"
        await jsonl_append(path=p, entry={"x": 1})
        assert p.exists()


class TestJsonlRead:
    def test_reads_multiple_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text('{"a":1}\n{"b":2}\n{"c":3}\n')
        entries = jsonl_read(path=p)
        assert len(entries) == 3
        assert entries[0] == {"a": 1}

    def test_skip_malformed(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text('{"ok":1}\nBAD LINE\n{"ok":2}\n')
        entries = jsonl_read(path=p, skip_malformed=True)
        assert len(entries) == 2

    def test_malformed_raises_when_not_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text("BAD\n")
        with pytest.raises(json.JSONDecodeError):
            jsonl_read(path=p, skip_malformed=False)

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            jsonl_read(path=tmp_path / "missing.jsonl")

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        entries = jsonl_read(path=p)
        assert entries == []


class TestJsonlLatest:
    def test_latest_by_key(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text('{"id":"a","v":1}\n{"id":"a","v":2}\n{"id":"b","v":3}\n')
        latest = jsonl_latest(path=p, by_key="id")
        assert latest == {"id": "b", "v": 3}

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert jsonl_latest(path=p, by_key="id") is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert jsonl_latest(path=tmp_path / "nope.jsonl", by_key="id") is None

    def test_key_not_present_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text('{"other":"field"}\n')
        assert jsonl_latest(path=p, by_key="id") is None

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text('{"id":"a","v":1}\nBAD LINE\n{"id":"b","v":2}\n')
        latest = jsonl_latest(path=p, by_key="id")
        assert latest == {"id": "b", "v": 2}

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text('{"id":"a"}\n\n\n{"id":"b"}\n')
        latest = jsonl_latest(path=p, by_key="id")
        assert latest == {"id": "b"}
