"""Tests for obase.isolated_task_runner (spawn-isolated task execution).

Upstreamed from the Tide consumer line; it is infrastructure (process
isolation + resource caps), so obase is the correct layer (SPEC §7).

These tests avoid the expensive/OS-specific paths (RLIMIT, RSS watchdog, real
``spawn`` children where avoidable) and pin the parts a caller actually depends
on: the status store round-trip, target resolution, and the runner's public
contract.
"""

from __future__ import annotations

import json

import pytest

from obase.isolated_task_runner import (
    InMemoryTaskStatusStore,
    JsonFileTaskStatusStore,
    TaskFailedError,
    TaskLimits,
    TaskRecord,
    TaskStatus,
    resolve_target,
)

# ---------------------------------------------------------------------------
# TaskRecord
# ---------------------------------------------------------------------------


def test_task_record_roundtrip():
    rec = TaskRecord(run_id="r1", target="mod:fn", status=TaskStatus.SUCCEEDED)
    again = TaskRecord.from_dict(rec.to_dict())
    assert again.run_id == rec.run_id
    assert again.target == rec.target
    assert again.status == rec.status


def test_task_record_done_flag():
    assert TaskRecord(run_id="r", target="t", status=TaskStatus.SUCCEEDED).done is True
    assert TaskRecord(run_id="r", target="t", status=TaskStatus.FAILED).done is True
    assert TaskRecord(run_id="r", target="t", status=TaskStatus.TIMEOUT).done is True
    assert TaskRecord(run_id="r", target="t", status=TaskStatus.RUNNING).done is False
    assert TaskRecord(run_id="r", target="t", status=TaskStatus.PENDING).done is False


def test_task_status_is_str_enum():
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.RUNNING == "running"
    assert TaskStatus.MEMORY_EXCEEDED == "memory_exceeded"


def test_task_limits_defaults_disable_everything():
    limits = TaskLimits()
    assert limits.timeout_s is None
    assert limits.memory_bytes is None
    assert limits.max_rss_bytes is None


def test_task_limits_is_frozen():
    import dataclasses

    limits = TaskLimits()
    with pytest.raises(dataclasses.FrozenInstanceError):
        limits.timeout_s = 5.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# InMemoryTaskStatusStore
# ---------------------------------------------------------------------------


def test_in_memory_store_save_and_load():
    store = InMemoryTaskStatusStore()
    rec = TaskRecord(run_id="a", target="m:f", status=TaskStatus.RUNNING)
    store.save(rec)
    assert store.load("a").run_id == "a"


def test_in_memory_store_load_missing_returns_none():
    assert InMemoryTaskStatusStore().load("nope") is None


def test_in_memory_store_list():
    store = InMemoryTaskStatusStore()
    store.save(TaskRecord(run_id="a", target="t", status=TaskStatus.PENDING))
    store.save(TaskRecord(run_id="b", target="t", status=TaskStatus.PENDING))
    assert {r.run_id for r in store.list()} == {"a", "b"}


# ---------------------------------------------------------------------------
# JsonFileTaskStatusStore
# ---------------------------------------------------------------------------


def test_json_store_save_and_load(tmp_path):
    store = JsonFileTaskStatusStore(tmp_path)
    rec = TaskRecord(run_id="job1", target="m:f", status=TaskStatus.SUCCEEDED)
    store.save(rec)
    loaded = store.load("job1")
    assert loaded is not None
    assert loaded.run_id == "job1"
    assert loaded.status == TaskStatus.SUCCEEDED


def test_json_store_load_missing_returns_none(tmp_path):
    assert JsonFileTaskStatusStore(tmp_path).load("absent") is None


def test_json_store_persists_across_instances(tmp_path):
    """The whole point: a client can reconnect by run_id after a restart."""
    JsonFileTaskStatusStore(tmp_path).save(
        TaskRecord(run_id="job2", target="m:f", status=TaskStatus.SUCCEEDED)
    )
    reopened = JsonFileTaskStatusStore(tmp_path)
    assert reopened.load("job2").run_id == "job2"


def test_json_store_list(tmp_path):
    store = JsonFileTaskStatusStore(tmp_path)
    store.save(TaskRecord(run_id="a", target="t", status=TaskStatus.SUCCEEDED))
    store.save(TaskRecord(run_id="b", target="t", status=TaskStatus.SUCCEEDED))
    assert {r.run_id for r in store.list()} == {"a", "b"}


def test_json_store_list_ignores_corrupt_files(tmp_path):
    store = JsonFileTaskStatusStore(tmp_path)
    store.save(TaskRecord(run_id="ok", target="t", status=TaskStatus.SUCCEEDED))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert [r.run_id for r in store.list()] == ["ok"]


def test_json_store_writes_valid_json(tmp_path):
    store = JsonFileTaskStatusStore(tmp_path)
    store.save(TaskRecord(run_id="j", target="t", status=TaskStatus.PENDING))
    payload = json.loads((tmp_path / "j.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "j"


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------


def test_resolve_target_from_module_level_callable():
    assert resolve_target(json.loads) == "json:loads"


def test_resolve_target_passes_through_a_dotted_spec():
    assert resolve_target("json:loads") == "json:loads"


def test_resolve_target_rejects_a_non_importable_callable():
    with pytest.raises((ValueError, TypeError)):
        resolve_target(lambda: None)  # noqa: E731 - lambdas have no dotted name


# ---------------------------------------------------------------------------
# TaskFailedError
# ---------------------------------------------------------------------------


def test_task_failed_error_carries_the_record():
    rec = TaskRecord(
        run_id="x", target="t", status=TaskStatus.FAILED, error_message="boom"
    )
    err = TaskFailedError(rec)
    assert err.record is rec
    assert "x" in str(err)
