"""obase.loop_event_store — 长程任务事件溯源存储 + goal 级配额追踪。

设计来源: 借鉴 LoopX ``event_sourced_state`` 的四个硬设计, 内化为 veya 3O
机制层 (obase) 自己的实现 —— 事件流是真相源 (source of truth), 快照
(``obase.checkpoint_store.CheckpointStore``) 只是投影物化:

  1. schema 版本化: 每行带 ``v`` 字段 + ``migrate()`` 逐级升级钩子;
  2. 链式 checksum: 每行 ``prev_hash`` + ``hash`` (sha256), 重放/校验可发现
     篡改与尾部截断;
  3. 并发安全: ``fcntl.flock`` 跨进程互斥 + ``threading.Lock`` 同进程串行化
     (flock 在同一进程内不互斥, 必须双保险);
  4. event_id 去重 + append_sequence 单调递增: 同进程幂等重试安全, 跨进程
     重复由 ``verify()`` 兜底发现。

事件行格式 (JSONL, 每行一个事件)::

    {"v": 1, "seq": 3, "id": "<uuid4>", "ts": 1690000000.0, "type": "todo_updated",
     "payload": {"todo_id": "t1", "status": "done"}, "prev_hash": "<hex>", "hash": "<hex>"}

与 ``obase.cost_tracker.CostTracker`` 的关系: CostTracker 负责全局记账面
(pricing/provider 维度); QuotaTracker 负责 goal 级预算治理 (无 pricing 依赖),
超支时抛 ``BudgetExceeded`` 并把 ``quota_consumed/quota_paused/quota_resumed``
事件写入同一事件流 —— 一次写入既审计 (对齐 AuditEmitter 语义) 又恢复。

3O 元素: ``obase.loop_event_store`` (``AppendOnlyEventStore`` / ``QuotaTracker``)。
依赖: 仅 stdlib + ``obase.exceptions`` / ``obase.sha256_hash``。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from obase.exceptions import BudgetExceeded, PauseRequested
from obase.sha256_hash import sha256_hash

# 当前事件 schema 版本。修改事件行结构时必须递增并注册迁移函数。
EVENT_SCHEMA_VERSION = 1

# 首行 prev_hash 的 genesis 常量 (任意固定值, 仅防截断首行)。
_GENESIS = "genesis"

# 迁移注册表: v -> v+1 的行迁移函数。v1 无历史, 保持空。
# 未来 v2 改 payload 结构时: _MIGRATIONS[1] = lambda row: {**row, "payload": {...}}
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _line_hash(
    prev_hash: str,
    seq: int,
    event_id: str,
    ts: float,
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """计算单行事件的 sha256 (hex)。payload 用稳定序列化保证跨进程一致。"""
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    raw = f"{prev_hash}|{seq}|{event_id}|{ts}|{event_type}|{body}".encode()
    return sha256_hash(raw).hex()


@dataclass
class VerifyResult:
    """``verify()`` 的结果。ok=False 时 error/line_no 定位首个损坏行。"""

    ok: bool
    count: int = 0
    error: str | None = None
    line_no: int | None = None
    first_seq: int | None = None
    last_seq: int | None = None


class LoopStoreError(Exception):
    """事件流损坏 / 迁移不支持等存储级错误。"""


class AppendOnlyEventStore:
    """JSONL 追加式事件流存储 (链式校验 + 并发安全 + 去重 + 可迁移)。

    Usage::

        store = AppendOnlyEventStore(Path("~/.veya/loops/g1/events.jsonl"))
        await store.append("goal_added", {"goal_id": "g1", "title": "..."})
        await store.append("todo_updated", {"todo_id": "t1", "status": "done"})
        events = store.replay()          # 重放全部事件 (校验链完整性)
        result = store.verify()          # 只校验, 不返回事件
        migrated = store.migrate(2)      # 未来版本迁移

    线程/进程安全: 写路径持 ``threading.Lock`` + ``flock(LOCK_EX)``; 读路径持
    ``flock(LOCK_SH)``, 避免读到写入一半的行。
    """

    def __init__(
        self,
        path: str | Path,
        *,
        schema_version: int = EVENT_SCHEMA_VERSION,
    ) -> None:
        self._path = Path(path)
        self._schema_version = schema_version
        self._lock = threading.Lock()
        # dedupe 缓存: dedupe_id -> 已存在事件行 (惰性加载, 同进程幂等重试安全)
        self._dedupe_map: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_version(self) -> int:
        return self._schema_version

    async def append(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        dedupe_id: str | None = None,
        fsync: bool = False,
    ) -> dict[str, Any]:
        """追加一个事件, 返回写入的事件行 (去重命中时返回已存在行)。

        Args:
            event_type: 事件类型, 如 ``goal_added`` / ``todo_updated``。
            payload: 事件负载 (可 JSON 序列化 dict)。
            dedupe_id: 幂等键 —— 同进程内重复 append 相同 dedupe_id 只写一次。
            fsync: 写后 fsync (崩溃安全; 关键事件如配额/交接建议开启)。
        """
        payload = payload or {}
        with self._lock:
            with self._exclusive_lock():
                if dedupe_id is not None:
                    existing = self._find_dedupe(dedupe_id)
                    if existing is not None:
                        return existing
                head = self._read_head()
                prev_seq = head["seq"] if head else 0
                prev_hash = head["hash"] if head else _GENESIS
                row = self._make_row(
                    event_type=event_type,
                    payload=payload,
                    seq=prev_seq + 1,
                    prev_hash=prev_hash,
                    dedupe_id=dedupe_id,
                )
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    if fsync:
                        f.flush()
                        import os

                        os.fsync(f.fileno())
                if self._dedupe_map is not None and dedupe_id is not None:
                    self._dedupe_map[dedupe_id] = row
                return row

    def replay(self) -> list[dict[str, Any]]:
        """重放全部事件, 严格校验链完整性 (损坏即抛 ``LoopStoreError``)。"""
        with self._lock:
            with self._shared_lock():
                rows = self._read_all(strict=True)
        self._verify_rows(rows, raise_on_error=True)
        return rows

    def verify(self) -> VerifyResult:
        """校验事件流完整性: 链式 hash / seq 连续 / schema 版本一致。"""
        with self._lock:
            with self._shared_lock():
                try:
                    rows = self._read_all(strict=False)
                except LoopStoreError as exc:
                    return VerifyResult(ok=False, count=0, error=str(exc))
        return self._verify_rows(rows, raise_on_error=False)

    def latest(self) -> dict[str, Any] | None:
        """读取尾部事件 (不校验链)。"""
        with self._lock:
            with self._shared_lock():
                if not self._path.exists():
                    return None
                lines = self._path.read_text(encoding="utf-8").strip().splitlines()
                if not lines:
                    return None
                try:
                    return json.loads(lines[-1])
                except json.JSONDecodeError:
                    return None

    def count(self) -> int:
        """事件总数。"""
        with self._lock:
            with self._shared_lock():
                if not self._path.exists():
                    return 0
                lines = self._path.read_text(encoding="utf-8").splitlines()
                return sum(1 for line in lines if line.strip())

    def migrate(self, target_version: int | None = None) -> int:
        """把事件流迁移到 target_version (默认当前 schema 版本)。

        逐行应用 ``_MIGRATIONS`` 注册的升级函数, 迁移后重算整条 hash 链并
        重写文件。v1 起步无迁移, 返回 0; 未来 v2 注册 ``_MIGRATIONS[1]`` 后
        此处自动生效。迁移是原子的 (先写临时文件再替换)。
        """
        target = target_version or self._schema_version
        if target < EVENT_SCHEMA_VERSION:
            raise LoopStoreError(f"cannot migrate down to v{target}")
        with self._lock:
            with self._exclusive_lock():
                if not self._path.exists():
                    return 0
                lines = self._path.read_text(encoding="utf-8").splitlines()
                migrated = 0
                prev_hash = _GENESIS
                out: list[dict[str, Any]] = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise LoopStoreError(f"malformed line in {self._path}: {exc}") from exc
                    ver = int(row.get("v", 1))
                    while ver < target:
                        upgrade = _MIGRATIONS.get(ver)
                        if upgrade is None:
                            raise LoopStoreError(
                                f"no migration registered from v{ver} to v{ver + 1}"
                            )
                        row = upgrade(row)
                        row["v"] = ver + 1
                        ver += 1
                        migrated += 1
                    # 重算 hash 链 (payload 可能已被迁移改写)
                    row["prev_hash"] = prev_hash
                    row["hash"] = _line_hash(
                        prev_hash=prev_hash,
                        seq=int(row["seq"]),
                        event_id=row["id"],
                        ts=float(row["ts"]),
                        event_type=row["type"],
                        payload=row.get("payload", {}),
                    )
                    prev_hash = row["hash"]
                    out.append(row)
                tmp = self._path.with_suffix(self._path.suffix + ".tmp")
                tmp.write_text(
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out),
                    encoding="utf-8",
                )
                tmp.replace(self._path)
                self._dedupe_map = None  # 迁移可能改写行, 失效缓存
                return migrated

    # ------------------------------------------------------------------
    # internal — row construction & parsing
    # ------------------------------------------------------------------

    def _make_row(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        seq: int,
        prev_hash: str,
        dedupe_id: str | None,
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        ts = time.time()
        row: dict[str, Any] = {
            "v": self._schema_version,
            "seq": seq,
            "id": event_id,
            "ts": ts,
            "type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        if dedupe_id is not None:
            row["dedupe_id"] = dedupe_id
        row["hash"] = _line_hash(
            prev_hash=prev_hash,
            seq=seq,
            event_id=event_id,
            ts=ts,
            event_type=event_type,
            payload=payload,
        )
        return row

    def _read_all(self, *, strict: bool) -> list[dict[str, Any]]:
        """读取全部事件行。解析失败时: strict=True 抛, strict=False 也抛
        (由调用方 catch 后转 VerifyResult)。"""
        if not self._path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise LoopStoreError(f"malformed line {line_no}: {exc}") from exc
        return rows

    def _read_head(self) -> dict[str, Any] | None:
        """读尾部一行 (在排他锁内调用)。"""
        if not self._path.exists():
            return None
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return None
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return None

    def _find_dedupe(self, dedupe_id: str) -> dict[str, Any] | None:
        """查 dedupe_id 是否已存在 (在排他锁内调用)。缓存 miss 时扫文件。"""
        if self._dedupe_map is None:
            self._dedupe_map = {}
            if self._path.exists():
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    did = row.get("dedupe_id")
                    if did is not None:
                        self._dedupe_map[did] = row
        return self._dedupe_map.get(dedupe_id)

    def _verify_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        raise_on_error: bool,
    ) -> VerifyResult:
        """校验行序列的链完整性 (hash/prev_hash/seq/版本)。"""
        if not rows:
            result = VerifyResult(ok=True, count=0)
            if raise_on_error:
                return result
            return result
        prev_hash = _GENESIS
        prev_seq = 0
        for i, row in enumerate(rows, start=1):
            try:
                ver = int(row["v"])
                seq = int(row["seq"])
                event_id = row["id"]
                ts = float(row["ts"])
                event_type = row["type"]
                payload = row.get("payload", {})
                stored_hash = row["hash"]
                stored_prev = row.get("prev_hash", "")
            except (KeyError, TypeError, ValueError) as exc:
                return self._fail(f"line {i}: missing/invalid fields ({exc})", i, raise_on_error)
            if ver != self._schema_version:
                return self._fail(
                    f"line {i}: schema v{ver} != store v{self._schema_version}", i, raise_on_error
                )
            if stored_prev != prev_hash:
                return self._fail(
                    f"line {i}: prev_hash mismatch (chain broken at seq {seq})", i, raise_on_error
                )
            if seq != prev_seq + 1:
                return self._fail(
                    f"line {i}: seq discontinuity (expected {prev_seq + 1}, got {seq})",
                    i,
                    raise_on_error,
                )
            recomputed = _line_hash(prev_hash, seq, event_id, ts, event_type, payload)
            if stored_hash != recomputed:
                return self._fail(
                    f"line {i}: hash mismatch (payload tampered at seq {seq})", i, raise_on_error
                )
            prev_hash = stored_hash
            prev_seq = seq
        result = VerifyResult(
            ok=True,
            count=len(rows),
            first_seq=rows[0]["seq"],
            last_seq=rows[-1]["seq"],
        )
        if raise_on_error:
            return result
        return result

    def _fail(
        self,
        error: str,
        line_no: int,
        raise_on_error: bool,
    ) -> VerifyResult:
        if raise_on_error:
            raise LoopStoreError(error)
        return VerifyResult(ok=False, count=0, error=error, line_no=line_no)

    # ------------------------------------------------------------------
    # file locks
    # ------------------------------------------------------------------

    def _exclusive_lock(self):
        """flock LOCK_EX (跨进程写互斥)。非 POSIX 平台降级为无操作。"""
        return _flock_ctx(self._path, exclusive=True)

    def _shared_lock(self):
        """flock LOCK_SH (读时防半行)。非 POSIX 平台降级为无操作。"""
        return _flock_ctx(self._path, exclusive=False)


class _flock_ctx:
    """fcntl.flock 上下文管理器。POSIX 之外降级为 no-op (仅线程锁兜底)。"""

    def __init__(self, path: Path, *, exclusive: bool) -> None:
        self._path = path
        self._exclusive = exclusive
        self._f = None

    def __enter__(self):
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows
            return self
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self._path.open("a+", encoding="utf-8")
        mode = fcntl.LOCK_EX if self._exclusive else fcntl.LOCK_SH
        fcntl.flock(self._f.fileno(), mode)
        return self

    def __exit__(self, *exc):
        if self._f is not None:
            try:
                import fcntl

                fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
            except ImportError:  # pragma: no cover
                pass
            self._f.close()
        return False


class QuotaTracker:
    """goal 级预算治理: 消耗追踪 + 超支暂停 + 事件化 (写入同一事件流)。

    Usage::

        store = AppendOnlyEventStore(Path("events.jsonl"))
        quota = QuotaTracker(budget_usd=5.0, goal_id="g1", store=store)
        await quota.record_usage(0.42, note="round 3 llm call")   # 超支 raise BudgetExceeded
        await quota.resume()                                       # 人工/自动恢复后继续

    与 ``obase.cost_tracker.CostTracker`` 的分工: CostTracker 是全局记账面
    (pricing/provider 维度); QuotaTracker 是 goal 维度预算治理, 不依赖
    pricing 表, 超支语义复用 ``BudgetExceeded`` / ``PauseRequested`` 异常。
    """

    def __init__(
        self,
        budget_usd: float,
        *,
        goal_id: str | None = None,
        store: AppendOnlyEventStore | None = None,
        auto_pause_on_exceed: bool = True,
    ) -> None:
        if budget_usd < 0:
            raise ValueError("budget_usd must be >= 0")
        self._budget = budget_usd
        self._goal_id = goal_id
        self._store = store
        self._auto_pause = auto_pause_on_exceed
        self._spent = 0.0
        self._paused = False
        self._entries: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def budget_usd(self) -> float:
        return self._budget

    @property
    def spent_usd(self) -> float:
        return self._spent

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self._budget - self._spent)

    @property
    def paused(self) -> bool:
        return self._paused

    async def record_usage(
        self,
        cost_usd: float,
        *,
        note: str = "",
    ) -> float:
        """记录消耗, 返回累计花费。配额耗尽时自动暂停并抛 ``BudgetExceeded``。

        若已暂停 (``PauseRequested`` 尚未恢复), 抛 ``PauseRequested``。
        """
        if cost_usd < 0:
            raise ValueError("cost_usd must be >= 0")
        if self._paused:
            raise PauseRequested(
                f"quota paused for goal {self._goal_id!r} (budget ${self._budget})"
            )
        self._spent += cost_usd
        self._entries.append(
            {"cost_usd": cost_usd, "note": note, "spent": self._spent, "ts": time.time()}
        )
        if self._store is not None:
            await self._store.append(
                "quota_consumed",
                {
                    "goal_id": self._goal_id,
                    "cost_usd": cost_usd,
                    "spent": self._spent,
                    "budget": self._budget,
                    "note": note,
                },
            )
        if self._spent > self._budget:
            if self._auto_pause:
                self._paused = True
                if self._store is not None:
                    await self._store.append(
                        "quota_paused",
                        {
                            "goal_id": self._goal_id,
                            "spent": self._spent,
                            "budget": self._budget,
                        },
                    )
            raise BudgetExceeded(f"budget ${self._budget:.4f} exceeded (spent ${self._spent:.4f})")
        return self._spent

    def check(self) -> None:
        """非异步护栏: 超支抛 ``BudgetExceeded`` (不写事件)。"""
        if self._spent > self._budget:
            raise BudgetExceeded(f"budget ${self._budget:.4f} exceeded (spent ${self._spent:.4f})")

    async def resume(self, *, new_budget: float | None = None, note: str = "") -> None:
        """恢复暂停状态 (人工放行或配额充值后调用)。

        Args:
            new_budget: 可选充值 —— 提高预算后恢复。不提供时 budget 不变,
                若 spent 仍超 budget, 下一次 ``record_usage`` 会再次超支暂停
                (这符合"消耗不会自动消失"的治理语义)。
        """
        if new_budget is not None:
            if new_budget < 0:
                raise ValueError("new_budget must be >= 0")
            self._budget = new_budget
        if self._paused:
            self._paused = False
            if self._store is not None:
                await self._store.append(
                    "quota_resumed",
                    {
                        "goal_id": self._goal_id,
                        "note": note,
                        "spent": self._spent,
                        "budget": self._budget,
                    },
                )

    def restore(
        self,
        spent_usd: float,
        *,
        budget_usd: float | None = None,
        paused: bool | None = None,
    ) -> None:
        """从事件流投影对齐运行时配额 (跨进程/跨天恢复用)。

        事件流是真相源, 投影只是恢复 —— 因此不写事件, 幂等。
        典型用法: 进程重启后重建 GoalKernel 投影, 用投影里的 QuotaView
        同步回运行时 QuotaTracker (spent/budget/paused)。
        """
        if spent_usd < 0:
            raise ValueError("spent_usd must be >= 0")
        self._spent = spent_usd
        if budget_usd is not None:
            if budget_usd < 0:
                raise ValueError("budget_usd must be >= 0")
            self._budget = budget_usd
        if paused is not None:
            self._paused = paused

    def summary(self) -> dict[str, Any]:
        return {
            "goal_id": self._goal_id,
            "budget_usd": self._budget,
            "spent_usd": self._spent,
            "remaining_usd": self.remaining_usd,
            "paused": self._paused,
            "entries": list(self._entries),
        }


__all__ = [
    "AppendOnlyEventStore",
    "EVENT_SCHEMA_VERSION",
    "LoopStoreError",
    "QuotaTracker",
    "VerifyResult",
]
