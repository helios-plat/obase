"""obase: POSIX 共享内存分配与垃圾回收管理。不依赖上层模块。"""

from __future__ import annotations

import logging
from multiprocessing import shared_memory
from typing import Any

__all__ = ["PosixShmAllocator", "PosixShmError"]

logger = logging.getLogger(__name__)


class PosixShmError(RuntimeError):
    """共享内存分配错误."""


class PosixShmAllocator:
    """POSIX 共享内存池管理器.

    职责:
    - 分配定长连续共享内存块 (/dev/shm)
    - 跨进程挂载已有内存块
    - 物理销毁 (unlink) 防止系统级资源泄漏
    - 跟踪当前进程创建的内存块，防止孤儿泄漏
    """

    def __init__(self) -> None:
        self._tracked_shms: dict[str, shared_memory.SharedMemory] = {}

    def allocate(self, name: str, size: int) -> shared_memory.SharedMemory:
        """分配定长连续共享内存块.

        Args:
            name: 共享内存名称（跨进程唯一标识）
            size: 字节大小

        Returns:
            SharedMemory 实例

        Raises:
            PosixShmError: size <= 0
        """
        if size <= 0:
            raise PosixShmError(f"size 必须 > 0，当前: {size}")
        try:
            shm = shared_memory.SharedMemory(name=name, create=True, size=size)
            self._tracked_shms[name] = shm
            return shm
        except FileExistsError:
            shm = shared_memory.SharedMemory(name=name)
            self._tracked_shms[name] = shm
            return shm

    def attach(self, name: str) -> shared_memory.SharedMemory:
        """跨进程挂载已有内存块.

        Args:
            name: 共享内存名称

        Returns:
            SharedMemory 实例
        """
        return shared_memory.SharedMemory(name=name)

    def free(self, name: str) -> bool:
        """物理销毁 (unlink) 共享内存块，防止 /dev/shm 泄漏.

        Args:
            name: 共享内存名称

        Returns:
            True 如果成功销毁，False 如果块不存在
        """
        if name in self._tracked_shms:
            shm = self._tracked_shms.pop(name)
            try:
                shm.close()
                shm.unlink()
            except Exception:
                pass
            return True
        try:
            shm = shared_memory.SharedMemory(name=name)
            shm.close()
            shm.unlink()
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def free_all(self) -> int:
        """释放所有 tracked 内存块.

        Returns:
            释放的块数量
        """
        count = 0
        for name in list(self._tracked_shms.keys()):
            if self.free(name):
                count += 1
        return count

    def is_tracked(self, name: str) -> bool:
        """检查名称是否在跟踪列表中."""
        return name in self._tracked_shms

    @property
    def tracked_count(self) -> int:
        return len(self._tracked_shms)

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "tracked_blocks": self.tracked_count,
        }
