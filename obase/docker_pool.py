"""obase.docker_pool — Docker 容器池管理与生命周期适配器.

职责:
- 按 image 维护一组可复用沙箱容器（创建 / 复用 / 销毁 / 状态查询）
- 容量上限 max_size + 空闲超时回收（idle_timeout_s）
- docker SDK 为可选依赖：惰性加载，未安装时 acquire/exec 给出明确错误

Example:
    >>> pool = DockerPool(image="python:3.12-slim", max_size=2)
    >>> cid = await pool.acquire()
    >>> await pool.release(cid)
    >>> await pool.close()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from obase.exceptions import OBaseNotFoundError

__all__ = ["DockerPool", "ContainerSlot", "DockerPoolError"]

PoolState = Literal["running", "idle", "stopped", "missing"]


class DockerPoolError(RuntimeError):
    """容器池操作失败。"""


def _docker() -> tuple[Any, ...]:
    """惰性加载 docker 原子（docker SDK 为可选依赖，未安装时给出明确错误）。"""
    try:
        from obase.docker.containers import (
            docker_container_create,
            docker_container_exec,
            docker_container_inspect,
            docker_container_remove,
            docker_container_start,
        )
    except ImportError as exc:
        raise DockerPoolError("DockerPool requires the docker SDK (obase[docker])") from exc
    return (
        docker_container_create,
        docker_container_exec,
        docker_container_inspect,
        docker_container_remove,
        docker_container_start,
    )


@dataclass
class ContainerSlot:
    """池内容器槽位（运行期状态）。"""

    container_id: str
    image: str
    name: str
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    busy: bool = False
    state: PoolState = "idle"


class DockerPool:
    """Docker 容器池：acquire 优先复用空闲容器，否则新建（上限 max_size）。

    全部 docker API 为同步阻塞调用，经 asyncio.to_thread 包裹避免阻塞事件循环。
    """

    def __init__(
        self,
        *,
        image: str,
        max_size: int = 4,
        idle_timeout_s: float = 600.0,
        name_prefix: str = "obase-pool",
        labels: dict[str, str] | None = None,
        docker_host: str = "unix:///var/run/docker.sock",
        env: dict[str, str] | None = None,
        command: list[str] | None = None,
        network: str | None = None,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self.image = image
        self.max_size = max_size
        self.idle_timeout_s = idle_timeout_s
        self.name_prefix = name_prefix
        self.labels = dict(labels or {})
        self.docker_host = docker_host
        self.env = env
        self.command = command
        self.network = network
        self._slots: dict[str, ContainerSlot] = {}
        self._counter = 0

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._slots)

    @property
    def idle_count(self) -> int:
        return sum(1 for s in self._slots.values() if not s.busy)

    async def status(self) -> list[dict[str, Any]]:
        """查询池内全部容器状态（含 docker daemon 实时态）。"""
        _, _, inspect, _, _ = _docker()
        out: list[dict[str, Any]] = []
        for slot in list(self._slots.values()):
            info: dict[str, Any] = {
                "container_id": slot.container_id,
                "name": slot.name,
                "image": slot.image,
                "pool_state": slot.state,
                "busy": slot.busy,
                "last_used_at": slot.last_used_at,
            }
            try:
                live = await asyncio.to_thread(
                    inspect,
                    container_id=slot.container_id,
                    docker_host=self.docker_host,
                )
                info["daemon_state"] = live.state
                info["status"] = live.status
            except (OBaseNotFoundError, Exception):  # noqa: BLE001 - 状态查询不致命
                info["daemon_state"] = "missing"
                slot.state = "missing"
            out.append(info)
        return out

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def acquire(self, *, name_hint: str | None = None) -> str:
        """取一个可用容器：优先空闲复用；无空闲且未达上限则新建。"""
        now = time.time()
        for slot in self._slots.values():
            if not slot.busy and slot.state == "idle":
                slot.busy = True
                slot.last_used_at = now
                return slot.container_id

        if self.size >= self.max_size:
            raise DockerPoolError(
                f"pool full ({self.max_size}) and no idle container — "
                "release or wait before acquiring"
            )

        create, _, _, _, start = _docker()
        self._counter += 1
        name = f"{self.name_prefix}-{name_hint or 'c'}-{self._counter}"
        try:
            created = await asyncio.to_thread(
                create,
                image=self.image,
                name=name,
                command=self.command,
                env=self.env,
                labels={**self.labels, "obase.pool": "true"},
                restart_policy="no",
                network=self.network,
                docker_host=self.docker_host,
            )
        except Exception as exc:  # noqa: BLE001 - 统一包装为池错误
            raise DockerPoolError(f"pool create failed: {exc}") from exc

        slot = ContainerSlot(
            container_id=created.container_id,
            image=self.image,
            name=created.name,
            busy=True,
            state="running",
        )
        self._slots[created.container_id] = slot
        try:
            await asyncio.to_thread(
                start,
                container_id=created.container_id,
                docker_host=self.docker_host,
            )
        except Exception as exc:  # noqa: BLE001
            self._slots.pop(created.container_id, None)
            raise DockerPoolError(f"pool start failed: {exc}") from exc
        return created.container_id

    async def release(self, container_id: str) -> None:
        """归还容器为 idle（若已超空闲时限则直接销毁）。"""
        slot = self._slots.get(container_id)
        if slot is None:
            raise DockerPoolError(f"unknown container: {container_id}")
        slot.busy = False
        slot.last_used_at = time.time()
        if time.time() - slot.last_used_at > self.idle_timeout_s:
            await self.destroy(container_id)

    async def destroy(self, container_id: str) -> None:
        """销毁容器并移出池。"""
        slot = self._slots.get(container_id)
        if slot is None:
            raise DockerPoolError(f"unknown container: {container_id}")
        _, _, _, remove, _ = _docker()
        try:
            await asyncio.to_thread(
                remove,
                container_id=container_id,
                force=True,
                docker_host=self.docker_host,
            )
        except OBaseNotFoundError:
            pass
        finally:
            self._slots.pop(container_id, None)

    async def exec(
        self,
        container_id: str,
        *,
        command: list[str],
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int = 30,
    ) -> Any:
        """在池内容器执行命令（委托 obase.docker.containers.docker_container_exec）。"""
        _, exec_fn, _, _, _ = _docker()
        return await asyncio.to_thread(
            exec_fn,
            container_id=container_id,
            command=command,
            workdir=workdir,
            env=env,
            timeout_sec=timeout_sec,
            docker_host=self.docker_host,
        )

    async def close(self) -> None:
        """销毁池内全部容器。"""
        for cid in list(self._slots):
            await self.destroy(cid)

    async def __aenter__(self) -> DockerPool:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
