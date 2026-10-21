"""obase.kv_cache_shared_memory — 基于 POSIX 共享内存的跨进程潜空间直连管道.

提供 Agent 间潜空间向量 (Latent Vectors) / KV-Cache 状态零拷贝通信设施：
allocate → write_latent_state / read_latent_state，多进程共享同一命名块。

Example:
    >>> shm = KVCacheSharedMemory(shm_name="test_latent", size=4096)
    >>> shm.allocate_buffer()
    'test_latent'
    >>> shm.write_latent_state({"vector": [0.1, 0.2]})
    True
    >>> shm.read_latent_state()
    {'vector': [0.1, 0.2]}
    >>> shm.close(); shm.unlink()
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["KVCacheSharedMemory", "KVCacheError"]


class KVCacheError(RuntimeError):
    """共享内存操作错误。"""


class KVCacheSharedMemory:
    """跨进程潜空间向量共享内存管道。"""

    def __init__(self, shm_name: str = "veya_latent_bus", size: int = 1024 * 1024) -> None:
        if not shm_name:
            raise ValueError("kv_cache_shared_memory: shm_name must not be empty")
        if size <= 0:
            raise ValueError("kv_cache_shared_memory: size must be > 0")
        self.shm_name = shm_name
        self.size = size
        self._shm: Any = None
        self._owns_buffer = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def allocate_buffer(self) -> str:
        """分配（或附着）共享内存块，返回块名。"""
        from multiprocessing import shared_memory

        try:
            self._shm = shared_memory.SharedMemory(
                name=self.shm_name, create=True, size=self.size
            )
            self._owns_buffer = True
        except FileExistsError:
            self._shm = shared_memory.SharedMemory(name=self.shm_name)
            self._owns_buffer = False
        return self._shm.name

    def close(self) -> None:
        """解除附着（不删除块）。"""
        if self._shm is not None:
            try:
                self._shm.close()
            finally:
                self._shm = None

    def unlink(self) -> None:
        """删除共享内存块（须在所有进程解除附着后调用）。"""
        from multiprocessing import shared_memory

        try:
            shared_memory.SharedMemory(name=self.shm_name).unlink()
        except FileNotFoundError:  # pragma: no cover - 已删除
            pass

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------

    def write_latent_state(self, vector_data: dict[str, Any]) -> bool:
        """写入潜空间状态；超出块大小返回 False（不抛）。"""
        if self._shm is None:
            self.allocate_buffer()
        raw_bytes = json.dumps(vector_data, ensure_ascii=False, default=str).encode("utf-8")
        if len(raw_bytes) > self.size:
            return False
        assert self._shm is not None
        self._shm.buf[: len(raw_bytes)] = raw_bytes
        return True

    def read_latent_state(self) -> dict[str, Any]:
        """读取潜空间状态；空/损坏返回 {}（不抛）。"""
        if self._shm is None:
            try:
                self.allocate_buffer()
            except Exception:  # noqa: BLE001 - 附着失败返回空
                return {}
        assert self._shm is not None
        raw_bytes = bytes(self._shm.buf).rstrip(b"\x00")
        if not raw_bytes:
            return {}
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001 - 损坏数据返回空
            return {}

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._shm is not None else "idle",
            "shm_name": self.shm_name,
            "size": self.size,
            "attached": self._shm is not None,
        }
