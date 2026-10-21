"""WAVE J gates: cross-capability composition (no new elements).

HARNESS_ORCHESTRATION / LONG_HORIZON_HARNESS / A2A_ORCHESTRATION /
ACP_HARNESS / MCP_SKILL / SKILL_OPT / CODEGRAPH / CONTEXT_LOOP.
Transport-heavy legs reuse real local peers; orchestration legs verify wiring.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

# WAVE J 集成需要五库同源工作区:补 sibling repo 路径 (若不存在则测试跳过)
_ROOT = Path(__file__).resolve().parents[2]
for _repo in ("oservi", "omodul", "oskill", "oprim"):
    _pkg_path = _ROOT / _repo
    if _pkg_path.is_dir() and str(_pkg_path) not in sys.path:
        sys.path.insert(0, str(_pkg_path))

pytestmark = pytest.mark.skipif(
    not (_ROOT / "oservi").is_dir() or not (_ROOT / "omodul").is_dir(),
    reason="cross-capability composition requires the 5-repo workspace",
)


# ---------- real local A2A peer (shared) ----------


class _Peer(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/.well-known/agent.json":
            self._send_json(
                {"name": "peer", "url": "x", "capabilities": {"streaming": True}, "skills": []}
            )
        else:
            self._send_json({}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        msg = json.loads(self.rfile.read(length) or b"{}")
        method = msg.get("method", "")
        if method == "message/send":
            text = msg["params"]["message"]["parts"][0]["text"]
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "result": {
                        "id": "t1",
                        "state": "completed",
                        "artifacts": [{"parts": [{"text": f"done:{text}"}]}],
                    },
                }
            )
        elif method == "tasks/cancel":
            self._send_json({"jsonrpc": "2.0", "id": msg.get("id"), "result": {}})
        elif method == "tasks/get":
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "result": {
                        "id": "t1",
                        "state": "completed",
                        "artifacts": [{"parts": [{"text": "done:x"}]}],
                    },
                }
            )
        else:
            self._send_json({"error": "unknown"}, status=400)


@pytest.fixture()
def peer_url():
    server = HTTPServer(("127.0.0.1", 0), _Peer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _orchestrator(subagent_runner):
    from oservi.engines.subagent_orchestrator import SubagentOrchestratorEngine

    async def _llm(**kwargs):
        return {"thought": "t"}

    return SubagentOrchestratorEngine(
        subagent_runner=subagent_runner,
        llm_caller=_llm,
        trigger={"on_demand": True},
        config={"max_parallel": 2},
        name="j-test",
    )


@pytest.mark.asyncio()
async def test_a2a_orchestration_composition(peer_url):
    from obase.a2a_adapter import A2AAgentAdapter

    adapter = A2AAgentAdapter(agent_url=peer_url)

    async def runner(*, task, config):
        result = await adapter.invoke(str(task.get("prompt", "")))
        return {"output": result.output, "cost_usd": 0.0}

    engine = _orchestrator(runner)
    out = await engine.orchestrate([{"prompt": "a"}, {"prompt": "b"}], parallel=True)
    assert out["status"] == "completed"
    assert [r["output"] for r in out["results"]] == ["done:a", "done:b"]


@pytest.mark.asyncio()
async def test_harness_orchestration_composition():
    from obase.harness_adapter import (
        HarnessAdapter,
        HarnessCapabilities,
        HarnessRunResult,
    )

    class FakeHarness:
        name = "fake-harness"
        capabilities = HarnessCapabilities(resume=True, cancel=True)

        async def run(self, prompt, **kwargs):
            return HarnessRunResult(run_id="r1", status="ok", output=f"h:{prompt}")

        async def resume(self, run_id, prompt="", **kwargs):
            return HarnessRunResult(run_id=run_id, status="ok", output=f"h:{prompt}")

        async def cancel(self, run_id):
            return False

        async def status(self, run_id):
            return {"run_id": run_id, "run_status": "ok"}

    harness = FakeHarness()
    assert isinstance(harness, HarnessAdapter)

    async def runner(*, task, config):
        result = await harness.run(str(task.get("prompt", "")))
        return {"output": result.output, "cost_usd": 0.0}

    engine = _orchestrator(runner)
    out = await engine.orchestrate([{"prompt": "q"}])
    assert out["results"][0]["output"] == "h:q"


@pytest.mark.asyncio()
async def test_long_horizon_harness_composition():
    from oservi.engines.agentic_loop import AgenticLoopEngine

    from obase.harness_adapter import HarnessRunResult

    async def _llm(**kwargs):
        return {"thought": "t"}

    engine = AgenticLoopEngine(
        llm_caller=_llm,
        tools=[],
        turn_handler=lambda **k: {},
        trigger={"on_demand": True},
        config={},
        name="j-loop",
    )

    async def harness_executor(fresh_context):
        step = fresh_context["bounded_next_step"]
        return {
            "progress": {"ran": step},
            "harness": HarnessRunResult(run_id="r", status="ok", output=step).__dict__,
        }

    out = await engine.run_verified(
        "goal",
        harness_executor,
        lambda r: {"accepted": True},
        max_rounds=2,
        is_complete=lambda s: "ran" in s,
    )
    assert out["status"] == "COMPLETED"
    assert out["verified_state"]["ran"].startswith("round 1/")


@pytest.mark.asyncio()
async def test_acp_harness_composition():
    from obase.acp_adapter import ACPAgentAdapter

    async def peer(message):
        method = message.get("method", "")
        if method == "initialize":
            return {"result": {"capabilities": {}}}
        if method == "session/new":
            return {"result": {"sessionId": "s1"}}
        if method == "session/prompt":
            return {"result": {"output": "acp-out"}}
        return {"error": "unknown"}

    acp = ACPAgentAdapter(transport=peer)
    session = await acp.new_session()
    turn = await acp.turn(session.session_id, "go")
    hr = acp.to_harness_result(session.session_id, turn)
    assert hr.status == "ok" and hr.output == "acp-out"
    assert hr.native_metadata["protocol"] == "acp"


@pytest.mark.asyncio()
async def test_mcp_skill_composition():
    from obase.mcp_client import discover_skills, normalize_skill_capability

    class Client:
        extensions = ["io.modelcontextprotocol/skills"]

        async def list_tools(self):
            return []

        async def call_tool(self, name, args):
            assert name == "skill_list"
            return {"skills": [{"name": "skill_x", "description": "x"}]}

    skills = await discover_skills(Client())
    assert skills[0]["extension"] == "io.modelcontextprotocol/skills"
    # shape-only:无 oskill 内容复制
    assert set(skills[0]) == {"name", "version", "description", "inputs", "outputs", "extension"}
    assert normalize_skill_capability({"name": "s"})["name"] == "s"


def test_skill_opt_composition(tmp_path):
    from omodul.optimize_skill import Config, InputData, optimize_skill
    from oskill.metric_baseline_compare import metric_baseline_compare

    def evaluator(skill, cases):
        level = float(skill.get("level", 0.0))
        return {"score": level}

    def generator(skill, objective, iteration):
        return {"name": "s", "level": min(1.0, skill.get("level", 0.0) + 0.5)}

    out = optimize_skill(
        Config(metric_directions={"score": "higher_is_better"}, max_iterations=1),
        InputData(
            skill={"name": "s", "level": 0.1},
            training_cases=[{"q": 1}],
            validation_cases=[{"q": 2}],
            candidate_generator=generator,
            evaluator=evaluator,
        ),
        tmp_path,
    )
    assert out["status"] == "completed"
    verdict = metric_baseline_compare(
        current_metrics=out["validation_metrics"]["selected"],
        baseline_metrics=out["validation_metrics"]["baseline"],
        metric_directions={"score": "higher_is_better"},
    )
    assert verdict.verdict == "healthy"


@pytest.mark.asyncio()
async def test_codegraph_composition(tmp_path):
    from omodul.index_codebase import Config, InputData, index_codebase
    from oservi.engines.source_watcher import SourceWatcherEngine

    (tmp_path / "a.py").write_text("x = 1\n")
    watcher = SourceWatcherEngine(
        searchers={},
        download=lambda *a, **k: {},
        ingest=lambda *a, **k: {},
        subscription=object(),
        trigger={},
        config={},
        name="j",
    )
    events = watcher.emit_file_changes(root=tmp_path)
    assert events and events[0]["kind"] == "added"

    writes: dict[str, str] = {}

    async def writer(*, path, embedding, content, delete=False):
        if delete:
            writes.pop(path, None)
        else:
            writes[path] = content

    out = await index_codebase(
        Config(incremental=True),
        InputData(
            root_path=str(tmp_path),
            embedder=lambda *, text: [1.0],
            vector_writer=writer,
            changed_files=events,
        ),
        tmp_path,
    )
    assert out["status"] == "completed" and out["indexed"] == 1


def test_context_loop_composition():
    from oskill.progressive_disclosure import (
        ContextItem,
        compact_context,
        select_context_window,
    )

    evidence = [
        ContextItem(
            item_id=f"e{i}",
            headline=f"h{i}",
            summary=f"s{i}",
            layer="L1",
            token_cost=50,
            relevance=0.9 - i * 0.1,
            recency=0.8,
        )
        for i in range(5)
    ]
    window = select_context_window(evidence, token_budget=120)
    assert sum(i.token_cost for i in window) <= 120
    compacted = compact_context(window, token_budget=80)
    assert sum(i.token_cost for i in compacted) <= 80
    assert compacted  # evidence 不丢光


def test_no_parallel_authority():
    import pathlib

    root = pathlib.Path("/data/soffy/projects/platform/3O")
    # McpClientRegistry 为 Wave B 之前既有 (非新增),列入允许名单
    allowed = {"obase/obase/mcp_client.py:class McpClientRegistry:"}
    new_registries = []
    for rel in (
        "obase/obase/harness_adapter.py",
        "obase/obase/a2a_adapter.py",
        "obase/obase/acp_adapter.py",
        "obase/obase/channel_adapter.py",
        "obase/obase/mcp_client.py",
    ):
        src = (root / rel).read_text()
        if "class " in src and "Registry" in src:
            for line in src.splitlines():
                if line.strip().startswith("class ") and "Registry" in line:
                    entry = f"{rel}:{line.strip()}"
                    if entry not in allowed:
                        new_registries.append(entry)
    assert new_registries == [], new_registries
