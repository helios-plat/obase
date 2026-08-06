"""obase.mcp_stdio — stdio transport MCP 客户端 (JSON-RPC 2.0, LSP 帧)。

通用机制: spawn 任意 stdio MCP 服务器二进制 (如 codebase-memory-mcp),
实现 McpClientHandle 协议 (list_tools / call_tool), 供 McpClientRegistry 注册。

- 帧协议: ``Content-Length: N\\r\\n\\r\\n<json>`` (MCP stdio 标准);
- 生命周期: start() 握手 initialize → 可用; close() 终止进程;
- 崩溃检测: poll + stderr 尾部留存 (diagnose 用);
- 并发: 单请求串行 (asyncio.Lock), 响应按 id 匹配。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .mcp_client import McpClientHandle, McpClientRegistry


class StdioMcpError(RuntimeError):
    """stdio MCP 客户端错误 (握手失败 / 进程退出 / 超时)。"""


def _encode_frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def _decode_frames(buf: bytes) -> tuple[list[dict[str, Any]], bytes]:
    """解出完整帧, 返回 (frames, 剩余未完成字节)。"""
    frames: list[dict[str, Any]] = []
    rest = buf
    while True:
        head_end = rest.find(b"\r\n\r\n")
        if head_end < 0:
            break
        header = rest[:head_end].decode("utf-8", errors="replace")
        length = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body_start = head_end + 4
        if len(rest) < body_start + length:
            break
        body = rest[body_start:body_start + length]
        try:
            frames.append(json.loads(body))
        except json.JSONDecodeError:
            pass  # 坏帧丢弃, 不阻断后续
        rest = rest[body_start + length:]
    return frames, rest


class StdioMcpClient:
    """stdio transport MCP 客户端 (McpClientHandle 协议实现)。

    Usage::

        client = StdioMcpClient(["codebase-memory-mcp"])
        await client.start()
        await client.list_tools()
        await client.call_tool("search_graph", {...})
        await client.close()
    """

    def __init__(
        self,
        cmd: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float = 15.0,
        request_timeout: float = 60.0,
        name: str = "stdio-mcp",
    ) -> None:
        self.cmd = list(cmd)
        self.cwd = str(cwd) if cwd else None
        self.env = env
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.name = name

        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._buf = b""
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._stderr_tail: list[str] = []
        self._started = False
        self._read_task: asyncio.Task | None = None

    # ── 生命周期 ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """spawn 进程 + initialize 握手。幂等。"""
        if self._started:
            return
        self._proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            cwd=self.cwd,
            env=self.env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader = self._proc.stdout
        self._writer = self._proc.stdin
        self._read_task = asyncio.create_task(self._read_loop())
        asyncio.create_task(self._drain_stderr())

        await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "veya-stdio-mcp", "version": "0.1"},
            },
            timeout=self.startup_timeout,
        )
        await self._notify("notifications/initialized")
        self._started = True

    async def close(self) -> None:
        """终止子进程 (SIGTERM → 2s 后 SIGKILL)。"""
        if self._read_task:
            self._read_task.cancel()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                if self._proc and self._proc.returncode is None:
                    self._proc.kill()
        self._started = False

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "alive": self.alive,
            "started": self._started,
            "stderr_tail": self._stderr_tail[-5:],
        }

    # ── McpClientHandle 协议 ───────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        res = await self._request("tools/list", {}, timeout=self.request_timeout)
        return (res or {}).get("tools", [])

    async def call_tool(self, name: str, args: dict) -> Any:
        res = await self._request(
            "tools/call", {"name": name, "arguments": args}, timeout=self.request_timeout
        )
        if isinstance(res, dict) and res.get("isError"):
            raise StdioMcpError(f"tool {name!r} 返回错误: {res.get('content')}")
        return res

    # ── 内部 ───────────────────────────────────────────────────────────

    async def _request(self, method: str, params: dict, *, timeout: float) -> Any:
        if not self.alive:
            raise StdioMcpError(f"{self.name}: 进程已退出 (rc={self._proc.returncode if self._proc else '?'})")
        async with self._lock:
            rid = self._next_id
            self._next_id += 1
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[rid] = fut
            self._writer.write(_encode_frame({"jsonrpc": "2.0", "id": rid,
                                              "method": method, "params": params}))
            await self._writer.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise StdioMcpError(f"{self.name}: {method} 超时 ({timeout}s)") from None

    async def _notify(self, method: str, params: dict | None = None) -> None:
        self._writer.write(_encode_frame({"jsonrpc": "2.0", "method": method,
                                          "params": params or {}}))
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while self._proc and self._reader:
                chunk = await self._reader.read(65536)
                if not chunk:
                    break
                self._buf += chunk
                frames, self._buf = _decode_frames(self._buf)
                for frame in frames:
                    await self._dispatch(frame)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            # 进程退出: 失败所有 pending
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(StdioMcpError(f"{self.name}: 连接关闭"))
            self._pending.clear()

    async def _dispatch(self, frame: dict[str, Any]) -> None:
        if "id" in frame:
            fut = self._pending.pop(frame["id"], None)
            if fut and not fut.done():
                if "error" in frame:
                    fut.set_exception(StdioMcpError(
                        f"{self.name}: {frame['error']}"))
                else:
                    fut.set_result(frame.get("result"))

    async def _drain_stderr(self) -> None:
        try:
            while self._proc and self._proc.stderr:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                self._stderr_tail.append(line.decode("utf-8", errors="replace").strip())
                self._stderr_tail = self._stderr_tail[-50:]
        except (asyncio.CancelledError, AttributeError):
            pass


__all__ = ["StdioMcpClient", "StdioMcpError", "McpClientRegistry", "McpClientHandle"]
