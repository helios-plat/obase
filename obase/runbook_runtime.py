"""obase.runbook_runtime — default check_runner / hook_runner for Runbook-driven runs.

3O layer: obase (I/O and resources).
Pairs with obase.orchestrator's Runbook/Check/runbook_goto: this module supplies
the executable side of a Check (does it actually pass?) and of a hook (what
actually runs when a node/edge fires one).
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import structlog

from obase.exceptions import OBaseError
from obase.orchestrator import Check, CheckType
from obase.sandbox.process_jail import ProcessJail

log = structlog.get_logger()

CheckRunner = Callable[[Check, dict[str, Any]], dict[str, Any]]
HookFn = Callable[[dict[str, Any]], Any]


class HookNotFoundError(OBaseError):
    retryable = False


class HookRegistry:
    """Name → callable registry for Runbook in_hook/out_hook/edge.hook. Process-local."""

    _hooks: ClassVar[dict[str, HookFn]] = {}

    @classmethod
    def register(cls, name: str, fn: HookFn) -> None:
        cls._hooks[name] = fn

    @classmethod
    def get(cls, name: str) -> HookFn:
        fn = cls._hooks.get(name)
        if fn is None:
            raise HookNotFoundError(f"hook not registered: {name!r}")
        return fn

    @classmethod
    def clear(cls) -> None:
        cls._hooks.clear()


def register_hook(name: str) -> Callable[[HookFn], HookFn]:
    """Decorator: ``@register_hook("plan.entered")`` registers fn under that name."""

    def deco(fn: HookFn) -> HookFn:
        HookRegistry.register(name, fn)
        return fn

    return deco


def default_hook_runner(hook_name: str, ctx: dict[str, Any]) -> Any:
    """Look up ``hook_name`` in HookRegistry and invoke it with ``ctx``.

    Raises HookNotFoundError for an unregistered name — a Runbook referencing
    a hook that was never wired up is a configuration bug, not a no-op.
    """
    return HookRegistry.get(hook_name)(ctx)


# ---- predicate check: restricted eval, matches ProcessJail's "OS-level, not a
# full sandbox" trust boundary — Runbook definitions are first-party, not
# untrusted input. Stronger isolation stays on oprim.sandbox_exec.
_PREDICATE_SAFE_LOCALS: dict[str, Any] = {
    "Path": Path,
    "len": len,
    "any": any,
    "all": all,
}


def _check_checklist(check: Check, ctx: dict[str, Any]) -> dict[str, Any]:
    items: list[str] = check.payload.get("items", [])
    confirmed = set(ctx.get("agent", {}).get("checklist_confirmed", []))
    missing = [i for i in items if i not in confirmed]
    if missing:
        return {"passed": False, "message": f"unconfirmed items: {missing}"}
    return {"passed": True, "message": "all items confirmed"}


def _check_manual(check: Check, ctx: dict[str, Any]) -> dict[str, Any]:
    confirmed_ids = set(ctx.get("agent", {}).get("confirmed_check_ids", []))
    if check.id not in confirmed_ids:
        return {"passed": False, "message": "awaiting manual confirmation"}
    return {"passed": True, "message": "manually confirmed"}


def _check_predicate(check: Check, ctx: dict[str, Any]) -> dict[str, Any]:
    expr = check.payload.get("expr", "")
    try:
        result = eval(expr, {"__builtins__": {}}, dict(_PREDICATE_SAFE_LOCALS))  # noqa: S307
    except Exception as exc:
        return {"passed": False, "message": f"predicate error: {exc}"}
    return {"passed": bool(result), "message": f"expr={expr!r} -> {result!r}"}


def _check_command(check: Check, ctx: dict[str, Any], *, jail: ProcessJail) -> dict[str, Any]:
    run = check.payload.get("run", "")
    timeout = check.payload.get("timeout")
    try:
        argv = shlex.split(run)
    except ValueError as exc:
        return {"passed": False, "message": f"cannot parse command: {exc}"}
    if not argv:
        return {"passed": False, "message": "empty command"}
    code, stdout, stderr = jail.run(argv, timeout=int(timeout) if timeout else None)
    tail = (stdout + stderr)[-2000:]
    return {"passed": code == 0, "message": f"exit={code}\n{tail}"}


def _check_llm_review(
    check: Check,
    ctx: dict[str, Any],
    *,
    llm_judge: CheckRunner | None,
) -> dict[str, Any]:
    if llm_judge is None:
        raise OBaseError(
            "check type 'llm_review' requires an llm_judge callable; "
            "pass one to make_default_check_runner(llm_judge=...)"
        )
    return llm_judge(check, ctx)


def make_default_check_runner(
    *,
    workspace_root: Path | str,
    llm_judge: CheckRunner | None = None,
    command_timeout_s: int = 60,
) -> CheckRunner:
    """Build a check_runner covering checklist/command/predicate/manual/llm_review.

    - checklist: passes when every payload["items"] entry is in
      ctx["agent"]["checklist_confirmed"].
    - manual: passes when check.id is in ctx["agent"]["confirmed_check_ids"].
    - predicate: evaluates payload["expr"] in a restricted namespace (Path/len/any/all).
    - command: runs payload["run"] (shlex-split, no shell) in a ProcessJail
      rooted at workspace_root; passes on exit code 0.
    - llm_review: delegates to llm_judge, which must be supplied explicitly —
      there is no default LLM provider baked into obase.
    """
    jail = ProcessJail(workspace_root, timeout_s=command_timeout_s)

    def _run(check: Check, ctx: dict[str, Any]) -> dict[str, Any]:
        if check.type == CheckType.CHECKLIST:
            return _check_checklist(check, ctx)
        if check.type == CheckType.MANUAL:
            return _check_manual(check, ctx)
        if check.type == CheckType.PREDICATE:
            return _check_predicate(check, ctx)
        if check.type == CheckType.COMMAND:
            return _check_command(check, ctx, jail=jail)
        if check.type == CheckType.LLM_REVIEW:
            return _check_llm_review(check, ctx, llm_judge=llm_judge)
        raise OBaseError(f"unknown check type: {check.type!r}")

    return _run
