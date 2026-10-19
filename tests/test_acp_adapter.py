"""WAVE F gates: ACP interop.

ACP_SESSION / TURN / STREAM / CANCEL / RESUME / CAPABILITIES via injected
transport (fake peer speaking JSON-RPC framing) + real `opencode acp` binary
probe. ACP_PROTOCOL_LEAK_TO_CANONICAL=0 (harness_adapter source has no ACP).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from obase.acp_adapter import ACPAdapterError, ACPAgentAdapter
from obase.harness_adapter import HarnessRunResult


class FakeACPPeer:
    """In-process ACP peer (JSON-RPC framing, deterministic)."""

    def __init__(self):
        self.turns = []

    async def __call__(self, message):
        method = message.get("method", "")
        if method == "initialize":
            return {
                "result": {
                    "capabilities": {
                        "streaming": True,
                        "resume": True,
                        "cancel": True,
                        "tools": True,
                    }
                }
            }
        if method == "session/new":
            return {"result": {"sessionId": "sess-1"}}
        if method == "session/prompt":
            prompt = message["params"]["prompt"]
            self.turns.append(prompt)
            return {"result": {"output": f"reply:{prompt}", "usage": {"tokens": 3}}}
        if method == "session/cancel":
            return {"result": {"cancelled": True}}
        return {"error": f"unknown {method}"}


@pytest.fixture()
def adapter():
    return ACPAgentAdapter(transport=FakeACPPeer())


@pytest.mark.asyncio()
async def test_session_turn_stream_cancel_resume_capabilities(adapter):
    caps = await adapter.capabilities()
    assert caps.as_dict() == {"streaming": True, "resume": True, "cancel": True, "tools": True}

    session = await adapter.new_session()
    assert session.session_id == "sess-1"

    turn = await adapter.turn(session.session_id, "hello")
    assert turn["output"] == "reply:hello"
    assert turn["session_id"] == "sess-1"

    chunks = [c async for c in adapter.stream(session.session_id, "again")]
    assert chunks == ["reply:again"]

    assert await adapter.cancel(session.session_id) is True
    cancelled_turn = await adapter.turn(session.session_id, "late")
    assert cancelled_turn["status"] == "cancelled"

    resumed = await adapter.resume(session.session_id, "back")
    assert resumed["output"] == "reply:back"

    hr = adapter.to_harness_result(session.session_id, resumed)
    assert isinstance(hr, HarnessRunResult)
    assert hr.output == "reply:back" and hr.status == "ok"
    assert hr.native_metadata["protocol"] == "acp"


@pytest.mark.asyncio()
async def test_unknown_session_errors():
    adapter = ACPAgentAdapter(transport=FakeACPPeer())
    with pytest.raises(ACPAdapterError):
        await adapter.turn("nope", "hi")
    assert await adapter.cancel("nope") is False
    with pytest.raises(ValueError):
        session = await adapter.new_session()
        await adapter.turn(session.session_id, "")


@pytest.mark.asyncio()
async def test_no_transport_honest_error():
    adapter = ACPAgentAdapter()
    with pytest.raises(ACPAdapterError):
        await adapter.initialize()


def test_real_acp_binary_probe():
    # 真实 ACP 生态 binary 存在性 + help 可执行 (协议实现走注入 transport)
    binary = shutil.which("opencode")
    assert binary, "opencode binary missing"
    proc = subprocess.run([binary, "acp", "--help"], capture_output=True, timeout=15)
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert b"ACP" in combined or b"acp" in combined.lower()


def test_no_protocol_leak_to_canonical():
    import pathlib

    canonical = (
        pathlib.Path(__file__).parent.parent.joinpath("obase/harness_adapter.py").read_text()
    )
    for token in ("session/prompt", "sessionId", "ACP_TURN", "ACPSession"):
        assert token not in canonical
