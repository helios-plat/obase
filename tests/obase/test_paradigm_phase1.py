"""3O 范式 Phase 1 — obase 契约层与基础实现冒烟测试。

验证面向契约编程 (ABC 不可实例化) + 5 大基础设施元素可用。
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from obase import (
    HttpLLMClient,
    IDaemon_Bus,
    IEvent_Barrier,
    IKV_Store,
    ILLM_Client,
    IVFS_Sandbox,
    LocalVFS,
    SQLiteKVStore,
)
from obase.daemon_bus import InProcessDaemonBus
from obase.event_barrier import InProcessEventBarrier
from obase.vfs_sandbox import VFSPathTraversalError

CONTRACTS = [IDaemon_Bus, IEvent_Barrier, IKV_Store, ILLM_Client, IVFS_Sandbox]


def test_contracts_are_abstract():
    """契约类必须不可直接实例化 (面向契约编程)。"""
    for contract in CONTRACTS:
        with pytest.raises(TypeError):
            contract()  # type: ignore[abstract]


def test_phase1_exports_available():
    """5 大元素全部经 obase 包收口导出。"""
    for name in (
        "IDaemon_Bus",
        "IEvent_Barrier",
        "IKV_Store",
        "ILLM_Client",
        "IVFS_Sandbox",
        "LocalVFS",
        "HttpLLMClient",
        "SQLiteKVStore",
    ):
        assert name in __import__("obase").__all__


async def test_local_vfs_execute_and_files(tmp_path):
    vfs = LocalVFS(str(tmp_path))
    result = await vfs.execute_isolated("echo hello-obase")
    assert result["exit_code"] == 0
    assert "hello-obase" in result["stdout"]

    await vfs.write_file("a/b.txt", b"payload")
    assert await vfs.read_file("a/b.txt") == b"payload"

    # 路径穿越保护
    with pytest.raises(VFSPathTraversalError):
        await vfs.read_file("../outside.txt")


async def test_local_vfs_timeout(tmp_path):
    vfs = LocalVFS(str(tmp_path))
    result = await vfs.execute_isolated("sleep 5", timeout=1)
    assert result["exit_code"] == -1
    assert "Timeout" in result["stderr"]


async def test_sqlite_kv_store_roundtrip(tmp_path):
    store = SQLiteKVStore(str(tmp_path / "kv.db"))
    await store.put("session/alpha", {"state": 1})
    await store.put("session/beta", {"state": 2})
    await store.put("other/gamma", {"state": 3})

    assert await store.get("session/alpha") == {"state": 1}
    assert await store.get("missing") is None

    values = await store.list_prefix("session/")
    assert len(values) == 2
    assert {"state": 1} in values
    assert {"state": 2} in values

    # 原子覆盖
    await store.put("session/alpha", {"state": 99})
    assert await store.get("session/alpha") == {"state": 99}


async def test_in_process_daemon_bus():
    bus = InProcessDaemonBus()
    sub = await bus.subscribe("topic/a")
    await bus.publish("topic/a", {"n": 1})
    assert await sub.receive() == {"n": 1}
    sub.close()
    await bus.publish("topic/a", {"n": 2})  # 退订后不报错


async def test_in_process_event_barrier():
    barrier = InProcessEventBarrier()
    assert await barrier.wait_for_event("booted", timeout=0.05) is False
    await barrier.set_event("booted")
    assert await barrier.wait_for_event("booted", timeout=0.05) is True


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = b"chunk-one|chunk-two"
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def echo_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/stream"
    server.shutdown()


async def test_http_llm_client_streams(echo_server):
    client = HttpLLMClient(timeout=5.0)
    chunks = []
    async for chunk in client.stream_request(echo_server, {"k": "v"}, {"X-Test": "1"}):
        chunks.append(chunk)
    assert b"".join(chunks) == b"chunk-one|chunk-two"
