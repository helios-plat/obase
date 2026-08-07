"""obase.loop_event_store 行为测试矩阵。

覆盖: 追加/重放 / 链式校验 (篡改、截断、断链) / 去重 / 并发 (多进程) /
迁移机制 / QuotaTracker (超支暂停恢复 + 事件化)。
"""

from __future__ import annotations

import json
import uuid

import pytest

from obase.exceptions import BudgetExceeded, PauseRequested
from obase.loop_event_store import (
    _GENESIS,
    EVENT_SCHEMA_VERSION,
    AppendOnlyEventStore,
    LoopStoreError,
    QuotaTracker,
    _line_hash,
)

# ---------------------------------------------------------------------------
# 追加 / 重放 / 校验
# ---------------------------------------------------------------------------


async def test_append_and_replay(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    for i in range(10):
        await store.append("todo_updated", {"i": i, "status": "done"})
    events = store.replay()
    assert len(events) == 10
    assert [e["seq"] for e in events] == list(range(1, 11))
    assert all(e["v"] == EVENT_SCHEMA_VERSION for e in events)
    assert all(e["type"] == "todo_updated" for e in events)
    assert store.count() == 10


async def test_append_with_payload_roundtrip(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    payload = {"goal_id": "g1", "title": "写 API", "tags": ["a", "b"]}
    row = await store.append("goal_added", payload)
    assert row["type"] == "goal_added"
    assert row["payload"] == payload
    assert store.replay()[0]["payload"] == payload


async def test_verify_ok_empty_and_populated(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    assert store.verify().ok
    assert store.verify().count == 0
    await store.append("goal_added", {"goal_id": "g1"})
    result = store.verify()
    assert result.ok
    assert result.count == 1
    assert result.first_seq == 1
    assert result.last_seq == 1


async def test_verify_detects_payload_tamper(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    await store.append("goal_added", {"goal_id": "g1"})
    await store.append("todo_updated", {"todo_id": "t1"})
    # 篡改中间一行的 payload (不重算 hash)
    path = tmp_path / "e.jsonl"
    lines = path.read_text().strip().splitlines()
    tampered = json.loads(lines[0])
    tampered["payload"] = {"goal_id": "EVIL"}
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n")
    result = store.verify()
    assert not result.ok
    assert "hash mismatch" in result.error
    assert result.line_no == 1


async def test_verify_detects_hash_field_tamper(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    await store.append("goal_added", {"goal_id": "g1"})
    await store.append("todo_updated", {"todo_id": "t1"})
    path = tmp_path / "e.jsonl"
    lines = path.read_text().strip().splitlines()
    tampered = json.loads(lines[0])
    tampered["hash"] = "0" * 64
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n")
    result = store.verify()
    assert not result.ok
    assert "hash mismatch" in result.error


async def test_verify_detects_chain_break(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    await store.append("goal_added", {"goal_id": "g1"})
    await store.append("todo_updated", {"todo_id": "t1"})
    path = tmp_path / "e.jsonl"
    lines = path.read_text().strip().splitlines()
    tampered = json.loads(lines[1])
    tampered["prev_hash"] = "0" * 64  # 断链
    lines[1] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n")
    result = store.verify()
    assert not result.ok
    assert "prev_hash mismatch" in result.error


async def test_verify_detects_missing_middle_rows(tmp_path):
    """删除中间行 -> seq 断裂, verify 必须发现。"""
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    for i in range(5):
        await store.append("todo_updated", {"i": i})
    path = tmp_path / "e.jsonl"
    lines = path.read_text().strip().splitlines()
    lines = lines[:1] + lines[3:]  # 保留 seq 1,4,5 → 2,3 丢失
    path.write_text("\n".join(lines) + "\n")
    result = store.verify()
    assert not result.ok
    # 删中间行会同时断链 (prev_hash mismatch) 和断序 (seq discontinuity),
    # 校验顺序先查 prev_hash, 两种错误都算检测成功。
    assert "prev_hash mismatch" in result.error or "seq discontinuity" in result.error


async def test_tail_truncation_self_consistent(tmp_path):
    """尾部截断在链内部是自洽的 (verify ok); 严格检测需外部基准。

    链式 hash 只能证明"内部无篡改/无空洞", 无法证明"没有丢尾部"。
    尾部截断由投影层持有期望 last_seq 来发现 —— 这是事件溯源的标准分工:
    verify 保一致性, 投影/恢复时对比期望序列号保完整性。
    """
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    for i in range(5):
        await store.append("todo_updated", {"i": i})
    path = tmp_path / "e.jsonl"
    lines = path.read_text().strip().splitlines()[:-2]
    path.write_text("\n".join(lines) + "\n")
    assert store.verify().ok  # 剩余 3 行自洽
    assert store.count() == 3
    # 外部基准发现截断: 投影层若期望 last_seq=5, 实际 3 → 截断
    assert store.latest()["seq"] == 3


async def test_replay_raises_on_corrupt(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    await store.append("goal_added", {"goal_id": "g1"})
    path = tmp_path / "e.jsonl"
    path.write_text('{"broken json\n', encoding="utf-8")
    with pytest.raises(LoopStoreError):
        store.replay()


async def test_latest_returns_tail(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    await store.append("goal_added", {"goal_id": "g1"})
    await store.append("todo_updated", {"todo_id": "t1"})
    tail = store.latest()
    assert tail is not None
    assert tail["type"] == "todo_updated"
    assert tail["seq"] == 2


# ---------------------------------------------------------------------------
# 去重 / 幂等
# ---------------------------------------------------------------------------


async def test_dedupe_same_id_appends_once(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    r1 = await store.append("goal_added", {"goal_id": "g1"}, dedupe_id="goal-g1")
    r2 = await store.append("goal_added", {"goal_id": "g1"}, dedupe_id="goal-g1")
    assert r1 == r2  # 幂等: 返回同一行
    assert store.count() == 1
    assert store.verify().ok


async def test_dedupe_distinct_ids_append_all(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "e.jsonl")
    for i in range(5):
        await store.append("todo_updated", {"i": i}, dedupe_id=f"todo-{i}")
    assert store.count() == 5


# ---------------------------------------------------------------------------
# 并发 (多进程 flock)
# ---------------------------------------------------------------------------


def _append_worker(path: str, worker_id: int, n: int) -> int:
    import asyncio

    from obase.loop_event_store import AppendOnlyEventStore

    async def run() -> int:
        store = AppendOnlyEventStore(path)
        for i in range(n):
            await store.append("todo_updated", {"worker": worker_id, "i": i}, fsync=True)
        return store.count()

    return asyncio.run(run())


def test_concurrent_append_multiprocess(tmp_path):
    import multiprocessing as mp

    path = tmp_path / "conc.jsonl"
    with mp.Pool(2) as pool:
        results = pool.starmap(
            _append_worker,
            [(str(path), 0, 20), (str(path), 1, 20)],
        )
    store = AppendOnlyEventStore(path)
    # 各 worker 完成时刻的瞬时 count 受竞态影响, 但至少包含自己的写入
    assert all(r >= 20 for r in results)
    assert store.count() == 40
    result = store.verify()
    assert result.ok, result.error
    assert result.count == 40
    seqs = [e["seq"] for e in store.replay()]
    assert seqs == list(range(1, 41))  # seq 全局单调无重复


# ---------------------------------------------------------------------------
# 迁移机制
# ---------------------------------------------------------------------------


async def test_migrate_v1_to_v2_rewrites_chain(tmp_path):
    from obase import loop_event_store as les

    # 手工构造 v1 事件文件 (模拟历史数据)
    path = tmp_path / "legacy.jsonl"
    rows = []
    prev = _GENESIS
    for i in range(1, 4):
        row = {
            "v": 1,
            "seq": i,
            "id": str(uuid.uuid4()),
            "ts": 1000.0 + i,
            "type": "todo_updated",
            "payload": {"i": i},
            "prev_hash": prev,
        }
        row["hash"] = _line_hash(prev, i, row["id"], row["ts"], "todo_updated", row["payload"])
        prev = row["hash"]
        rows.append(row)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    # 注册 v1 -> v2 迁移
    def upgrade(row: dict) -> dict:
        row = dict(row)
        row["payload"] = {**row["payload"], "migrated": True}
        return row

    les._MIGRATIONS[1] = upgrade
    try:
        store = les.AppendOnlyEventStore(path, schema_version=2)
        migrated = store.migrate(2)
        assert migrated == 3
        events = store.replay()
        assert all(e["v"] == 2 for e in events)
        assert all(e["payload"]["migrated"] is True for e in events)
        assert store.verify().ok
        # 迁移后可继续追加 v2 事件, 链不断
        await store.append("goal_added", {"goal_id": "g1"})
        assert store.verify().ok
        assert store.count() == 4
    finally:
        les._MIGRATIONS.pop(1, None)


async def test_migrate_no_registration_raises(tmp_path):
    from obase import loop_event_store as les

    path = tmp_path / "legacy.jsonl"
    row = {
        "v": 1,
        "seq": 1,
        "id": str(uuid.uuid4()),
        "ts": 1000.0,
        "type": "todo_updated",
        "payload": {},
        "prev_hash": _GENESIS,
    }
    row["hash"] = _line_hash(_GENESIS, 1, row["id"], row["ts"], "todo_updated", {})
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    store = les.AppendOnlyEventStore(path, schema_version=3)  # 跳到 v3, 无 v1->v2 迁移
    with pytest.raises(LoopStoreError):
        store.migrate(3)


# ---------------------------------------------------------------------------
# QuotaTracker
# ---------------------------------------------------------------------------


async def test_quota_budget_exceeded_pause_resume(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "q.jsonl")
    quota = QuotaTracker(budget_usd=1.0, goal_id="g1", store=store)
    assert quota.remaining_usd == 1.0
    await quota.record_usage(0.6, note="round 1")
    assert quota.spent_usd == pytest.approx(0.6)
    with pytest.raises(BudgetExceeded):
        await quota.record_usage(0.5, note="round 2")  # 1.1 > 1.0
    assert quota.paused
    # 暂停后不能再记录
    with pytest.raises(PauseRequested):
        await quota.record_usage(0.01)
    # 充值恢复: 提高预算到 2.0 后再继续
    await quota.resume(new_budget=2.0)
    assert not quota.paused
    await quota.record_usage(0.1, note="round 3")
    assert quota.spent_usd == pytest.approx(1.2)
    assert quota.budget_usd == pytest.approx(2.0)

    # 事件流: consumed(0.6) -> consumed(1.1) -> paused -> resumed -> consumed(1.2)
    types = [e["type"] for e in store.replay()]
    assert types == [
        "quota_consumed",
        "quota_consumed",
        "quota_paused",
        "quota_resumed",
        "quota_consumed",
    ]
    assert store.verify().ok


async def test_quota_check_sync_guard(tmp_path):
    quota = QuotaTracker(budget_usd=0.5)
    await quota.record_usage(0.3)
    quota.check()  # 0.3 <= 0.5 OK
    quota._spent = 0.6  # 注入超支 (模拟外部记账对齐后)
    with pytest.raises(BudgetExceeded):
        quota.check()


async def test_quota_summary_and_events_align(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "q.jsonl")
    quota = QuotaTracker(budget_usd=10.0, goal_id="g9", store=store)
    await quota.record_usage(1.0)
    await quota.record_usage(2.0)
    summary = quota.summary()
    assert summary["goal_id"] == "g9"
    assert summary["spent_usd"] == pytest.approx(3.0)
    assert summary["remaining_usd"] == pytest.approx(7.0)
    assert summary["paused"] is False
    events = store.replay()
    assert all(e["payload"]["goal_id"] == "g9" for e in events)
    assert [e["payload"]["cost_usd"] for e in events] == [1.0, 2.0]


async def test_quota_without_store_is_usable(tmp_path):
    quota = QuotaTracker(budget_usd=5.0, goal_id="g1")
    await quota.record_usage(1.0)
    assert quota.spent_usd == pytest.approx(1.0)
    with pytest.raises(BudgetExceeded):
        await quota.record_usage(9.0)


async def test_quota_restore_aligns_runtime(tmp_path):
    """restore: 从事件流投影对齐运行时配额 (跨进程恢复, 不写事件)。"""
    store = AppendOnlyEventStore(tmp_path / "q.jsonl")
    quota = QuotaTracker(budget_usd=5.0, goal_id="g1", store=store)
    await quota.record_usage(1.0)
    await quota.record_usage(2.0)

    # 模拟新进程: 全新 QuotaTracker, 从投影恢复
    fresh = QuotaTracker(budget_usd=5.0, goal_id="g1", store=store)
    fresh.restore(3.0, budget_usd=5.0, paused=False)
    assert fresh.spent_usd == pytest.approx(3.0)
    assert fresh.remaining_usd == pytest.approx(2.0)
    assert fresh.paused is False
    # 恢复后可继续记账 (record_usage 写新事件)
    await fresh.record_usage(0.5)
    assert fresh.spent_usd == pytest.approx(3.5)
    # 事件流: restore 本身不写事件, 但 record_usage 写 —— 共 3 条
    assert store.count() == 3


async def test_quota_restore_paused_state(tmp_path):
    store = AppendOnlyEventStore(tmp_path / "q.jsonl")
    quota = QuotaTracker(budget_usd=1.0, goal_id="g1", store=store)
    await quota.record_usage(0.6)
    with pytest.raises(BudgetExceeded):
        await quota.record_usage(0.5)  # 超支 → paused

    fresh = QuotaTracker(budget_usd=1.0, goal_id="g1", store=store)
    fresh.restore(1.1, budget_usd=1.0, paused=True)
    assert fresh.paused is True
    with pytest.raises(PauseRequested):
        await fresh.record_usage(0.01)
    # 充值恢复
    await fresh.resume(new_budget=2.0)
    assert fresh.paused is False
    await fresh.record_usage(0.1)
    assert fresh.spent_usd == pytest.approx(1.2)
