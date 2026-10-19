"""WAVE I gates: channel adapters via real local HTTP peers.

CHANNEL_REAL_ADAPTER_COUNT>=2 (telegram + slack, real httpx transport)
CHANNEL_SEND / RECEIVE / ACK / PROVIDER_REGISTRY
CHANNEL_PROJECT_POLICY=0 / NEW_CHANNEL_REGISTRY=0.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest

from obase.channel_adapter import (
    ChannelAdapter,
    SlackChannelAdapter,
    TelegramChannelAdapter,
    register_channel_adapters,
)
from obase.provider_registry import ProviderRegistry


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

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        path = urlparse(self.path).path
        if path.endswith("/sendMessage"):
            assert body["text"], "text required"
            self._send_json({"ok": True, "result": {"message_id": 1}})
        elif path.endswith("/chat.postMessage"):
            assert body["text"], "text required"
            self._send_json({"ok": True, "ts": "1700000000.0001"})
        else:
            self._send_json({"ok": False}, status=404)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.endswith("/getUpdates"):
            self._send_json(
                {
                    "ok": True,
                    "result": [
                        {"update_id": 11, "message": {"chat": {"id": 7}, "text": "hi", "date": 1}},
                        {"update_id": 12, "message": {"chat": {"id": 7}, "text": "yo", "date": 2}},
                    ],
                }
            )
        elif path.endswith("/conversations.history"):
            assert self.headers.get("Authorization", "").startswith("Bearer ")
            self._send_json(
                {
                    "ok": True,
                    "messages": [
                        {"ts": "1700000000.0002", "text": "hello"},
                    ],
                }
            )
        else:
            self._send_json({"ok": False}, status=404)


@pytest.fixture()
def peer_base():
    server = HTTPServer(("127.0.0.1", 0), _Peer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_protocol_contract(peer_base):
    for cls in (TelegramChannelAdapter, SlackChannelAdapter):
        assert isinstance(cls(token="t", api_base=peer_base), ChannelAdapter)


@pytest.mark.asyncio()
async def test_telegram_send_receive_ack(peer_base):
    adapter = TelegramChannelAdapter(token="tok", default_chat="7", api_base=peer_base)
    assert await adapter.send("7", "hello") is True
    messages = await adapter.receive(limit=10)
    assert [m.text for m in messages] == ["hi", "yo"]
    assert messages[0].chat == "7"
    assert await adapter.ack(messages[0].message_id) is True
    meta = await adapter.metadata()
    assert meta["adapter"] == "telegram" and meta["configured"] is True


@pytest.mark.asyncio()
async def test_slack_send_receive_ack(peer_base):
    adapter = SlackChannelAdapter(token="xoxb-tok", default_chat="C1", api_base=peer_base)
    assert await adapter.send("C1", "hello") is True
    messages = await adapter.receive(limit=10)
    assert [m.text for m in messages] == ["hello"]
    assert await adapter.ack(messages[0].message_id) is True
    meta = await adapter.metadata()
    assert meta["adapter"] == "slack" and meta["configured"] is True


@pytest.mark.asyncio()
async def test_unconfigured_honest():
    adapter = TelegramChannelAdapter(token="")
    assert await adapter.send("7", "hi") is False
    assert await adapter.receive() == []
    assert await adapter.ack("") is False


def test_provider_registry_and_no_new_registry(peer_base):
    ProviderRegistry.clear()
    try:
        names = register_channel_adapters(
            telegram={"token": "t", "api_base": peer_base},
            slack={"token": "s", "api_base": peer_base},
        )
        assert names == ["telegram", "slack"]
        listed = ProviderRegistry.list_providers("channel")
        assert sorted(n for _, n in listed) == ["slack", "telegram"]
    finally:
        ProviderRegistry.clear()
    import inspect as _inspect

    import obase.channel_adapter as mod

    assert not [
        n for n, o in vars(mod).items() if _inspect.isclass(o) and n.lower().endswith("registry")
    ]


def test_no_project_policy():
    import pathlib

    src = pathlib.Path(__file__).parent.parent.joinpath("obase/channel_adapter.py").read_text()
    for forbidden in (
        "conversation_policy",
        "approval_policy",
        "user_state",
        "BotIdentity",
        "business_state",
    ):
        assert forbidden not in src
