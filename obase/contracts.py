"""3O 范式 Phase 1 — obase 契约层 (物理法则定义).

零业务逻辑: 本文件只定义抽象契约 (ABC), 不包含任何业务域实现。
零向上依赖: 仅使用标准库, 不 import 任何上层业务包。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any


class IDaemon_Bus(ABC):
    """跨进程守护总线契约"""

    @abstractmethod
    async def publish(self, topic: str, payload: dict) -> None:
        """向指定主题发布消息"""

    @abstractmethod
    async def subscribe(self, topic: str) -> Any:
        """订阅指定主题, 返回订阅器句柄"""


class IEvent_Barrier(ABC):
    """全局事件同步屏障契约"""

    @abstractmethod
    async def wait_for_event(self, event_name: str, timeout: float) -> bool:
        """等待事件触发, 超时返回 False"""

    @abstractmethod
    async def set_event(self, event_name: str) -> None:
        """触发事件"""


class IKV_Store(ABC):
    """持久化键值存储契约 (用于 Session Tree)"""

    @abstractmethod
    async def put(self, key: str, value: dict) -> None:
        """原子写入键值对"""

    @abstractmethod
    async def get(self, key: str) -> dict | None:
        """读取键值对, 不存在返回 None"""

    @abstractmethod
    async def list_prefix(self, prefix: str) -> list[dict]:
        """按前缀列出所有值"""


class ILLM_Client(ABC):
    """纯底层大模型网络请求通道 (禁止包含 Prompt 组装)"""

    @abstractmethod
    async def stream_request(
        self, endpoint: str, payload: dict, headers: dict
    ) -> AsyncGenerator[bytes, None]:
        """流式收发原始字节"""


class IVFS_Sandbox(ABC):
    """虚拟文件系统与隔离执行环境契约"""

    @abstractmethod
    async def execute_isolated(self, cmd: str, timeout: int = 30) -> dict[str, Any]:
        """在隔离环境中执行命令并返回结果"""

    @abstractmethod
    async def read_file(self, path: str) -> bytes:
        """读取沙盒内文件"""

    @abstractmethod
    async def write_file(self, path: str, content: bytes) -> None:
        """写入沙盒内文件"""


# --- 3O 范式语义别名 (Phase 2 下游层按规范命名引用) ---
# 别名指向契约本身而非具体实现, 保持面向契约编程。
VFSProvider = IVFS_Sandbox
KVStoreProvider = IKV_Store
