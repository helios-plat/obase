"""obase.isolated_task_runner — spawn-isolated execution of CPU-heavy tasks.

3O layer: obase (cross-cutting infrastructure: process isolation + resource caps).

Runs one importable callable per task in a fresh ``spawn`` child process so a
CPU-bound job never blocks the caller's event loop and a crash, leak or hang in
the job cannot take the host process down.

Guarantees
----------
- **spawn only** — the child is a clean interpreter (no inherited event loop,
  DB pools, locks or threads from the parent).
- **global concurrency cap** — at most ``max_concurrency`` children alive per
  runner; extra submissions wait in ``pending``.
- **per-task wall-clock timeout** — SIGTERM, then SIGKILL after a grace period.
- **per-task memory cap** — ``RLIMIT_AS`` set inside the child before the target
  is imported (POSIX only; ignored where ``resource`` is unavailable), plus an
  optional parent-side resident-set (RSS) watchdog (Linux ``/proc``). Note that
  numeric stacks (BLAS thread pools, Arrow/Lance runtimes) reserve several GB of
  *virtual* address space while touching little of it, so ``RLIMIT_AS`` should
  be a generous backstop and ``max_rss_bytes`` the working limit for them.
- **persistent run id + status** — every state change is written to a
  :class:`TaskStatusStore`; :class:`JsonFileTaskStatusStore` survives restarts so
  a client can reconnect by ``run_id`` and records orphaned by a dead parent are
  marked ``interrupted`` by :meth:`IsolatedTaskRunner.recover_interrupted`.
- **cancellation** — pending tasks never start; running tasks are terminated.
- **safe result / exception transport** — results travel back by pickle over a
  one-way pipe; exceptions never cross the boundary as objects, only as
  ``(type name, message, formatted traceback)`` strings.

Targets are given as ``"package.module:function"`` (or a module-level function,
which is converted to that form). Coroutine functions are run with
``asyncio.run`` inside the child.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import multiprocessing as mp
import os
import signal
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "IsolatedTaskRunner",
    "InMemoryTaskStatusStore",
    "JsonFileTaskStatusStore",
    "TaskLimits",
    "TaskRecord",
    "TaskStatus",
    "TaskStatusStore",
    "TaskFailedError",
    "TERMINAL_STATUSES",
]


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # target raised an exception
    TIMEOUT = "timeout"  # killed after exceeding timeout_s
    CANCELLED = "cancelled"  # cancelled by caller
    CRASHED = "crashed"  # child died without reporting (segfault, OOM-kill, os._exit)
    MEMORY_EXCEEDED = "memory_exceeded"  # killed by the RSS watchdog
    INTERRUPTED = "interrupted"  # owning runner process vanished mid-flight


TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
        TaskStatus.CRASHED,
        TaskStatus.MEMORY_EXCEEDED,
        TaskStatus.INTERRUPTED,
    }
)


@dataclass(frozen=True)
class TaskLimits:
    """Per-task resource limits. ``None`` disables a limit.

    ``memory_bytes`` → ``RLIMIT_AS`` in the child (allocation fails with
    ``MemoryError``); ``max_rss_bytes`` → parent watchdog kills the child when
    its resident set exceeds the value (status ``memory_exceeded``).
    """

    timeout_s: float | None = None
    memory_bytes: int | None = None
    max_rss_bytes: int | None = None


@dataclass
class TaskRecord:
    """Persistent, JSON-serialisable state of one run (no result payload)."""

    run_id: str
    target: str
    status: TaskStatus = TaskStatus.PENDING
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    owner_pid: int = field(default_factory=os.getpid)
    child_pid: int | None = None
    exit_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    timeout_s: float | None = None
    memory_bytes: int | None = None
    max_rss_bytes: int | None = None
    peak_rss_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = str(self.status)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskRecord:
        values = dict(data)
        values["status"] = TaskStatus(values["status"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in values.items() if k in known})


class TaskFailedError(RuntimeError):
    """Raised by :meth:`IsolatedTaskRunner.result` when a run did not succeed."""

    def __init__(self, record: TaskRecord) -> None:
        self.record = record
        detail = record.error_message or record.status
        super().__init__(f"task {record.run_id} {record.status}: {detail}")


# ---------------------------------------------------------------------------
# Status stores
# ---------------------------------------------------------------------------


class TaskStatusStore(Protocol):
    def save(self, record: TaskRecord) -> None: ...

    def load(self, run_id: str) -> TaskRecord | None: ...

    def list(self) -> list[TaskRecord]: ...


class InMemoryTaskStatusStore:
    """Process-local store (no persistence across restarts)."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}

    def save(self, record: TaskRecord) -> None:
        self._records[record.run_id] = replace(record, metadata=dict(record.metadata))

    def load(self, run_id: str) -> TaskRecord | None:
        rec = self._records.get(run_id)
        return None if rec is None else replace(rec, metadata=dict(rec.metadata))

    def list(self) -> list[TaskRecord]:
        return [replace(r, metadata=dict(r.metadata)) for r in self._records.values()]


