from __future__ import annotations

import json

import pytest

from obase.runbook_cli import main

RUNBOOK_YAML = """
name: cli-test
initial: start
nodes:
  start:
    prompt: begin
    before_transfer:
      - type: checklist
        payload:
          items:
            - brief understood
  done:
    prompt: finished
edges:
  - from: start
    to: done
"""


@pytest.fixture
def runbook_path(tmp_path):
    path = tmp_path / "rb.yaml"
    path.write_text(RUNBOOK_YAML)
    return path


class TestStartAndCur:
    def test_start_creates_run_at_initial_node(self, runbook_path, capsys):
        code = main(["--runbook", str(runbook_path), "--run-id", "cli-1", "start"])
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["current_node"] == "start"
        assert out["state"] == "running"

    def test_cur_reflects_current_node(self, runbook_path, capsys):
        main(["--runbook", str(runbook_path), "--run-id", "cli-2", "start"])
        capsys.readouterr()
        code = main(["--runbook", str(runbook_path), "--run-id", "cli-2", "cur"])
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["node"] == "start"
        assert out["allowed_next"] == ["done"]

    def test_cur_without_start_errors(self, runbook_path, capsys):
        code = main(["--runbook", str(runbook_path), "--run-id", "never-started", "cur"])
        assert code == 2
        assert "no run" in capsys.readouterr().err


class TestGoto:
    def test_goto_fails_without_confirmation(self, runbook_path, capsys):
        main(["--runbook", str(runbook_path), "--run-id", "cli-3", "start"])
        capsys.readouterr()
        code = main(["--runbook", str(runbook_path), "--run-id", "cli-3", "goto", "done"])
        assert code == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False

    def test_goto_succeeds_with_confirm_item(self, runbook_path, capsys):
        main(["--runbook", str(runbook_path), "--run-id", "cli-4", "start"])
        capsys.readouterr()
        code = main(
            [
                "--runbook",
                str(runbook_path),
                "--run-id",
                "cli-4",
                "goto",
                "done",
                "--confirm-item",
                "brief understood",
            ]
        )
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["to"] == "done"


class TestHistory:
    def test_history_reflects_transitions(self, runbook_path, capsys):
        main(["--runbook", str(runbook_path), "--run-id", "cli-5", "start"])
        main(
            [
                "--runbook",
                str(runbook_path),
                "--run-id",
                "cli-5",
                "goto",
                "done",
                "--confirm-item",
                "brief understood",
            ]
        )
        capsys.readouterr()
        code = main(["--runbook", str(runbook_path), "--run-id", "cli-5", "history"])
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert [h["to"] for h in out] == ["done"]


class TestErrors:
    def test_bad_runbook_path_errors(self, tmp_path, capsys):
        code = main(["--runbook", str(tmp_path / "missing.yaml"), "--run-id", "x", "cur"])
        assert code == 2

    def test_malformed_runbook_errors(self, tmp_path, capsys):
        bad = tmp_path / "bad.yaml"
        bad.write_text("nodes: {}\n")  # missing name/initial
        code = main(["--runbook", str(bad), "--run-id", "x", "cur"])
        assert code == 2
        assert "error" in capsys.readouterr().err
