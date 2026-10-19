"""3O 范式全栈 — obase 新增元素测试 (元素 1/2 + base_types/context_vars)."""

from __future__ import annotations

import pytest

from obase import (
    ContextSlot,
    DaemonBusProvider,
    ErrorDict,
    JSONValue,
    LocalEventBarrier,
    ResultDict,
)


async def test_local_event_barrier_timeout_then_set():
    barrier = LocalEventBarrier()
    assert await barrier.wait_for("boot", timeout=0.02) is False
    barrier.set_event("boot")
    assert await barrier.wait_for("boot", timeout=0.02) is True
    # 已触发的事件保持置位
    assert await barrier.wait_for("boot", timeout=0.02) is True


async def test_local_event_barrier_independent_events():
    barrier = LocalEventBarrier()
    barrier.set_event("a")
    assert await barrier.wait_for("b", timeout=0.02) is False
    assert await barrier.wait_for("a", timeout=0.02) is True


def test_daemon_bus_provider_is_protocol():
    """DaemonBusProvider 是纯适配器协议, 不可实例化。"""
    with pytest.raises(TypeError):
        DaemonBusProvider()  # type: ignore[abstract]


def test_base_types_aliases():
    """base_types 定义类型别名, 无业务逻辑。"""
    sample: JSONValue = {"a": [1, 2.5, None, "x"]}
    assert isinstance(sample, dict)
    assert ResultDict is not None
    assert ErrorDict is not None

    # 类型别名可用作注解 (typing.get_type_hints 可解析)
    import typing

    def _f() -> ResultDict: ...

    assert typing.get_type_hints(_f)["return"] is not None


def test_context_slot_roundtrip():
    slot: ContextSlot[int] = ContextSlot("demo", default=0)
    assert slot.get() == 0
    token = slot.set(42)
    assert slot.get() == 42
    slot.reset(token)
    assert slot.get() == 0


async def test_context_slot_child_task_inherits():
    slot: ContextSlot[str] = ContextSlot("inherit", default="root")
    token = slot.set("parent")

    async def child() -> str:
        return slot.get()

    assert await child() == "parent"
    slot.reset(token)
    assert await child() == "root"
