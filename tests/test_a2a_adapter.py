"""WAVE E gates: A2A interop via real local HTTP peer.

A2A_CAPABILITY_DISCOVERY / INVOKE / STREAM / CANCEL / RESULT_NORMALIZATION
A2A_ORCHESTRATION_LOGIC=0 (source scan: no delegation/selection/planning).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from obase.a2a_adapter import (
    A2AAdapterError,
    A2AAgentAdapter,
    normalize_a2a_result,
)


class _Peer(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/.well-known/agent.json":
            self._send_json(
                {
                    "name": "peer-agent",
                    "url": f"http://127.0.0.1:{self.server.server_port}",
                    "capabilities": {"streaming": True, "pushNotifications": False},
                    "skills": [{"name": "echo"}],
                }
            )
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        msg = json.loads(self.rfile.read(length) or b"{}")
        method = msg.get("method", "")
        if method == "message/send":
            text = msg["params"]["message"]["parts"][0]["text"]
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "result": {
                        "id": "task-1",
                        "state": "completed",
                        "artifacts": [{"parts": [{"text": f"echo:{text}"}]}],
                        "usage": {"tokens": 7},
                    },
                }
            )
        elif method == "tasks/cancel":
            self._send_json({"jsonrpc": "2.0", "id": msg.get("id"), "result": {"id": "task-1"}})
        elif method == "tasks/get":
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "result": {
                        "id": "task-1",
                        "state": "completed",
                        "artifacts": [{"parts": [{"text": "echo:hi"}]}],
                    },
                }
            )
        else:
            self._send_json({"jsonrpc": "2.0", "id": msg.get("id"), "error": f"unknown {method}"})


@pytest.fixture()
def peer_url():
    server = HTTPServer(("127.0.0.1", 0), _Peer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.mark.asyncio()
async def test_capability_discovery(peer_url):
    adapter = A2AAgentAdapter(agent_url=peer_url)
    caps = await adapter.discover_capabilities()
    assert caps.name == "peer-agent"
    assert caps.streaming is True
    assert caps.skills == [{"name": "echo"}]


@pytest.mark.asyncio()
async def test_invoke_stream_cancel_status(peer_url):
    adapter = A2AAgentAdapter(agent_url=peer_url)
    result = await adapter.invoke("hi")
    assert result.status == "ok"
    assert result.output == "echo:hi"
    assert result.usage == {"tokens": 7}

    chunks = [c async for c in adapter.stream("hi")]
    assert chunks == ["echo:hi"]

    st = await adapter.status(result.task_id)
    assert st["task_id"] == result.task_id

    assert await adapter.cancel(result.task_id) is True
    assert await adapter.cancel("unknown-task") is False


@pytest.mark.asyncio()
async def test_discovery_failure_honest():
    adapter = A2AAgentAdapter(agent_url="http://127.0.0.1:1", timeout_s=2)
    with pytest.raises(A2AAdapterError):
        await adapter.discover_capabilities()


def test_normalize_matrix():
    assert normalize_a2a_result("t", {"state": "completed"}).status == "ok"
    assert normalize_a2a_result("t", {"state": "failed"}).status == "error"
    assert normalize_a2a_result("t", {"state": "canceled"}).status == "cancelled"
    assert normalize_a2a_result("t", {"error": "boom"}).status == "error"
    assert normalize_a2a_result("t", "garbage").status == "error"


def test_no_orchestration_logic():
    import pathlib

    src = pathlib.Path(__file__).parent.parent.joinpath("obase/a2a_adapter.py").read_text()
    for forbidden in (
        "delegation_policy",
        "agent_selection",
        "goal_planning",
        "business_retry",
        "project_state",
        "SubagentOrchestrator",
    ):
        assert forbidden not in src


def test_requires_transport_or_url():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        A2AAgentAdapter()
