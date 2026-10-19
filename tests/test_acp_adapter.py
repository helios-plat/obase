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
    assert hr.output == "reply:back" and hr.status == "completed"
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
    if binary is None:
        pytest.skip("opencode binary is not installed")
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


class DeclaringPeer(FakeACPPeer):
    """Peer whose initialize declares MCP attachment/refresh + session close."""

    async def __call__(self, message):
        if message.get("method") == "initialize":
            return {
                "result": {
                    "capabilities": {
                        "streaming": True,
                        "resume": True,
                        "cancel": True,
                        "tools": True,
                        "mcp": {"attach": True, "refresh": True},
                        "session_close": True,
                    }
                }
            }
        if message.get("method") == "session/close":
            return {"result": {"closed": True}}
        return await super().__call__(message)


@pytest.mark.asyncio()
async def test_capabilities_default_honest_false(adapter):
    caps = await adapter.capabilities()
    assert caps.as_dict() == {"streaming": True, "resume": True, "cancel": True, "tools": True}
    assert caps.supports_mcp_attachment is False
    assert caps.supports_mcp_refresh is False
    assert caps.supports_session_close is False


@pytest.mark.asyncio()
async def test_capabilities_from_upstream_declaration():
    adapter = ACPAgentAdapter(transport=DeclaringPeer())
    caps = await adapter.capabilities()
    assert caps.supports_mcp_attachment is True
    assert caps.supports_mcp_refresh is True
    assert caps.supports_session_close is True


@pytest.mark.asyncio()
async def test_close_remote_supported_and_idempotent():
    adapter = ACPAgentAdapter(transport=DeclaringPeer())
    session = await adapter.new_session()
    first = await adapter.close(session.session_id)
    assert first == {
        "session_id": session.session_id,
        "closed": True,
        "remote_close_supported": True,
        "remote_close_error": None,
    }
    second = await adapter.close(session.session_id)
    assert second["closed"] is True
    assert second["remote_close_supported"] is False


@pytest.mark.asyncio()
async def test_close_remote_unsupported_still_detaches(adapter):
    session = await adapter.new_session()
    result = await adapter.close(session.session_id)
    assert result["closed"] is True
    assert result["remote_close_supported"] is False
    assert result["remote_close_error"]
    with pytest.raises(ACPAdapterError):
        await adapter.turn(session.session_id, "after close")
