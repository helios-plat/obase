"""D2 gates: unified harness execution contract (single ABI).

Covers: identity separation, canonical statuses, error taxonomy,
structured activities, terminal-observation authority, capability
projection onto D1 ProviderSpec, and same-ABI normalization across the
Codex/Claude/OpenCode adapters. Live runs reuse the real opencode CLI;
failure/timeout/unavailable paths use deterministic local doubles.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from obase.harness_adapter import (
    RESULT_STATUSES,
    TERMINAL_STATUSES,
    ActivityKind,
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    HarnessActivity,
    HarnessCapabilities,
    HarnessErrorKind,
    HarnessRunRequest,
    HarnessRunResult,
    OpenCodeHarnessAdapter,
    apply_cleanup_outcome,
    classify_process_error,
    normalize_status,
)
from obase.provider_routing import LIFECYCLE_OPS, ProviderSpec


class _SleepAdapter(CodexHarnessAdapter):
    binary = "sleep"
    adapter_name = "sleep-double"

    def build_run_argv(self, prompt: str, **kwargs):
        return [self.binary, "30"]


class _MissingAdapter(CodexHarnessAdapter):
    binary = "definitely-missing-binary-xyz"
    adapter_name = "missing-double"

    def build_run_argv(self, prompt: str, **kwargs):
        return [self.binary]


class _StubAdapter(OpenCodeHarnessAdapter):
    """Deterministic canned result without spawning anything."""

    def __init__(self, result: HarnessRunResult):
        super().__init__()
        self._canned = result

    async def run(self, prompt: str, **kwargs):
        return self._canned


def _canned_completed() -> HarnessRunResult:
    return HarnessRunResult(
        run_id="run-1",
        session_id="sess-1",
        turn_id="turn-1",
        parent_run_id=None,
        status="completed",
        output="hi",
        usage={"tokens": 3},
        terminal_observed=True,
    )


def _opencode_run_available() -> bool:
    binary = shutil.which("opencode")
    if binary is None:
        return False
    try:
        proc = subprocess.run(
            [binary, "run", "reply with exactly: D2_PROBE"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


# -- identity ---------------------------------------------------------------


def test_identity_ids_stay_independent():
    result = _canned_completed()
    assert (result.run_id, result.session_id, result.turn_id) == (
        "run-1",
        "sess-1",
        "turn-1",
    )
    assert result.parent_run_id is None
    wire = result.to_dict()
    assert (wire["run_id"], wire["session_id"], wire["turn_id"]) == (
        "run-1",
        "sess-1",
        "turn-1",
    )


@pytest.mark.asyncio()
async def test_resume_stamps_parent_and_session():
    adapter = OpenCodeHarnessAdapter()
    rejected = await adapter.resume("ghost-run", "hi")
    assert rejected.status == "failed"
    assert rejected.error_kind is HarnessErrorKind.RESUME_REJECTED
    assert rejected.terminal_observed is True
    assert rejected.parent_run_id == "ghost-run"


def test_request_envelope_projects_to_kwargs():
    req = HarnessRunRequest(
        prompt="do it",
        cwd="/tmp",
        session_id="sess-9",
        timeout_s=30.0,
        options={"model": "m"},
    )
    kwargs = req.to_kwargs()
    assert kwargs["cwd"] == "/tmp"
    assert kwargs["timeout_s"] == 30.0
    assert kwargs["session"] == "sess-9"
    assert kwargs["model"] == "m"
    with pytest.raises(ValueError):
        HarnessRunRequest(prompt="")


# -- statuses ---------------------------------------------------------------


def test_canonical_status_set():
    assert set(RESULT_STATUSES) == {
        "completed",
        "failed",
        "cancelled",
        "timeout",
        "partial",
    }
    assert set(TERMINAL_STATUSES) == set(RESULT_STATUSES)


def test_normalize_status_table():
    assert normalize_status("ok") == "completed"
    assert normalize_status("completed") == "completed"
    assert normalize_status("error") == "failed"
    assert normalize_status("canceled") == "cancelled"
    assert normalize_status("timed_out") == "timeout"
    assert normalize_status("partial") == "partial"
    assert normalize_status("grpc-unknown") == "failed"
    assert normalize_status("") == "failed"
    assert normalize_status(None) == "failed"
    # Never silently succeeds.
    assert normalize_status("whatever", default="partial") == "partial"


def test_result_preserves_native_and_usage():
    result = HarnessRunResult(
        run_id="r",
        status="failed",
        output="out",
        usage={"tokens": 7},
        error="boom",
        native_metadata={"binary": "codex", "returncode": 1},
    )
    assert result.usage == {"tokens": 7}
    assert result.native_metadata["returncode"] == 1
    assert result.error == "boom"


def test_terminal_false_success_is_zero():
    # Harness-terminal "completed" with empty output stays completed, and
    # the ABI carries no goal-acceptance claim whatsoever.
    result = HarnessRunResult(run_id="r", status="completed", output="")
    assert result.status == "completed"
    assert not hasattr(result, "goal_accepted")
    assert "goal" not in result.to_dict()


# -- error taxonomy ---------------------------------------------------------


def test_error_taxonomy_values():
    assert {m.value for m in HarnessErrorKind} == {
        "configuration",
        "unavailable",
        "authentication",
        "rate_limited",
        "protocol",
        "process",
        "timeout",
        "cancelled",
        "resume_rejected",
        "execution",
    }
    assert HarnessErrorKind.coerce(None) is None
    assert HarnessErrorKind.coerce("timeout") is HarnessErrorKind.TIMEOUT
    with pytest.raises(ValueError):
        HarnessErrorKind.coerce("nope")


def test_classify_process_error_needs_evidence():
    assert (
        classify_process_error("Error: OAuth token expired", 1) is HarnessErrorKind.AUTHENTICATION
    )
    assert (
        classify_process_error("429 too many requests, slow down", 1)
        is HarnessErrorKind.RATE_LIMITED
    )
    assert classify_process_error("usage limit reached", 1) is HarnessErrorKind.RATE_LIMITED
    assert classify_process_error("segfault", 139) is HarnessErrorKind.PROCESS
    # Raw text is preserved by callers; classification never consumes it.
    assert classify_process_error("", 0) is HarnessErrorKind.PROCESS


@pytest.mark.asyncio()
async def test_missing_binary_is_unavailable_failed():
    result = await _MissingAdapter().run("hi")
    assert result.status == "failed"
    assert result.error_kind is HarnessErrorKind.UNAVAILABLE
    assert result.terminal_observed is True
    assert result.error


@pytest.mark.asyncio()
async def test_spawn_timeout_is_timeout_not_cancelled():
    result = await _SleepAdapter(timeout_s=1).run("hi")
    assert result.status == "timeout"
    assert result.error_kind is HarnessErrorKind.TIMEOUT
    assert result.terminal_observed is True


# -- activities -------------------------------------------------------------


def test_activity_contract_and_validation():
    act = HarnessActivity(
        kind="tool_call",
        sequence=2,
        run_id="run-1",
        session_id="sess-1",
        tool_name="read",
        tool_arguments={"path": "a.txt"},
        tool_status="ok",
        tool_result_ref="res-1",
    )
    assert act.kind is ActivityKind.TOOL_CALL
    wire = act.to_dict()
    assert wire["tool_name"] == "read"
    assert wire["tool_arguments"] == {"path": "a.txt"}
    assert wire["tool_status"] == "ok"
    assert wire["tool_result_ref"] == "res-1"
    assert set(ActivityKind) == {
        ActivityKind.MESSAGE,
        ActivityKind.TOOL_CALL,
        ActivityKind.TOOL_RESULT,
        ActivityKind.TERMINAL,
        ActivityKind.STATUS,
    }
    with pytest.raises(ValueError):
        HarnessActivity(kind="teleport", sequence=0, run_id="r")
    with pytest.raises(ValueError):
        HarnessActivity(kind="message", sequence=-1, run_id="r")


@pytest.mark.asyncio()
async def test_stream_activities_ordered_no_fabrication():
    adapter = _StubAdapter(_canned_completed())
    assert adapter.capabilities.supports_activity("message") is True
    assert adapter.capabilities.supports_activity("tool_call") is False
    events = [event async for event in adapter.stream_activities("hi")]
    kinds = [event.kind for event in events]
    assert kinds == [ActivityKind.MESSAGE, ActivityKind.STATUS, ActivityKind.TERMINAL]
    assert [event.sequence for event in events] == [0, 1, 2]
    assert all(event.run_id == "run-1" for event in events)
    assert all(event.session_id == "sess-1" for event in events)
    assert events[0].payload == {"text": "hi"}
    assert events[2].payload["terminal_observed"] is True


# -- terminal authority -----------------------------------------------------


def test_cleanup_after_terminal_never_rejudges():
    terminal = _canned_completed()
    kept = apply_cleanup_outcome(terminal, "pipe teardown timed out")
    assert kept.status == "completed"
    assert kept.output == "hi"
    assert kept.error is None
    assert kept.native_metadata["cleanup_error_ignored"] == "pipe teardown timed out"
    assert apply_cleanup_outcome(terminal, None) is terminal


def test_cleanup_without_terminal_fails_closed():
    open_run = HarnessRunResult(run_id="r", status="completed", output="x")
    open_run.terminal_observed = False
    judged = apply_cleanup_outcome(open_run, "wait timed out")
    assert judged.status == "failed"
    assert judged.error == "wait timed out"


# -- capabilities -----------------------------------------------------------


def test_capability_projection_onto_d1():
    for cls in (CodexHarnessAdapter, ClaudeCodeHarnessAdapter, OpenCodeHarnessAdapter):
        caps = cls().capabilities
        assert isinstance(caps, HarnessCapabilities)
        matrix = caps.lifecycle_matrix()
        assert set(matrix) == set(LIFECYCLE_OPS)
        assert matrix["run"] is True
        assert matrix["resume"] is caps.resume
        assert matrix["cancel"] is caps.cancel
        assert matrix["stream"] is caps.streaming
        # Honest unsupported declarations: no fake tool activity anywhere.
        assert caps.tool_activity is False
        assert caps.turn_identity is False
        spec = ProviderSpec(
            name=cls().name,
            protocol_family=cls.protocol_family,
            lifecycle=matrix,
        )
        assert spec.can("resume") is caps.resume
        assert spec.can("stream") is caps.streaming


def test_no_duplicate_generic_capability_authority():
    import pathlib

    src = pathlib.Path(__file__).parent.parent.joinpath("obase/harness_adapter.py").read_text()
    assert "_specs" not in src
    assert "register_spec" not in src
    caps = OpenCodeHarnessAdapter().capabilities
    assert not hasattr(caps, "register_spec")


# -- same ABI across adapters -----------------------------------------------


@pytest.mark.asyncio()
async def test_all_adapters_share_one_result_abi():
    results = []
    for cls in (CodexHarnessAdapter, ClaudeCodeHarnessAdapter, OpenCodeHarnessAdapter):
        results.append(await cls().resume("ghost-run", "hi"))
    keys = None
    for result in results:
        assert type(result) is HarnessRunResult
        assert result.status == "failed"
        assert result.error_kind is HarnessErrorKind.RESUME_REJECTED
        assert result.terminal_observed is True
        wire = result.to_dict()
        assert set(wire) == {
            "run_id",
            "session_id",
            "turn_id",
            "parent_run_id",
            "status",
            "output",
            "usage",
            "error",
            "error_kind",
            "terminal_observed",
            "activities",
            "native_metadata",
        }
        keys = keys or set(wire)
        assert set(wire) == keys


@pytest.mark.asyncio()
async def test_live_terminal_observation_end_to_end():
    if shutil.which("opencode") is None:
        pytest.skip("opencode binary is not installed")
    if not _opencode_run_available():
        pytest.skip("opencode run is unavailable in this environment")
    adapter = OpenCodeHarnessAdapter(timeout_s=90)
    run = await adapter.run("reply with exactly: D2_TERMINAL_OK")
    assert run.status == "completed"
    assert "D2_TERMINAL_OK" in run.output
    assert run.terminal_observed is True
    assert run.session_id
    assert run.is_terminal is True
    assert run.activities and run.activities[0].kind is ActivityKind.TERMINAL
    assert run.activities[0].run_id == run.run_id
    assert run.activities[0].session_id == run.session_id
