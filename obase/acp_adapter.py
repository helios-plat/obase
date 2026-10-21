"""obase.acp_adapter — ACP (Agent Client Protocol) adapter.

WAVE F owner: obase. ACP 只负责 client↔agent protocol:
initialize/session, prompt/turn, stream, cancel, resume, capabilities.

ACP-specific message schema 不得泄漏为统一 HarnessAdapter contract;
允许内部 adapt to HarnessRunResult (见 to_harness_result)。
"""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from obase.provider_routing import ProtocolFamily

__all__ = [
    "ACPAgentAdapter",
    "ACPAdapterError",
    "ACPCapabilities",
    "ACPSession",
    "ACP_TURN_METHOD",
    "ACP_INITIALIZE_METHOD",
]


class ACPAdapterError(RuntimeError):
    """ACP protocol 错误。"""


ACP_INITIALIZE_METHOD = "initialize"
ACP_TURN_METHOD = "session/prompt"


@dataclass
class ACPCapabilities:
    """ACP agent capabilities (protocol shapes only)。

    D5: ``supports_mcp_attachment`` / ``supports_mcp_refresh`` /
    ``supports_session_close`` are declaration-driven — set only from
    explicit upstream ``initialize`` evidence, defaulting to ``False``.
    ``as_dict`` keeps the original four transport keys (pinned contract);
    the D5 flags are read as attributes.
    """

    streaming: bool = False
    resume: bool = False
    cancel: bool = False
    tools: bool = False
    supports_mcp_attachment: bool = False
    supports_mcp_refresh: bool = False
    supports_session_close: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, bool]:
        return {
            "streaming": self.streaming,
            "resume": self.resume,
            "cancel": self.cancel,
            "tools": self.tools,
        }


@dataclass
class ACPSession:
    """ACP 会话句柄 (protocol id + 本地运行态,无业务态)。"""

    session_id: str
    run_id: str
    status: str = "active"
    started_at: float = field(default_factory=time.time)


