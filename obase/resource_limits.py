"""obase.resource_limits — 确定性资源信封（ResourceEnvelope）.

给受控执行一个确定性边界：
- cpu_seconds: CPU 时间预算（秒）
- memory_mb: 内存上限（MiB）
- wallclock_s: 墙钟超时（秒）
- network: NetworkPolicy（deny_all / allowlist 出口）
- write_scope: 允许写入的路径前缀白名单（空 = 只读）
- max_stdout_bytes: 输出/子进程 stdout 限额

本模块只定义"规格 + 判定"；强制由 obase.hardened_executor 执行。
纯 stdlib。

例:
    >>> env = ResourceEnvelope(
    ...     wallclock_s=5.0,
    ...     network=NetworkPolicy("allowlist", ("api.example.com:443",)),
    ... )
    >>> env.allows_network("api.example.com", 443)
    True
    >>> env.allows_network("evil.example.com", 443)
    False
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "NetworkPolicy",
    "ResourceEnvelope",
    "DEFAULT_ENVELOPE",
    "validate_envelope",
    "write_allowed",
    "network_allowed",
    "WallclockDeadline",
]


@dataclass(frozen=True)
class NetworkPolicy:
    """网络策略。mode='deny_all' 时无任何出口；'allowlist' 时仅允许列出的 host[:port]。"""

    mode: str = "deny_all"  # deny_all | allowlist
    egress_allow: tuple[str, ...] = ()

    def allows(self, host: str, port: int | None = None) -> bool:
        """host[:port] 是否在允许出口内。port 省略时匹配任意端口。"""
        if self.mode == "deny_all":
            return False
        target = host if port is None else f"{host}:{port}"
        for rule in self.egress_allow:
            if target == rule:
                return True
            if ":" not in rule and rule == host:
                return True
        return False


@dataclass(frozen=True)
class ResourceEnvelope:
    """确定性资源信封（不可变，创建后不得修改）。"""

    name: str = "default"
    cpu_seconds: float = 30.0
    memory_mb: float = 512.0
    wallclock_s: float = 60.0
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    write_scope: tuple[str, ...] = ()
    max_stdout_bytes: int = 1_048_576  # 1 MiB

    def allows_write(self, path: str | Path) -> bool:
        return write_allowed(self, path)

    def allows_network(self, host: str, port: int | None = None) -> bool:
        return network_allowed(self, host, port)


DEFAULT_ENVELOPE = ResourceEnvelope(name="default-denied")


def validate_envelope(envelope: ResourceEnvelope) -> None:
    """校验信封数值合法性（负值/非法模式抛 ValueError）。"""
    if envelope.cpu_seconds < 0 or envelope.wallclock_s < 0 or envelope.memory_mb < 0:
        raise ValueError(
            "resource_limits: cpu_seconds/wallclock_s/memory_mb must be >= 0"
        )
    if envelope.network.mode not in ("deny_all", "allowlist"):
        raise ValueError(
            f"resource_limits: unknown network mode {envelope.network.mode!r}"
        )
    for scope in envelope.write_scope:
        p = Path(scope)
        if not p.is_absolute():
            raise ValueError(
                f"resource_limits: write_scope must be absolute: {scope!r}"
            )


def write_allowed(envelope: ResourceEnvelope, path: str | Path) -> bool:
    """path 是否落在信封 write_scope 内（前缀匹配）。空 write_scope = 只读。"""
    if not envelope.write_scope:
        return False
    target = Path(path).expanduser().resolve()
    for scope in envelope.write_scope:
        base = Path(scope).expanduser().resolve()
        try:
            target.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def network_allowed(envelope: ResourceEnvelope, host: str, port: int | None = None) -> bool:
    return envelope.network.allows(host, port)


class WallclockDeadline:
    """墙钟截止（monotonic 时钟），用于超时判定。"""

    def __init__(self, timeout_s: float) -> None:
        self._deadline = time.monotonic() + max(0.0, timeout_s)

    @property
    def remaining(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining <= 0
