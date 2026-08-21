from __future__ import annotations

import pytest

from obase.orchestrator import CheckType
from obase.runbook_loader import RunbookParseError, load_runbook_yaml, parse_runbook

CODING_LOOP_YAML = """
name: coding-agent-loop
initial: start
version: "1"

nodes:
  start:
    prompt: |
      Load task brief, progress.md, recent history and project constraints.
    before_transfer:
      - type: checklist
        payload:
          items:
            - Task brief understood
            - Constraints recorded

  plan:
    prompt: |
      Produce a concrete, scoped implementation plan. Update progress.md.
    before_transfer:
      - type: predicate
        payload:
          expr: "Path('progress.md').exists() and Path('progress.md').stat().st_size > 0"

  execute:
    prompt: |
      Implement the plan with minimal scope. Run tests.
    before_transfer:
      - type: command
        payload:
          run: "python -m pytest -q"
      - type: checklist
        payload:
          items:
            - Only intended files changed
            - Tests pass

  review:
    prompt: |
      Review against plan and constraints. Decide handoff or fix.
    before_transfer:
      - type: checklist
        payload:
          items:
            - Deviations justified
            - Risks documented

  handoff:
    prompt: |
      Summarize changes, verification evidence and remaining risks.

edges:
  - from: start
    to: plan
    condition: Context loaded
  - from: plan
    to: execute
    condition: Plan ready
  - from: execute
    to: review
    condition: Implementation complete
  - from: review
    to: execute
    condition: Fixable issues found
  - from: review
    to: handoff
    condition: Acceptable
"""


class TestLoadCodingLoopExample:
    def test_parses_all_nodes_and_edges(self, tmp_path):
        path = tmp_path / "coding-agent-loop.yaml"
        path.write_text(CODING_LOOP_YAML)
        rb = load_runbook_yaml(path)
        assert rb.name == "coding-agent-loop"
        assert rb.initial == "start"
        assert set(rb.nodes) == {"start", "plan", "execute", "review", "handoff"}
        assert len(rb.edges) == 5

    def test_node_checks_parsed_with_correct_types(self, tmp_path):
        path = tmp_path / "rb.yaml"
        path.write_text(CODING_LOOP_YAML)
        rb = load_runbook_yaml(path)
        execute_checks = rb.nodes["execute"].before_transfer
        assert [c.type for c in execute_checks] == [CheckType.COMMAND, CheckType.CHECKLIST]
        assert execute_checks[0].payload["run"] == "python -m pytest -q"

    def test_edge_condition_and_default_max_attempts(self, tmp_path):
        path = tmp_path / "rb.yaml"
        path.write_text(CODING_LOOP_YAML)
        rb = load_runbook_yaml(path)
        review_to_execute = next(
            e for e in rb.edges if e.from_node == "review" and e.to_node == "execute"
        )
        assert review_to_execute.condition == "Fixable issues found"
        assert review_to_execute.max_attempts == 3

    def test_content_hash_is_stable_across_loads(self, tmp_path):
        path = tmp_path / "rb.yaml"
        path.write_text(CODING_LOOP_YAML)
        rb1 = load_runbook_yaml(path)
        rb2 = load_runbook_yaml(path)
        assert rb1.content_hash() == rb2.content_hash()

    def test_check_ids_are_stable_across_loads(self, tmp_path):
        path = tmp_path / "rb.yaml"
        path.write_text(CODING_LOOP_YAML)
        rb1 = load_runbook_yaml(path)
        rb2 = load_runbook_yaml(path)
        ids1 = [c.id for c in rb1.nodes["execute"].before_transfer]
        ids2 = [c.id for c in rb2.nodes["execute"].before_transfer]
        assert ids1 == ids2


class TestParseErrors:
    def test_missing_name_raises(self):
        with pytest.raises(RunbookParseError):
            parse_runbook({"initial": "start", "nodes": {"start": {}}})

    def test_missing_nodes_raises(self):
        with pytest.raises(RunbookParseError):
            parse_runbook({"name": "x", "initial": "start", "nodes": {}})

    def test_initial_not_in_nodes_raises(self):
        with pytest.raises(RunbookParseError):
            parse_runbook({"name": "x", "initial": "missing", "nodes": {"start": {}}})

    def test_missing_file_raises_parse_error_not_file_not_found(self, tmp_path):
        with pytest.raises(RunbookParseError):
            load_runbook_yaml(tmp_path / "nope.yaml")

    def test_edge_unknown_from_node_raises(self):
        with pytest.raises(RunbookParseError):
            parse_runbook(
                {
                    "name": "x",
                    "initial": "start",
                    "nodes": {"start": {}},
                    "edges": [{"from": "ghost", "to": "start"}],
                }
            )

    def test_unknown_check_type_raises(self):
        with pytest.raises(RunbookParseError):
            parse_runbook(
                {
                    "name": "x",
                    "initial": "start",
                    "nodes": {"start": {"before_transfer": [{"type": "telepathy", "payload": {}}]}},
                }
            )

    def test_non_mapping_yaml_raises(self, tmp_path):
        path = tmp_path / "rb.yaml"
        path.write_text("- just\n- a\n- list\n")
        with pytest.raises(RunbookParseError):
            load_runbook_yaml(path)

    def test_invalid_yaml_syntax_raises(self, tmp_path):
        path = tmp_path / "rb.yaml"
        path.write_text("name: [unterminated\n")
        with pytest.raises(RunbookParseError):
            load_runbook_yaml(path)
