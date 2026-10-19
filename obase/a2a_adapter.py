"""obase.a2a_adapter — A2A (Agent-to-Agent) protocol adapter.

WAVE E owner: obase. A2A 只负责 transport/protocol:
capability discovery / remote invoke / stream / cancel / status /
result normalization.

与编排引擎组合时: A2A = transport,编排引擎 = scheduling. 本模块不做
delegation policy / agent selection semantics / goal planning /
business retries / project state.
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
    "A2AAgentAdapter",
    "A2AAdapterError",
    "A2ACapabilities",
    "A2AResult",
    "normalize_a2a_result",
]


class A2AAdapterError(RuntimeError):
    """A2A transport/protocol 错误。"""


@dataclass
class A2ACapabilities:
    """远端 agent capability (来自 agent card, shapes only)。"""

    name: str = ""
    url: str = ""
    streaming: bool = False
    push_notifications: bool = False
    skills: list[dict[str, Any]] = field(default_factory=list)
    raw_card: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "streaming": self.streaming,
            "push_notifications": self.push_notifications,
            "skills": self.skills,
        }


@dataclass
class A2AResult:
    """归一化远端调用结果。"""

    task_id: str
    status: str  # "ok" | "error" | "cancelled" | "working"
    output: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    native_metadata: dict[str, Any] = field(default_factory=dict)


def normalize_a2a_result(task_id: str, payload: Any) -> A2AResult:
    """A2A task payload -> 归一化结果 (纯函数,无状态)。"""
    if not isinstance(payload, dict):
        return A2AResult(task_id=task_id, status="error", error=f"non-dict payload: {payload!r}")
    state = str(payload.get("state") or payload.get("status") or "").lower()
    if state in ("completed", "ok", "done", "succeeded"):
        status = "ok"
    elif state in ("canceled", "cancelled"):
        status = "cancelled"
    elif state in ("failed", "error", "rejected"):
        status = "error"
    else:
        status = "working" if state else "ok"
    output = ""
    artifacts = payload.get("artifacts") or []
    if isinstance(artifacts, list):
        parts = []
        for artifact in artifacts:
            if isinstance(artifact, dict):
                for part in artifact.get("parts", []):
                    if isinstance(part, dict) and part.get("text"):
                        parts.append(str(part["text"]))
        output = "\n".join(parts)
    if not output:
        output = str(payload.get("output") or payload.get("result") or "")
    error = payload.get("error")
    return A2AResult(
        task_id=task_id,
        status="error" if error else status,
        output=output,
        usage=dict(payload.get("usage") or {}),
        error=str(error) if error else None,
        native_metadata={"raw_state": state},
    )


class A2AAgentAdapter:
    """A2A protocol adapter (transport only,无 orchestration 语义)。

    transport 经注入的 async callable (message -> response) 或 agent base_url
    (httpx JSON-RPC) 二选一;不持有 delegation/selection/planning/重试/项目态。
    """

    protocol_family: ProtocolFamily = ProtocolFamily.A2A

    def __init__(
        self,
        *,
        agent_url: str | None = None,
        transport: Any | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        if agent_url is None and transport is None:
            raise ValueError("A2AAgentAdapter: agent_url 或 transport 必须提供其一")
        self.agent_url = (agent_url or "").rstrip("/")
        self.transport = transport
        self.timeout_s = timeout_s
        self._capabilities: A2ACapabilities | None = None
        self._tasks: dict[str, dict[str, Any]] = {}

    # -- capability discovery -------------------------------------------------
    async def discover_capabilities(self) -> A2ACapabilities:
        """拉取远端 agent card (/.well-known/agent.json), shapes only。"""
        import httpx

        if self.transport is not None:
            raw = self.transport({"method": "agent.getCard", "params": {}})
            card = await raw if inspect.isawaitable(raw) else raw
            return self._card_to_capabilities(card if isinstance(card, dict) else {})
        url = f"{self.agent_url}/.well-known/agent.json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                card = resp.json()
        except Exception as exc:
            raise A2AAdapterError(f"capability discovery failed for {url}: {exc}") from exc
        self._capabilities = self._card_to_capabilities(card if isinstance(card, dict) else {})
        return self._capabilities

    @staticmethod
    def _card_to_capabilities(card: dict[str, Any]) -> A2ACapabilities:
        caps = card.get("capabilities") or {}
        return A2ACapabilities(
            name=str(card.get("name", "")),
            url=str(card.get("url", "")),
            streaming=bool(caps.get("streaming", False)),
            push_notifications=bool(caps.get("pushNotifications", False)),
            skills=list(card.get("skills") or []),
            raw_card=card,
        )

    # -- remote invoke / stream / cancel / status ------------------------------
    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        import httpx

        if self.transport is not None:
            raw = self.transport({"method": method, "params": params})
            return await raw if inspect.isawaitable(raw) else raw
        payload = {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:8], "method": method, "params": params}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(self.agent_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise A2AAdapterError(f"A2A rpc {method} failed: {exc}") from exc
        if isinstance(data, dict) and data.get("error"):
            raise A2AAdapterError(f"A2A rpc {method} error: {data['error']}")
        return data.get("result") if isinstance(data, dict) else data

    async def invoke(self, message: str, *, context_id: str | None = None) -> A2AResult:
        """远端调用 (message/send),返回归一化结果。"""
        if not message:
            raise ValueError("A2AAgentAdapter.invoke: message must not be empty")
        task_id = f"a2a_{uuid.uuid4().hex[:12]}"
        params: dict[str, Any] = {"message": {"role": "user", "parts": [{"text": message}]}}
        if context_id:
            params["context_id"] = context_id
        raw = await self._rpc("message/send", params)
        task = raw if isinstance(raw, dict) else {"output": raw}
        task_id = str(task.get("id") or task_id)
        self._tasks[task_id] = {"status": "submitted", "ts": time.time()}
        result = normalize_a2a_result(task_id, task)
        self._tasks[task_id]["status"] = result.status
        return result

    async def stream(self, message: str, **kwargs: Any) -> AsyncIterator[str]:
        """流式调用: yield 文本块 (transport 原生块或单次结果)。"""
        result = await self.invoke(message, **kwargs)
        if result.output:
            yield result.output

    async def cancel(self, task_id: str) -> bool:
        """取消远端 task (tasks/cancel),远端无此 task 返回 False。"""
        if task_id not in self._tasks:
            return False
        try:
            await self._rpc("tasks/cancel", {"id": task_id})
        except A2AAdapterError:
            return False
        self._tasks[task_id]["status"] = "cancelled"
        return True

    async def status(self, task_id: str) -> dict[str, Any]:
        """task 状态 (tasks/get),远端不支持则返回本地记录。"""
        tracked = self._tasks.get(task_id)
        if tracked is None:
            return {"task_id": task_id, "status": "unknown"}
        try:
            raw = await self._rpc("tasks/get", {"id": task_id})
            if isinstance(raw, dict):
                return {"task_id": task_id, **normalize_a2a_result(task_id, raw).__dict__}
        except A2AAdapterError:
            pass
        return {"task_id": task_id, "status": tracked.get("status", "unknown")}
