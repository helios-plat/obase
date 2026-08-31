"""Browser infrastructure types and the optional Playwright adapter.

The adapter owns browser-driver details and session handles only.  Policy,
takeover decisions, transactions, and Veya task context stay in higher 3O
layers.  Playwright is imported lazily so the value types remain usable in
environments that do not install a browser driver.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol, cast

BrowserControlState = Literal["AGENT_CONTROL", "HUMAN_CONTROL"]
BrowserSessionState = Literal["created", "running", "attached", "stopped", "failed"]


@dataclass(frozen=True)
class BrowserProfile:
    """Declarative browser configuration bound to an existing computer."""

    id: str
    computer_id: str = ""
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    timeout_ms: int = 30_000
    storage_state_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "computer_id": self.computer_id,
            "headless": self.headless,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "timeout_ms": self.timeout_ms,
            "storage_state_path": self.storage_state_path,
        }


@dataclass(frozen=True)
class BrowserSessionHandle:
    """Opaque browser session reference returned by browser atomics."""

    session_id: str
    profile_id: str
    computer_id: str
    state: BrowserSessionState = "created"
    control_state: BrowserControlState = "AGENT_CONTROL"
    url: str = ""
    attached: bool = False
    owner_id: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "computer_id": self.computer_id,
            "state": self.state,
            "control_state": self.control_state,
            "url": self.url,
            "attached": self.attached,
            "owner_id": self.owner_id,
            "version": self.version,
        }


class BrowserAdapter(Protocol):
    """Driver adapter contract consumed by browser atomics."""

    def create(self, profile: BrowserProfile) -> Any: ...

    def start(self, handle: BrowserSessionHandle) -> Any: ...

    def status(self, handle: BrowserSessionHandle) -> Any: ...

    def attach(self, handle: BrowserSessionHandle) -> Any: ...

    def stop(self, handle: BrowserSessionHandle) -> Any: ...

    def reset(self, handle: BrowserSessionHandle) -> Any: ...

    def set_control_state(
        self, handle: BrowserSessionHandle, state: BrowserControlState
    ) -> Any: ...

    def navigate(self, handle: BrowserSessionHandle, url: str, **kwargs: Any) -> Any: ...

    def snapshot(self, handle: BrowserSessionHandle, **kwargs: Any) -> Any: ...

    def click(self, handle: BrowserSessionHandle, selector: str, **kwargs: Any) -> Any: ...

    def type(
        self, handle: BrowserSessionHandle, selector: str, text: str, **kwargs: Any
    ) -> Any: ...

    def download(self, handle: BrowserSessionHandle, selector: str, **kwargs: Any) -> Any: ...

    def upload(
        self, handle: BrowserSessionHandle, selector: str, file_paths: Any, **kwargs: Any
    ) -> Any: ...

    def screenshot(self, handle: BrowserSessionHandle, **kwargs: Any) -> Any: ...


@dataclass
class _PlaywrightRecord:
    profile: BrowserProfile
    handle: BrowserSessionHandle
    playwright: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None


def _as_profile(value: BrowserProfile | Mapping[str, Any]) -> BrowserProfile:
    if isinstance(value, BrowserProfile):
        return value
    if isinstance(value, Mapping):
        return BrowserProfile(**dict(value))
    raise TypeError("profile must be a BrowserProfile or mapping")


def _as_handle(value: BrowserSessionHandle | Mapping[str, Any]) -> BrowserSessionHandle:
    if isinstance(value, BrowserSessionHandle):
        return value
    if isinstance(value, Mapping):
        return BrowserSessionHandle(**dict(value))
    raise TypeError("handle must be a BrowserSessionHandle or mapping")


class PlaywrightBrowserAdapter:
    """A session-preserving async Playwright adapter.

    This is the sole browser-driver implementation for the new 3O browser
    surface.  Tests and deployments may inject another ``BrowserAdapter``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _PlaywrightRecord] = {}

    def _record(self, value: BrowserSessionHandle | Mapping[str, Any]) -> _PlaywrightRecord:
        handle = _as_handle(value)
        record = self._sessions.get(handle.session_id)
        if record is None:
            raise RuntimeError("unknown browser session handle")
        return record

    @staticmethod
    def _result(record: _PlaywrightRecord, operation: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "operation": operation,
            "browser": record.handle.to_dict(),
            "handle": record.handle.to_dict(),
            "status": record.handle.state,
        }
        payload.update(extra)
        return payload

    @staticmethod
    def _failed(operation: str, exc: Exception) -> dict[str, Any]:
        return {
            "ok": False,
            "operation": operation,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    def create(self, profile: BrowserProfile | Mapping[str, Any]) -> dict[str, Any]:
        selected = _as_profile(profile)
        handle = BrowserSessionHandle(
            session_id=f"browser-{uuid.uuid4().hex}",
            profile_id=selected.id,
            computer_id=selected.computer_id,
        )
        self._sessions[handle.session_id] = _PlaywrightRecord(selected, handle)
        return self._result(self._sessions[handle.session_id], "create")

    async def start(self, handle: BrowserSessionHandle | Mapping[str, Any]) -> dict[str, Any]:
        operation = "start"
        try:
            record = self._record(handle)
            if record.handle.state in {"running", "attached"}:
                return self._result(record, operation)
            from playwright.async_api import async_playwright

            record.playwright = await async_playwright().start()
            record.browser = await record.playwright.chromium.launch(
                headless=record.profile.headless
            )
            context_kwargs: dict[str, Any] = {
                "viewport": {
                    "width": record.profile.viewport_width,
                    "height": record.profile.viewport_height,
                }
            }
            state_path = record.profile.storage_state_path
            if state_path and Path(state_path).exists():
                context_kwargs["storage_state"] = state_path
            record.context = await record.browser.new_context(**context_kwargs)
            record.page = await record.context.new_page()
            record.handle = replace(record.handle, state="running", attached=False)
            return self._result(record, operation)
        except Exception as exc:
            return self._failed(operation, exc)

    async def status(self, handle: BrowserSessionHandle | Mapping[str, Any]) -> dict[str, Any]:
        operation = "status"
        try:
            record = self._record(handle)
            if record.page is not None:
                record.handle = replace(record.handle, url=str(record.page.url or ""))
            return self._result(record, operation)
        except Exception as exc:
            return self._failed(operation, exc)

    async def attach(self, handle: BrowserSessionHandle | Mapping[str, Any]) -> dict[str, Any]:
        operation = "attach"
        try:
            record = self._record(handle)
            if record.handle.state not in {"running", "attached"}:
                return self._failed(operation, RuntimeError("browser session is not running"))
            record.handle = replace(record.handle, state="attached", attached=True)
            return self._result(record, operation)
        except Exception as exc:
            return self._failed(operation, exc)

    async def stop(self, handle: BrowserSessionHandle | Mapping[str, Any]) -> dict[str, Any]:
        operation = "stop"
        try:
            record = self._record(handle)
            state_path = record.profile.storage_state_path
            if record.context is not None and state_path:
                await record.context.storage_state(path=state_path)
            if record.context is not None:
                await record.context.close()
            if record.browser is not None:
                await record.browser.close()
            if record.playwright is not None:
                await record.playwright.stop()
            record.playwright = None
            record.browser = None
            record.context = None
            record.page = None
            record.handle = replace(record.handle, state="stopped", attached=False)
            return self._result(record, operation)
        except Exception as exc:
            return self._failed(operation, exc)

    async def reset(self, handle: BrowserSessionHandle | Mapping[str, Any]) -> dict[str, Any]:
        operation = "reset"
        try:
            record = self._record(handle)
            if record.handle.state in {"running", "attached"}:
                stopped = await self.stop(record.handle)
                if not stopped.get("ok"):
                    return stopped
            record.handle = replace(record.handle, state="created", attached=False, url="")
            return await self.start(record.handle)
        except Exception as exc:
            return self._failed(operation, exc)

    async def set_control_state(
        self,
        handle: BrowserSessionHandle | Mapping[str, Any],
        state: BrowserControlState,
    ) -> dict[str, Any]:
        operation = "set_control_state"
        try:
            if state not in {"AGENT_CONTROL", "HUMAN_CONTROL"}:
                raise ValueError(f"unsupported browser control state: {state}")
            record = self._record(handle)
            record.handle = replace(record.handle, control_state=state)
            return self._result(record, operation)
        except Exception as exc:
            return self._failed(operation, exc)

    def _page(self, value: BrowserSessionHandle | Mapping[str, Any]) -> _PlaywrightRecord:
        record = self._record(value)
        if record.page is None or record.handle.state not in {"running", "attached"}:
            raise RuntimeError("browser session is not running")
        return record

    def _timeout(self, record: _PlaywrightRecord, kwargs: Mapping[str, Any]) -> int:
        return int(kwargs.get("timeout_ms", record.profile.timeout_ms))

    async def navigate(
        self, handle: BrowserSessionHandle | Mapping[str, Any], url: str, **kwargs: Any
    ) -> dict[str, Any]:
        operation = "navigate"
        try:
            record = self._page(handle)
            await record.page.goto(
                url,
                timeout=self._timeout(record, kwargs),
                wait_until=str(kwargs.get("wait_until", "domcontentloaded")),
            )
            record.handle = replace(record.handle, url=str(record.page.url or url))
            return self._result(
                record,
                operation,
                url=record.handle.url,
                title=await record.page.title(),
            )
        except Exception as exc:
            return self._failed(operation, exc)

    async def snapshot(
        self, handle: BrowserSessionHandle | Mapping[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        operation = "snapshot"
        try:
            record = self._page(handle)
            selector = kwargs.get("selector")
            target = (
                record.page.locator(str(selector)).first
                if selector
                else record.page.locator("body")
            )
            text = await target.inner_text(timeout=self._timeout(record, kwargs))
            html = await target.inner_html(timeout=self._timeout(record, kwargs))
            return self._result(
                record,
                operation,
                url=str(record.page.url or ""),
                title=await record.page.title(),
                text=text,
                html=html,
            )
        except Exception as exc:
            return self._failed(operation, exc)

    async def click(
        self, handle: BrowserSessionHandle | Mapping[str, Any], selector: str, **kwargs: Any
    ) -> dict[str, Any]:
        operation = "click"
        try:
            record = self._page(handle)
            await record.page.locator(selector).first.click(timeout=self._timeout(record, kwargs))
            return self._result(record, operation, selector=selector)
        except Exception as exc:
            return self._failed(operation, exc)

    async def type(
        self,
        handle: BrowserSessionHandle | Mapping[str, Any],
        selector: str,
        text: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        operation = "type"
        try:
            record = self._page(handle)
            await record.page.locator(selector).first.fill(
                text, timeout=self._timeout(record, kwargs)
            )
            return self._result(record, operation, selector=selector)
        except Exception as exc:
            return self._failed(operation, exc)

    async def download(
        self, handle: BrowserSessionHandle | Mapping[str, Any], selector: str, **kwargs: Any
    ) -> dict[str, Any]:
        operation = "download"
        try:
            record = self._page(handle)
            async with record.page.expect_download(timeout=self._timeout(record, kwargs)) as event:
                await record.page.locator(selector).first.click(
                    timeout=self._timeout(record, kwargs)
                )
            download = await event.value
            path = kwargs.get("path")
            if path:
                await download.save_as(str(path))
            return self._result(
                record,
                operation,
                selector=selector,
                path=str(path or await download.path()),
                suggested_filename=download.suggested_filename,
            )
        except Exception as exc:
            return self._failed(operation, exc)

    async def upload(
        self,
        handle: BrowserSessionHandle | Mapping[str, Any],
        selector: str,
        file_paths: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        operation = "upload"
        try:
            record = self._page(handle)
            await record.page.locator(selector).first.set_input_files(
                file_paths, timeout=self._timeout(record, kwargs)
            )
            return self._result(record, operation, selector=selector)
        except Exception as exc:
            return self._failed(operation, exc)

    async def screenshot(
        self, handle: BrowserSessionHandle | Mapping[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        operation = "screenshot"
        try:
            record = self._page(handle)
            selector = kwargs.get("selector")
            target = record.page.locator(str(selector)).first if selector else record.page
            screenshot = await target.screenshot(
                path=str(kwargs["path"]) if kwargs.get("path") else None,
                full_page=bool(kwargs.get("full_page", False)),
            )
            return self._result(
                record,
                operation,
                screenshot_base64=base64.b64encode(cast(bytes, screenshot)).decode("ascii"),
                path=str(kwargs.get("path") or ""),
            )
        except Exception as exc:
            return self._failed(operation, exc)


__all__ = [
    "BrowserAdapter",
    "BrowserControlState",
    "BrowserProfile",
    "BrowserSessionHandle",
    "BrowserSessionState",
    "PlaywrightBrowserAdapter",
]
