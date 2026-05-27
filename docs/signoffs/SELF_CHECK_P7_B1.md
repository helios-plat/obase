# SELF_CHECK P7-B1 — obase.mcp_server FastMCP Facade

**Date**: 2026-05-27  
**Branch**: main  
**Commit**: fdb23b8  

---

## 1. Checklist

| 项 | 状态 |
|---|---|
| `obase/mcp_server/__init__.py` 创建 | ✅ |
| `SkillDef` Pydantic 模型（camelCase alias） | ✅ |
| `MCPServer` Facade（完全封装，无 @property 逃生口） | ✅ |
| `MCPServerError` / `MCPProtocolError` 错误层级 | ✅ |
| `pyproject.toml` 加 `mcp>=1.27` | ✅ |
| `uv run python -c "from mcp.server.fastmcp import FastMCP; ..."` → OK | ✅ |
| 测试 ≥9（硬要求） | ✅ 11 |
| 覆盖率 ≥95% | ✅ 100% |
| mypy --strict 0 errors | ✅ |
| ruff 0 errors | ✅ |
| `examples/mcp_server_demo.py` 跑通 | ✅ |
| `CHANGELOG.md` 更新 | ✅ |
| 边界严格（只改 obase，不碰 hevi / stratum） | ✅ |

---

## 2. 测试数 vs 要求

要求：≥9  
实际：**11 passed**

```
tests/test_mcp_server.py::test_register_skill_normal PASSED
tests/test_mcp_server.py::test_stdio_tools_list_and_call PASSED
tests/test_mcp_server.py::test_streamable_http_transport PASSED
tests/test_mcp_server.py::test_handler_exception_returns_error_response PASSED
tests/test_mcp_server.py::test_handler_bad_input_returns_error_response PASSED
tests/test_mcp_server.py::test_unknown_skill_call_error PASSED
tests/test_mcp_server.py::test_capability_negotiation PASSED
tests/test_mcp_server.py::test_multiple_skills_registered PASSED
tests/test_mcp_server.py::test_snake_camel_serialization PASSED
tests/test_mcp_server.py::test_register_skill_wraps_add_tool_error PASSED
tests/test_mcp_server.py::test_serve_stdio_delegates PASSED

11 passed in 0.70s
```

---

## 3. 覆盖率

```
Name                           Stmts   Miss  Cover   Missing
------------------------------------------------------------
obase/mcp_server/__init__.py      45      0   100%
------------------------------------------------------------
TOTAL                             45      0   100%
```

---

## 4. mypy --strict obase/mcp_server/

```
Success: no issues found in 1 source file
```

---

## 5. ruff check obase/mcp_server/

```
All checks passed!
```

---

## 6. snake/camel 序列化测试输出

```
SkillDef wire format (by_alias=True):
  name: hevi.generate_video
  description: Generate a 3+ min vertical content video from a topic.
  inputSchema: {'type': 'object', 'properties': {'topic': {'type': 'string', ...}, ...}, 'required': ['topic']}
  outputSchema: {'type': 'object', 'properties': {'video_path': {'type': 'string'}, ...}}
```

`input_schema` → `inputSchema` ✅  
`output_schema` → `outputSchema` ✅

---

## 7. Example 运行输出

```
=== obase.mcp_server Demo ===
Server: hevi v5.0.0  |  Skills: 2

SkillDef wire format (by_alias=True):
  ...
  inputSchema: {...}
  outputSchema: {...}

--- In-process stdio smoke test ---
✓ initialize  protocolVersion=2025-11-25
  server=hevi v5.0.0
✓ tools/list  count=2
  • hevi.generate_video: Generate a 3+ min vertical content video from a topic.
  • hevi.list_runs: List recent video generation runs.
✓ tools/call  isError=False
  → type='text' text='{"video_path": "/tmp/hevi/Python_async_60s.mp4", ...}'
✓ tools/call  isError=False
  → type='text' text='{"runs": [{"id": "run_0", ...}, ...]}'

Demo complete — all in-process checks passed.
```

---

## 8. 关键设计决策备注

| 决策 | 理由 |
|---|---|
| `_DynamicArgModel(ArgModelBase, extra='allow')` | FastMCP 的 `arg_model` 机制要求 Pydantic 模型；`extra='allow'` + 重写 `model_dump_one_level()` 使 raw dict 直通到 handler |
| `version` 注入到 `_mcp_server.version` | FastMCP 1.27 构造函数不接受 `version`，但底层 `Server` 接受 |
| `serve_streamable_http` 随机端口测试 | FastMCP 的 streamable HTTP ASGI app 需要 Uvicorn lifespan 事件初始化 session_manager，ASGI transport 无法模拟 |
| `_DYNAMIC_FUNC_META` 单例 | 无状态，共享安全，减少每次注册的分配 |

---

## 9. 边界确认

- 修改范围：`/home/soffy/projects/platform/obase/` 仅
- 不涉及 hevi / stratum / 其他项目
- 不包含具体业务 Skill（那是 hevi/mcp/skills/ 后续 Batch）
