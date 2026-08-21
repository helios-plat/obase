from __future__ import annotations

import pytest

from obase.exceptions import OBaseError
from obase.orchestrator import Check, CheckType, Edge, Node, Runbook, runbook_goto, start_runbook
from obase.runbook_runtime import (
    HookNotFoundError,
    HookRegistry,
    default_hook_runner,
    make_default_check_runner,
    register_hook,
)


@pytest.fixture(autouse=True)
def clean_hook_registry():
    HookRegistry.clear()
    yield
    HookRegistry.clear()


class TestChecklistCheck:
    def test_passes_when_all_items_confirmed(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.CHECKLIST, payload={"items": ["a", "b"]})
        result = runner(check, {"agent": {"checklist_confirmed": ["a", "b", "c"]}})
        assert result["passed"] is True

    def test_fails_and_lists_missing_items(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.CHECKLIST, payload={"items": ["a", "b"]})
        result = runner(check, {"agent": {"checklist_confirmed": ["a"]}})
        assert result["passed"] is False
        assert "b" in result["message"]


class TestManualCheck:
    def test_fails_without_confirmation(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.MANUAL, payload={})
        result = runner(check, {"agent": {}})
        assert result["passed"] is False

    def test_passes_when_check_id_confirmed(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.MANUAL, payload={})
        result = runner(check, {"agent": {"confirmed_check_ids": [check.id]}})
        assert result["passed"] is True


class TestPredicateCheck:
    def test_true_expression_passes(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.PREDICATE, payload={"expr": "1 + 1 == 2"})
        result = runner(check, {"agent": {}})
        assert result["passed"] is True

    def test_false_expression_fails(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.PREDICATE, payload={"expr": "1 == 2"})
        result = runner(check, {"agent": {}})
        assert result["passed"] is False

    def test_malformed_expression_fails_not_raises(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.PREDICATE, payload={"expr": "this is not python("})
        result = runner(check, {"agent": {}})
        assert result["passed"] is False
        assert "predicate error" in result["message"]

    def test_restricted_namespace_blocks_builtins(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.PREDICATE, payload={"expr": "open('/etc/passwd')"})
        result = runner(check, {"agent": {}})
        assert result["passed"] is False


class TestCommandCheck:
    def test_exit_zero_passes(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.COMMAND, payload={"run": "true"})
        result = runner(check, {"agent": {}})
        assert result["passed"] is True

    def test_exit_nonzero_fails(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.COMMAND, payload={"run": "false"})
        result = runner(check, {"agent": {}})
        assert result["passed"] is False

    def test_stdout_captured_in_message(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.COMMAND, payload={"run": "echo hello-check"})
        result = runner(check, {"agent": {}})
        assert result["passed"] is True
        assert "hello-check" in result["message"]


class TestLlmReviewCheck:
    def test_raises_without_judge_configured(self, tmp_path):
        runner = make_default_check_runner(workspace_root=tmp_path)
        check = Check(type=CheckType.LLM_REVIEW, payload={"prompt": "review this"})
        with pytest.raises(OBaseError):
            runner(check, {"agent": {}})

    def test_delegates_to_injected_judge(self, tmp_path):
        calls = []

        def judge(check: Check, ctx: dict) -> dict:
            calls.append((check.id, ctx))
            return {"passed": True, "message": "looks good"}

        runner = make_default_check_runner(workspace_root=tmp_path, llm_judge=judge)
        check = Check(type=CheckType.LLM_REVIEW, payload={"prompt": "review this"})
        result = runner(check, {"agent": {}})
        assert result["passed"] is True
        assert len(calls) == 1


class TestHookRunner:
    def test_unregistered_hook_raises(self):
        with pytest.raises(HookNotFoundError):
            default_hook_runner("nope", {})

    def test_registered_hook_is_invoked_with_ctx(self):
        seen = []

        @register_hook("on_enter_plan")
        def _hook(ctx: dict) -> str:
            seen.append(ctx)
            return "ok"

        result = default_hook_runner("on_enter_plan", {"run_id": "x"})
        assert result == "ok"
        assert seen == [{"run_id": "x"}]


class TestRunbookGotoWithDefaultRuntime:
    def test_full_transition_wired_to_default_check_and_hook_runner(self, tmp_path):
        entered = []

        @register_hook("mark_entered")
        def _mark(ctx: dict) -> None:
            entered.append(ctx["node"])

        rb = Runbook(
            name="wired",
            initial="start",
            nodes={
                "start": Node(
                    id="start",
                    prompt="begin",
                    before_transfer=[Check(type=CheckType.PREDICATE, payload={"expr": "1 == 1"})],
                ),
                "done": Node(id="done", prompt="finished", in_hook="mark_entered"),
            },
            edges=[Edge(from_node="start", to_node="done")],
        )
        start_runbook(rb, run_id="wired-1")
        check_runner = make_default_check_runner(workspace_root=tmp_path)
        result = runbook_goto(
            rb,
            "wired-1",
            "done",
            check_runner=check_runner,
            hook_runner=default_hook_runner,
        )
        assert result["ok"] is True
        assert entered == ["done"]
