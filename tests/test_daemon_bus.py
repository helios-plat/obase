from __future__ import annotations

import pytest

from obase import DaemonBusProvider, HitlSignalBus
from obase.daemon_bus import IDaemon_Bus, InProcessDaemonBus


@pytest.mark.asyncio
async def test_in_process_daemon_bus_fanout_and_topic_isolation():
    bus = InProcessDaemonBus()
    first = await bus.subscribe("events/a")
    second = await bus.subscribe("events/a")
    unrelated = await bus.subscribe("events/b")
    assert isinstance(bus, IDaemon_Bus)
    assert DaemonBusProvider is IDaemon_Bus
    await bus.publish("events/a", {"kind": "created", "n": 1})
    assert await first.receive() == {"kind": "created", "n": 1}
    assert await second.receive() == {"kind": "created", "n": 1}
    assert unrelated._queue.empty()
    first.close()
    second.close()
    unrelated.close()


@pytest.mark.asyncio
async def test_in_process_daemon_bus_copies_payload_and_validates_inputs():
    bus = InProcessDaemonBus()
    sub = await bus.subscribe("topic")
    payload = {"nested": {"value": 1}}
    await bus.publish("topic", payload)
    payload["nested"]["value"] = 9
    assert await sub.receive() == {"nested": {"value": 1}}
    with pytest.raises(ValueError, match="non-empty"):
        await bus.subscribe(" ")
    with pytest.raises(TypeError, match="dictionary"):
        await bus.publish("topic", "not-a-dict")  # type: ignore[arg-type]
    sub.close()


def test_hitl_signal_bus_interrupt_state_and_clear():
    bus = HitlSignalBus()
    assert bus.interrupted is False
    assert bus.interrupt_reason == ""
    bus.signal_interrupt(reason="user stop")
    assert bus.interrupted is True
    assert bus.interrupt_reason == "user stop"
    bus.clear_interrupt()
    assert bus.interrupted is False
    assert bus.interrupt_reason == ""


def test_hitl_signal_bus_interrupt_state_and_clear():
    bus = HitlSignalBus()
    assert bus.interrupted is False
    assert bus.interrupt_reason == ""
    bus.signal_interrupt(reason="user stop")
    assert bus.interrupted is True
    assert bus.interrupt_reason == "user stop"
    bus.clear_interrupt()
    assert bus.interrupted is False
    assert bus.interrupt_reason == ""
