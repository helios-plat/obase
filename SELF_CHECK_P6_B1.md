# SELF_CHECK_P6_B1.md — obase.template 子模块

## 概要

P6-B1 第一个元素: `obase.template` — YAML prompt template loading, validation, rendering.

## 文件清单

| 文件 | 说明 |
|------|------|
| `obase/template/__init__.py` | 公开 API re-export |
| `obase/template/_impl.py` | Template model + load/validate/render_prompt |
| `tests/test_template.py` | 15 tests |
| `examples/template_usage.py` | 使用示例 |
| `CHANGELOG.md` | [Unreleased] 新增条目 |

## 公开 API

```python
from obase.template import load, validate, render_prompt, Template, TemplateError, TemplateValidationError

load(path: Path) -> Template
validate(template: Template) -> None
render_prompt(template: Template, vars: dict[str, str]) -> str
```

## 5 红线验收

| 红线 | 结果 |
|------|------|
| 覆盖率 ≥95% | ✅ **100%** (52/52 stmts) |
| 测试 ≥7 | ✅ **15 tests** passed |
| Pydantic + docstring + Raises | ✅ Template BaseModel, 全函数 docstring + Raises |
| mypy --strict + ruff 0 | ✅ mypy: Success, no issues. ruff: All checks passed |
| CHANGELOG + Example | ✅ CHANGELOG [Unreleased] + examples/template_usage.py |

## 测试结果

```
15 passed in 0.10s
Coverage: 100% (obase/template/)
```

## 测试覆盖点

1. 正常加载 YAML
2. 必填字段缺失 → TemplateValidationError
3. Placeholder render 成功
4. 缺少 vars → TemplateError
5. Version semver 校验（拒绝 / 接受）
6. 大文件加载（~40KB）
7. Round-trip（load → dump → reload）
8. Name 含空格拒绝
9. 文件不存在 → TemplateError
10. validate() 正常通过
11. 无 placeholder render
12. 无效 YAML 语法
13. YAML 非 mapping
14. validate() 捕获无效 template