class ACPAgentAdapter:
    """ACP client adapter (protocol only)。

    transport 经注入的 async callable (json-rpc message -> response);
    不持有 ACP 之外的统一语义,不做 approval/delegation/项目态。
    """

    protocol_family: ProtocolFamily = ProtocolFamily.ACP

    def __init__(self, *, transport: Any = None, timeout_s: float = 60.0) -> None:
        self.transport = transport
        self.timeout_s = timeout_s
        self._sessions: dict[str, ACPSession] = {}
        self._cancelled: set[str] = set()

    async def _send(self, message: dict[str, Any]) -> Any:
        if self.transport is None:
            raise ACPAdapterError("ACPAgentAdapter: no transport injected")
        raw = self.transport(message)
        result = await raw if inspect.isawaitable(raw) else raw
        if isinstance(result, dict) and result.get("error"):
            raise ACPAdapterError(f"ACP error: {result['error']}")
        return result.get("result", result) if isinstance(result, dict) else result

    # -- initialize / session --------------------------------------------------
    async def initialize(self, *, client_name: str = "3o-acp-client") -> dict[str, Any]:
        """ACP initialize 握手,返回 server capabilities (raw)。"""
        result = await self._send(
            {
                "jsonrpc": "2.0",
                "id": uuid.uuid4().hex[:8],
                "method": ACP_INITIALIZE_METHOD,
                "params": {"client": client_name, "protocol": "acp/0.1"},
            }
        )
        return result if isinstance(result, dict) else {"raw": result}

    async def new_session(self, **kwargs: Any) -> ACPSession:
        """建 ACP session (session/new),返回会话句柄。"""
        result = await self._send(
            {
                "jsonrpc": "2.0",
                "id": uuid.uuid4().hex[:8],
                "method": "session/new",
                "params": dict(kwargs),
            }
        )
        session_id = ""
        if isinstance(result, dict):
            session_id = str(result.get("sessionId") or result.get("session_id") or "")
        if not session_id:
            session_id = f"acp_{uuid.uuid4().hex[:12]}"
        session = ACPSession(session_id=session_id, run_id=f"acp_{uuid.uuid4().hex[:8]}")
        self._sessions[session.session_id] = session
        return session

    async def capabilities(self) -> ACPCapabilities:
        """取 ACP capabilities (initialize 握手派生,声明驱动)。"""
        init = await self.initialize()
        caps = init.get("capabilities", init) if isinstance(init, dict) else {}
        if not isinstance(caps, dict):
            caps = {}
        mcp_declared = caps.get("mcp") if isinstance(caps.get("mcp"), dict) else {}
        return ACPCapabilities(
            streaming=bool(caps.get("streaming", False)),
            resume=bool(caps.get("resume", False)),
            cancel=bool(caps.get("cancel", True)),
            tools=bool(caps.get("tools", False)),
            supports_mcp_attachment=bool(
                mcp_declared.get("attachment", mcp_declared.get("attach", False))
            ),
            supports_mcp_refresh=bool(mcp_declared.get("refresh", False)),
            supports_session_close=bool(caps.get("session_close", caps.get("close", False))),
            raw=caps,
        )

    # -- prompt / turn / stream / cancel / resume --------------------------------
    async def turn(self, session_id: str, prompt: str) -> dict[str, Any]:
        """单轮 prompt (session/prompt),返回原生 turn 结果。"""
        if session_id not in self._sessions:
            raise ACPAdapterError(f"unknown ACP session: {session_id}")
        if not prompt:
            raise ValueError("ACPAgentAdapter.turn: prompt must not be empty")
        if session_id in self._cancelled:
            return {"session_id": session_id, "status": "cancelled", "output": ""}
        result = await self._send(
            {
                "jsonrpc": "2.0",
                "id": uuid.uuid4().hex[:8],
                "method": ACP_TURN_METHOD,
                "params": {"sessionId": session_id, "prompt": prompt},
            }
        )
        if isinstance(result, dict):
            return {"session_id": session_id, **result}
        return {"session_id": session_id, "output": str(result)}

    async def stream(self, session_id: str, prompt: str) -> AsyncIterator[str]:
        """流式 turn: yield 文本块 (原生块或整包回退)。"""
        result = await self.turn(session_id, prompt)
        output = result.get("output", "")
        if isinstance(output, list):
            for chunk in output:
                yield str(chunk)
        elif output:
            yield str(output)

    async def cancel(self, session_id: str) -> bool:
        """取消会话 (session/cancel + 本地标记)。"""
        if session_id not in self._sessions:
            return False
        self._cancelled.add(session_id)
        try:
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "id": uuid.uuid4().hex[:8],
                    "method": "session/cancel",
                    "params": {"sessionId": session_id},
                }
            )
        except ACPAdapterError:
            pass
        session = self._sessions[session_id]
        session.status = "cancelled"
        return True

    async def resume(self, session_id: str, prompt: str = "") -> dict[str, Any]:
        """恢复会话:本地标记恢复 + 可选 follow-up turn。"""
        session = self._sessions.get(session_id)
        if session is None:
            raise ACPAdapterError(f"unknown ACP session: {session_id}")
        self._cancelled.discard(session_id)
        session.status = "active"
        if prompt:
            return await self.turn(session_id, prompt)
        return {"session_id": session_id, "status": "active"}

    async def close(self, session_id: str) -> dict[str, Any]:
        """关闭会话:尽力而为的远端 session/close + 保证本地 detach。

        D5 session-scoped teardown contract. 幂等:未知会话也返回成功
        (无可清理)。若对端不支持远端关闭,诚实报告
        ``remote_close_supported=False`` 而不伪装,本地 detach 照常完成。
        """
        remote_supported: bool | None = None
        remote_error: str | None = None
        if session_id in self._sessions:
            try:
                await self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": uuid.uuid4().hex[:8],
                        "method": "session/close",
                        "params": {"sessionId": session_id},
                    }
                )
                remote_supported = True
            except ACPAdapterError as exc:
                remote_supported = False
                remote_error = str(exc)
        self._sessions.pop(session_id, None)
        self._cancelled.discard(session_id)
        return {
            "session_id": session_id,
            "closed": True,
            "remote_close_supported": bool(remote_supported),
            "remote_close_error": remote_error,
        }

    # -- 内部: adapt to HarnessRunResult (不反向污染 canonical contract) ---------
    def to_harness_result(self, session_id: str, turn_result: dict[str, Any]) -> Any:
        """ACP turn -> HarnessRunResult (延迟导入,避免 schema 泄漏)。"""
        from obase.harness_adapter import HarnessRunResult, normalize_status

        session = self._sessions.get(session_id)
        return HarnessRunResult(
            run_id=session.run_id if session else session_id,
            status=normalize_status(turn_result.get("status", "completed")),
            output=str(turn_result.get("output", "")),
            usage=dict(turn_result.get("usage") or {}),
            error=turn_result.get("error"),
            native_metadata={"acp_session": session_id, "protocol": "acp"},
        )
