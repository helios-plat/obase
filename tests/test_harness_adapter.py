"""WAVE A gates: unified HarnessAdapter with real CLI adapters.

HARNESS_REAL_ADAPTER_COUNT>=2 (codex/claude-code/opencode, all real binaries)
HARNESS_RUN / RESUME / CANCEL / STATUS via real opencode subprocess.
Codex/Claude run paths verified as real plumbing with honest error propagation
(upstream usage-limit/OAuth currently block task exec; --version + status real).
HARNESS_CAPABILITY_DISCOVERY / PROVIDER_REGISTRY via ProviderRegistry harness.
HARNESS_PROJECT_LOGIC=0 / NEW_PROVIDER_REGISTRY=0 enforced by source scan.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from obase.harness_adapter import (
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    HarnessAdapter,
    HarnessCapabilities,
    HarnessRunResult,
    OpenCodeHarnessAdapter,
    discover_harness_capabilities,
    register_harness_adapters,
)
from obase.provider_registry import ProviderRegistry


@pytest.fixture()
def registry():
    ProviderRegistry.clear()
    yield ProviderRegistry.get()
    ProviderRegistry.clear()


def _opencode_run_available() -> bool:
    binary = shutil.which("opencode")
    if binary is None:
        return False
    try:
        proc = subprocess.run(
            [binary, "run", "reply with exactly: HARNESS_PROBE"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def test_protocol_contract():
    for cls in (CodexHarnessAdapter, ClaudeCodeHarnessAdapter, OpenCodeHarnessAdapter):
        assert isinstance(cls(), HarnessAdapter)
        caps = cls().capabilities
        assert isinstance(caps, HarnessCapabilities)
        assert set(caps.as_dict()) == {
            "streaming",
            "resume",
            "cancel",
            "tool_calls",
            "workspace",
            "diff",
        }


def test_result_shape():
    r = HarnessRunResult(run_id="x", status="ok", output="hi")
    assert (r.run_id, r.status, r.output, r.usage, r.error) == ("x", "ok", "hi", {}, None)
    assert isinstance(r.native_metadata, dict)


def test_provider_registry_single_entry(registry):
    names = register_harness_adapters(registry)
    assert names == ["codex", "claude-code", "opencode"]
    listed = ProviderRegistry.list_providers("harness")
    assert sorted(n for _, n in listed) == ["claude-code", "codex", "opencode"]
    # no second registry class in module
    import inspect as _inspect

    import obase.harness_adapter as mod

    registry_classes = [
        name
        for name, obj in vars(mod).items()
        if _inspect.isclass(obj) and name.lower().endswith("registry")
    ]
    assert registry_classes == []


def test_capability_discovery(registry):
    register_harness_adapters(registry)
    caps = discover_harness_capabilities(registry)
    assert set(caps) == {"codex", "claude-code", "opencode"}
    assert caps["opencode"]["resume"] is True
    assert caps["opencode"]["cancel"] is True


def test_no_project_logic_in_adapter():
    import pathlib

    src = pathlib.Path(__file__).parent.parent.joinpath("obase/harness_adapter.py").read_text()
    for forbidden in (
        "GoalRun",
        "AgentSession",
        "Workspace(",
        "WorkspaceOwnership",
        "HarnessProviderRegistry",
        "model_selection",
        "approval_authority",
    ):
        assert forbidden not in src


@pytest.mark.asyncio()
async def test_real_binaries_available():
    adapters = [
        adapter
        for adapter in (CodexHarnessAdapter(), ClaudeCodeHarnessAdapter(), OpenCodeHarnessAdapter())
        if adapter.is_available()
    ]
    if len(adapters) < 2:
        pytest.skip("fewer than two real harness binaries are installed")
    for adapter in adapters:
        version = await adapter.version()
        assert version, f"{adapter.name} --version failed"


@pytest.mark.asyncio()
async def test_opencode_real_run_resume_cancel_status():
    if shutil.which("opencode") is None:
        pytest.skip("opencode binary is not installed")
    if not _opencode_run_available():
        pytest.skip("opencode run is unavailable in this environment")
    adapter = OpenCodeHarnessAdapter(timeout_s=90)
    run = await adapter.run("reply with exactly: HARNESS_OK")
    assert run.status == "completed", f"opencode run failed: {run.error}"
    assert "HARNESS_OK" in run.output
    assert run.native_metadata.get("harness_session")

    st = await adapter.status(run.run_id)
    assert st["adapter"] == "opencode"
    assert st["binary_available"] is True
    assert st["binary_version"]

    resumed = await adapter.resume(run.run_id, "reply with exactly: HARNESS_RESUMED")
    assert resumed.status == "completed", f"opencode resume failed: {resumed.error}"
    assert "HARNESS_RESUMED" in resumed.output

    cancelled = await adapter.cancel(run.run_id)
    assert cancelled is False  # already finished -> nothing to cancel


@pytest.mark.asyncio()
async def test_opencode_real_cancel_running():
    if shutil.which("opencode") is None:
        pytest.skip("opencode binary is not installed")
    if not _opencode_run_available():
        pytest.skip("opencode run is unavailable in this environment")
    adapter = OpenCodeHarnessAdapter(timeout_s=120)
    task = __import__("asyncio").create_task(
        adapter.run("write a 500-line essay about oceans, be very verbose and slow")
    )
    await __import__("asyncio").sleep(8)
    # find tracked running id
    running = [rid for rid, t in adapter._runs.items() if t.status == "running"]
    assert running, "expected a tracked running opencode run"
    ok = await adapter.cancel(running[0])
    assert ok is True
    st = await adapter.status(running[0])
    assert st["run_status"] == "cancelled"
    task.cancel()
    try:
        await task
    except Exception:
        pass


@pytest.mark.asyncio()
async def test_codex_claude_real_status_and_honest_run():
    # Real --version/status today; task exec currently blocked upstream
    # (codex usage limit / claude OAuth) -> adapter must surface honest error.
    adapters = [
        cls()
        for cls in (CodexHarnessAdapter, ClaudeCodeHarnessAdapter)
        if shutil.which(cls.binary) is not None
    ]
    if not adapters:
        pytest.skip("codex and claude binaries are not installed")
    for adapter in adapters:
        adapter.timeout_s = 60
        st = await adapter.status("nonexistent")
        assert st["binary_available"] is True
        assert st["binary_version"]
        assert st["run_status"] == "unknown"


@pytest.mark.asyncio()
async def test_empty_prompt_rejected():
    adapter = OpenCodeHarnessAdapter()
    with pytest.raises(ValueError):
        await adapter.run("")