class JsonFileTaskStatusStore:
    """One JSON file per run under ``directory``; atomic replace on every save."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in run_id)
        if not safe or safe in {".", ".."}:
            raise ValueError(f"invalid run_id: {run_id!r}")
        return self.directory / f"{safe}.json"

    def save(self, record: TaskRecord) -> None:
        path = self._path(record.run_id)
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record.to_dict(), fh, ensure_ascii=False, default=str)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def load(self, run_id: str) -> TaskRecord | None:
        path = self._path(run_id)
        try:
            with path.open(encoding="utf-8") as fh:
                return TaskRecord.from_dict(json.load(fh))
        except FileNotFoundError:
            return None

    def list(self) -> list[TaskRecord]:
        out: list[TaskRecord] = []
        for path in sorted(self.directory.glob("*.json")):
            with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                with path.open(encoding="utf-8") as fh:
                    out.append(TaskRecord.from_dict(json.load(fh)))
        return out


# ---------------------------------------------------------------------------
# Child side (must stay importable at module level for spawn)
# ---------------------------------------------------------------------------


def resolve_target(target: str | Callable[..., Any]) -> str:
    """Normalise a callable or ``"mod:func"`` string to ``"mod:func"``."""
    if isinstance(target, str):
        if ":" not in target:
            raise ValueError(f"target must look like 'package.module:function', got {target!r}")
        return target
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    if not module or not qualname or "<" in qualname or module == "__main__":
        raise ValueError("target must be an importable module-level function")
    return f"{module}:{qualname}"


def _load_target(spec: str) -> Callable[..., Any]:
    module_name, _, attr_path = spec.partition(":")
    obj: Any = importlib.import_module(module_name)
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    if not callable(obj):
        raise TypeError(f"{spec} is not callable")
    return obj  # type: ignore[no-any-return]


def _apply_memory_limit(memory_bytes: int | None) -> None:
    if not memory_bytes:
        return
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    limit = int(memory_bytes)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))


def _set_parent_death_signal() -> None:
    """Linux: have the kernel SIGKILL this child if the parent thread dies."""
    if not sys.platform.startswith("linux"):
        return
    with contextlib.suppress(Exception):
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        pr_set_pdeathsig = 1
        libc.prctl(pr_set_pdeathsig, int(signal.SIGKILL), 0, 0, 0)


def _child_entry(
    conn: Any,
    target: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    memory_bytes: int | None,
    parent_death_signal: bool = False,
) -> None:
    """Spawned child: apply limits, run target, send exactly one message."""
    message: tuple[str, Any]
    if parent_death_signal:
        _set_parent_death_signal()
    try:
        _apply_memory_limit(memory_bytes)
        func = _load_target(target)
        result = func(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        message = ("ok", result)
    except BaseException as exc:  # noqa: BLE001 - everything must be reported
        message = (
            "error",
            {
                "type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
    try:
        conn.send(message)
    except BaseException as exc:  # noqa: BLE001 - e.g. unpicklable result
        with contextlib.suppress(BaseException):
            conn.send(
                (
                    "error",
                    {
                        "type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                        "message": f"result could not be sent to parent: {exc}",
                        "traceback": traceback.format_exc(),
                    },
                )
            )
    finally:
        with contextlib.suppress(BaseException):
            conn.close()
    # Skip interpreter teardown (atexit, thread joins) once the message is out.
    os._exit(0)


# ---------------------------------------------------------------------------
# Parent side
# ---------------------------------------------------------------------------

StatusCallback = Callable[[TaskRecord], Awaitable[None] | None]


@dataclass
class _Run:
    record: TaskRecord
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    done: asyncio.Event
    cancel_requested: bool = False
    process: Any = None
    result: Any = None
    task: asyncio.Task[None] | None = None


class IsolatedTaskRunner:
    """Runs importable callables in spawn children under a global cap.

    Parameters
    ----------
    max_concurrency : int
        Maximum number of live child processes for this runner.
    default_limits : TaskLimits
        Applied when :meth:`submit` gets no ``limits``.
    status_store : TaskStatusStore | None
        Where :class:`TaskRecord` transitions are persisted (in-memory default).
    on_status : callable | None
        Called (sync or async) with a copy of the record after every transition.
        Exceptions raised by the callback are swallowed.
    kill_grace_s : float
        Seconds between SIGTERM and SIGKILL on timeout / cancel.
    poll_interval_s : float
        Parent polling interval while a child runs.
    """

    def __init__(
        self,
        *,
        max_concurrency: int = 2,
        default_limits: TaskLimits | None = None,
        status_store: TaskStatusStore | None = None,
        on_status: StatusCallback | None = None,
        kill_grace_s: float = 5.0,
        poll_interval_s: float = 0.05,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.max_concurrency = int(max_concurrency)
        self.default_limits = default_limits or TaskLimits()
        self.store: TaskStatusStore = status_store or InMemoryTaskStatusStore()
        self._on_status = on_status
        self._kill_grace_s = float(kill_grace_s)
        self._poll_s = float(poll_interval_s)
        self._ctx = mp.get_context("spawn")
        self._semaphore: asyncio.Semaphore | None = None
        self._runs: dict[str, _Run] = {}
        self._running = 0

    # -- introspection ------------------------------------------------------

    @property
    def running_count(self) -> int:
        return self._running

    @property
    def active_run_ids(self) -> list[str]:
        return [rid for rid, run in self._runs.items() if not run.record.done]

    def status(self, run_id: str) -> TaskRecord | None:
        """Current record: live state if this runner owns it, else from the store."""
        run = self._runs.get(run_id)
        if run is not None:
            return replace(run.record, metadata=dict(run.record.metadata))
        return self.store.load(run_id)

    # -- lifecycle ------------------------------------------------------------

    def recover_interrupted(self) -> list[TaskRecord]:
        """Mark stored non-terminal records whose owner process is gone.

        Call once at startup. Records owned by a live process other than this
        one are left alone (another runner may still be supervising them).
        """
        recovered: list[TaskRecord] = []
        for rec in self.store.list():
            if rec.done or rec.run_id in self._runs:
                continue
            if rec.owner_pid != os.getpid() and _pid_alive(rec.owner_pid):
                continue
            if rec.child_pid and _is_spawn_child(rec.child_pid):
                with contextlib.suppress(OSError):
                    os.kill(rec.child_pid, signal.SIGKILL)
            rec.status = TaskStatus.INTERRUPTED
            rec.finished_at = time.time()
            rec.error_message = "runner process exited before the task finished"
            self.store.save(rec)
            recovered.append(rec)
        return recovered

    async def submit(
        self,
        run_id: str,
        target: str | Callable[..., Any],
        *args: Any,
        limits: TaskLimits | None = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> TaskRecord:
        """Queue a run and return its ``pending`` record immediately."""
        if run_id in self._runs and not self._runs[run_id].record.done:
            raise ValueError(f"run_id {run_id!r} is already active")
        spec = resolve_target(target)
        lim = limits or self.default_limits
        record = TaskRecord(
            run_id=run_id,
            target=spec,
            timeout_s=lim.timeout_s,
            memory_bytes=lim.memory_bytes,
            max_rss_bytes=lim.max_rss_bytes,
            metadata=dict(metadata or {}),
        )
        run = _Run(record=record, args=tuple(args), kwargs=dict(kwargs), done=asyncio.Event())
        self._runs[run_id] = run
        await self._publish(run)
        run.task = asyncio.create_task(self._supervise(run), name=f"isolated-task:{run_id}")
        return replace(record, metadata=dict(record.metadata))

    async def wait(self, run_id: str, timeout: float | None = None) -> TaskRecord:
        """Wait for a run owned by this runner to reach a terminal state."""
        run = self._runs.get(run_id)
        if run is None:
            rec = self.store.load(run_id)
            if rec is None:
                raise KeyError(run_id)
            return rec
        await asyncio.wait_for(run.done.wait(), timeout)
        return replace(run.record, metadata=dict(run.record.metadata))

    async def result(self, run_id: str, timeout: float | None = None) -> Any:
        """Wait and return the target's return value, or raise TaskFailedError."""
        record = await self.wait(run_id, timeout)
        if record.status != TaskStatus.SUCCEEDED:
            raise TaskFailedError(record)
        run = self._runs.get(run_id)
        return None if run is None else run.result

    def forget(self, run_id: str) -> None:
        """Drop the in-memory result of a finished run (store record is kept)."""
        run = self._runs.get(run_id)
        if run is not None and run.record.done:
            self._runs.pop(run_id, None)

    def request_cancel(self, run_id: str) -> bool:
        """Synchronously flag a pending/running task for cancellation.

        The supervisor acts on the flag within one poll interval. Returns False
        if the run is unknown to this runner or already finished.
        """
        run = self._runs.get(run_id)
        if run is None or run.record.done:
            return False
        run.cancel_requested = True
        return True

    async def cancel(self, run_id: str) -> bool:
        """Cancel a pending or running task. Returns False if unknown/finished."""
        return self.request_cancel(run_id)

    async def shutdown(self) -> None:
        """Cancel every active run and wait for the children to be reaped."""
        for run in list(self._runs.values()):
            if not run.record.done:
                run.cancel_requested = True
        tasks = [r.task for r in self._runs.values() if r.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- internals ------------------------------------------------------------

    def _sem(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    async def _publish(self, run: _Run) -> None:
        snapshot = replace(run.record, metadata=dict(run.record.metadata))
        with contextlib.suppress(Exception):
            self.store.save(snapshot)
        if self._on_status is not None:
            try:
                maybe = self._on_status(replace(snapshot, metadata=dict(snapshot.metadata)))
                if asyncio.iscoroutine(maybe) or isinstance(maybe, asyncio.Future):
                    await maybe
            except Exception:  # noqa: BLE001 - callbacks must not break supervision
                pass

    async def _finish(self, run: _Run, status: TaskStatus, **fields: Any) -> None:
        run.record.status = status
        run.record.finished_at = time.time()
        for key, value in fields.items():
            setattr(run.record, key, value)
        await self._publish(run)
        run.done.set()

    async def _supervise(self, run: _Run) -> None:
        sem = self._sem()
        try:
            # Wait for a slot, but notice cancellation while queued.
            while True:
                if run.cancel_requested:
                    await self._finish(
                        run, TaskStatus.CANCELLED, error_message="cancelled before start"
                    )
                    return
                try:
                    await asyncio.wait_for(sem.acquire(), timeout=self._poll_s)
                    break
                except TimeoutError:
                    continue
            self._running += 1
            try:
                await self._run_child(run)
            finally:
                self._running -= 1
                sem.release()
        except asyncio.CancelledError:
            # Supervisor itself cancelled (e.g. loop shutdown): never orphan the child.
            await asyncio.shield(self._kill(run.process))
            if not run.record.done:
                await self._finish(
                    run, TaskStatus.CANCELLED, error_message="supervisor cancelled"
                )
            raise
        except Exception as exc:  # noqa: BLE001 - spawn/IPC failures
            await self._kill(run.process)
            if not run.record.done:
                await self._finish(
                    run,
                    TaskStatus.CRASHED,
                    error_type=f"{type(exc).__module__}.{type(exc).__qualname__}",
                    error_message=f"runner failure: {exc}",
                    error_traceback=traceback.format_exc(),
                )

    async def _run_child(self, run: _Run) -> None:
        if run.cancel_requested:
            await self._finish(run, TaskStatus.CANCELLED, error_message="cancelled before start")
            return
        recv_conn, send_conn = self._ctx.Pipe(duplex=False)
        process = self._ctx.Process(
            target=_child_entry,
            args=(
                send_conn,
                run.record.target,
                run.args,
                run.kwargs,
                run.record.memory_bytes,
                # PR_SET_PDEATHSIG fires when the *thread* that started the child
                # exits, so only use it when starting from the main thread.
                threading.current_thread() is threading.main_thread(),
            ),
            daemon=True,
            name=f"isolated-task-{run.record.run_id}",
        )
        run.process = process
        try:
            # Started on the loop thread (spawn start is a fork+exec, cheap) so
            # the parent-death signal is tied to a long-lived thread.
            process.start()
        finally:
            send_conn.close()  # parent keeps only the read end
        run.record.status = TaskStatus.RUNNING
        run.record.started_at = time.time()
        run.record.child_pid = process.pid
        await self._publish(run)

        deadline = (
            None
            if run.record.timeout_s is None
            else time.monotonic() + float(run.record.timeout_s)
        )
        message: tuple[str, Any] | None = None
        try:
            while True:
                if run.cancel_requested:
                    await self._kill(process)
                    await self._finish(
                        run,
                        TaskStatus.CANCELLED,
                        exit_code=process.exitcode,
                        error_message="cancelled while running",
                    )
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    await self._kill(process)
                    await self._finish(
                        run,
                        TaskStatus.TIMEOUT,
                        exit_code=process.exitcode,
                        error_message=f"exceeded timeout of {run.record.timeout_s}s",
                    )
                    return
                rss = _rss_bytes(process.pid)
                if rss is not None:
                    run.record.peak_rss_bytes = max(run.record.peak_rss_bytes or 0, rss)
                    limit = run.record.max_rss_bytes
                    if limit is not None and rss > limit:
                        await self._kill(process)
                        await self._finish(
                            run,
                            TaskStatus.MEMORY_EXCEEDED,
                            exit_code=process.exitcode,
                            error_message=(
                                f"resident memory {rss} bytes exceeded limit {limit} bytes"
                            ),
                        )
                        return
                if recv_conn.poll():
                    try:
                        message = await asyncio.to_thread(recv_conn.recv)
                    except (EOFError, OSError):
                        message = None
                    break
                if not process.is_alive():
                    # Drain a message that landed between poll and death.
                    if recv_conn.poll(0.2):
                        with contextlib.suppress(EOFError, OSError):
                            message = await asyncio.to_thread(recv_conn.recv)
                    break
                await asyncio.sleep(self._poll_s)

            await asyncio.to_thread(process.join, self._kill_grace_s)
            if process.is_alive():
                await self._kill(process)
            exit_code = process.exitcode

            if message is not None and message[0] == "ok":
                run.result = message[1]
                await self._finish(run, TaskStatus.SUCCEEDED, exit_code=exit_code)
            elif message is not None and message[0] == "error":
                err = message[1] or {}
                await self._finish(
                    run,
                    TaskStatus.FAILED,
                    exit_code=exit_code,
                    error_type=str(err.get("type")),
                    error_message=str(err.get("message")),
                    error_traceback=str(err.get("traceback")),
                )
            else:
                await self._finish(
                    run,
                    TaskStatus.CRASHED,
                    exit_code=exit_code,
                    error_message=_describe_exit(exit_code),
                )
        finally:
            with contextlib.suppress(Exception):
                recv_conn.close()
            with contextlib.suppress(Exception):
                if not process.is_alive():
                    process.close()

    async def _kill(self, process: Any) -> None:
        if process is None:
            return
        try:
            if not process.is_alive():
                return
        except ValueError:  # already closed
            return
        process.terminate()
        await asyncio.to_thread(process.join, self._kill_grace_s)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, self._kill_grace_s)


def _describe_exit(exit_code: int | None) -> str:
    if exit_code is None:
        return "child process did not report a result"
    if exit_code < 0:
        try:
            name = signal.Signals(-exit_code).name
        except ValueError:
            name = str(-exit_code)
        return f"child process killed by signal {name} without reporting a result"
    return f"child process exited with code {exit_code} without reporting a result"


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_spawn_child(pid: int) -> bool:
    """True only if ``pid`` is alive and looks like a multiprocessing spawn child.

    Guards against killing an unrelated process that reused a stale PID.
    """
    if not _pid_alive(pid):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmdline = fh.read()
    except OSError:
        return False
    return b"multiprocessing.spawn" in cmdline


def _rss_bytes(pid: int | None) -> int | None:
    """Resident set size of ``pid`` from /proc (Linux); None if unavailable."""
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None
