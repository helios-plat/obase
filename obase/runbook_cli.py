"""obase.runbook_cli — dev CLI for inspecting/driving Runbook-based runs.

3O layer: obase (I/O and resources).
Usage::

    python -m obase.runbook_cli --runbook path.yaml --run-id r1 start
    python -m obase.runbook_cli --runbook path.yaml --run-id r1 cur
    python -m obase.runbook_cli --runbook path.yaml --run-id r1 history --tail 20
    python -m obase.runbook_cli --runbook path.yaml --run-id r1 goto done \\
        --confirm-item "Task brief understood" --confirm-check ab12cd34

A thin composition over obase.orchestrator's runbook_* functions, the YAML
loader, and the default check_runner/hook_runner — not a new execution engine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from obase.exceptions import StageContractViolation
from obase.orchestrator import runbook_current, runbook_goto, runbook_history, start_runbook
from obase.runbook_loader import RunbookParseError, load_runbook_yaml
from obase.runbook_runtime import default_hook_runner, make_default_check_runner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="3o run", description="Inspect/drive a Runbook-based run."
    )
    parser.add_argument("--runbook", required=True, help="Path to the Runbook YAML file")
    parser.add_argument("--run-id", required=True, help="Run id (directory under FS.run_dir)")
    parser.add_argument(
        "--workspace-root", default=".", help="Root for 'command' checks (default: cwd)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="Start (or resume) the run at its initial node")
    sub.add_parser("cur", help="Show the node the run is currently sitting in")

    p_hist = sub.add_parser("history", help="Show the run's transition history")
    p_hist.add_argument("--tail", type=int, default=50)

    p_goto = sub.add_parser("goto", help="Attempt to transition to a target node")
    p_goto.add_argument("target")
    p_goto.add_argument(
        "--confirm-item",
        action="append",
        default=[],
        help="Mark a checklist item confirmed (repeatable)",
    )
    p_goto.add_argument(
        "--confirm-check",
        action="append",
        default=[],
        help="Mark a manual check id confirmed (repeatable)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        runbook = load_runbook_yaml(args.runbook)
    except RunbookParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "start":
            state = start_runbook(runbook, run_id=args.run_id)
            print(
                json.dumps(
                    {
                        "run_id": state.run_id,
                        "current_node": state.current_node,
                        "state": state.state,
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "cur":
            print(json.dumps(runbook_current(runbook, args.run_id), indent=2))
            return 0

        if args.command == "history":
            print(json.dumps(runbook_history(args.run_id, tail=args.tail), indent=2))
            return 0

        if args.command == "goto":
            agent_context: dict[str, Any] = {
                "checklist_confirmed": args.confirm_item,
                "confirmed_check_ids": args.confirm_check,
            }
            check_runner = make_default_check_runner(workspace_root=Path(args.workspace_root))
            result = runbook_goto(
                runbook,
                args.run_id,
                args.target,
                check_runner=check_runner,
                hook_runner=default_hook_runner,
                agent_context=agent_context,
            )
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1
    except FileNotFoundError:
        print(f"error: no run {args.run_id!r} found — run 'start' first", file=sys.stderr)
        return 2
    except StageContractViolation as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
