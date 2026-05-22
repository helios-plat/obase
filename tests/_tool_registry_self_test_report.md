# obase.tool_registry Self-Test Report

## 5 Red Lines 自测结果

| Red Line | Target | Actual | Pass? |
|---|---|---|---|
| 1. Test coverage | ≥95% | 99% | ✅ |
| 2. Test count | ≥10 | 31 | ✅ |
| 3. Interface contract | Pydantic + docstring + types + exceptions | implemented | ✅ |
| 4. Static checks | mypy strict + ruff | both clean | ✅ |
| 5. Documentation | CHANGELOG + usage example | done | ✅ |

## 详细命令输出

### Coverage

```
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
obase/tool_registry/__init__.py      57      0   100%
obase/tool_registry/schema.py        73      1    99%   128
---------------------------------------------------------------
TOTAL                               130      1    99%
============================== 31 passed in 0.10s ==============================
```

Line 128 in schema.py is the `raise RuntimeError` inside the `__origin__ is tuple` guard.
In Python 3.14, parameterized `tuple[str, int]` proxies `__name__ = "tuple"` via `GenericAlias`,
so the forbidden-name check fires first. The `__origin__` guard is a defence-in-depth path for
future Python versions where that proxy behaviour may change. Dead branch; no test can reach it
without bypassing type annotations. Accepted as known structural gap at 99%.

### Mypy

```
Success: no issues found in 2 source files
```

### Ruff

```
All checks passed!
```

### Test results

```
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.0.3, pluggy-1.6.0
collected 31 items

tests/test_tool_registry.py::TestToolRegistryBasic::test_register_tool_basic PASSED
tests/test_tool_registry.py::TestToolRegistryBasic::test_register_tool_via_decorator PASSED
tests/test_tool_registry.py::TestToolRegistryBasic::test_register_tool_conflict_raises PASSED
tests/test_tool_registry.py::TestToolRegistryBasic::test_register_tool_with_write_permission PASSED
tests/test_tool_registry.py::TestToolRegistryBasic::test_register_tool_with_secrets PASSED
tests/test_tool_registry.py::TestToolRegistryBasic::test_get_nonexistent_tool_returns_none PASSED
tests/test_tool_registry.py::TestToolRegistryBasic::test_has_nonexistent_tool_returns_false PASSED
tests/test_tool_registry.py::TestToolRegistryListing::test_list_tools_all PASSED
tests/test_tool_registry.py::TestToolRegistryListing::test_list_tools_filter_by_permission PASSED
tests/test_tool_registry.py::TestToolRegistryListing::test_list_tools_filter_by_stability PASSED
tests/test_tool_registry.py::TestToolRegistryClearAndMeta::test_clear_removes_all_tools PASSED
tests/test_tool_registry.py::TestToolRegistryClearAndMeta::test_description_extracted_from_docstring PASSED
tests/test_tool_registry.py::TestToolRegistryClearAndMeta::test_full_name_from_oprim_module PASSED
tests/test_tool_registry.py::TestToolRegistryClearAndMeta::test_full_name_from_oskill_module PASSED
tests/test_tool_registry.py::TestToolRegistryClearAndMeta::test_register_no_docstring_empty_description PASSED
tests/test_tool_registry_schema.py::TestBuildArgsModel::test_build_args_model_basic PASSED
tests/test_tool_registry_schema.py::TestBuildArgsModel::test_build_args_model_missing_annotation_raises PASSED
tests/test_tool_registry_schema.py::TestBuildArgsModel::test_build_args_model_positional_param_raises PASSED
tests/test_tool_registry_schema.py::TestBuildArgsModel::test_build_args_model_forbidden_path_raises PASSED
tests/test_tool_registry_schema.py::TestBuildArgsModel::test_build_args_model_forbidden_datetime_raises PASSED
tests/test_tool_registry_schema.py::TestBuildArgsModel::test_build_args_model_forbidden_tuple_raises PASSED
tests/test_tool_registry_schema.py::TestBuildArgsModel::test_build_args_model_forbidden_bytes_raises PASSED
tests/test_tool_registry_schema.py::TestDocstringParsing::test_parse_docstring_args PASSED
tests/test_tool_registry_schema.py::TestDocstringParsing::test_parse_docstring_no_args_section PASSED
tests/test_tool_registry_schema.py::TestDocstringParsing::test_parse_docstring_multiline_arg PASSED
tests/test_tool_registry_schema.py::TestSchemaGeneration::test_to_openai_tool_format PASSED
tests/test_tool_registry_schema.py::TestSchemaGeneration::test_to_anthropic_tool_format PASSED
tests/test_tool_registry_schema.py::TestSchemaGeneration::test_to_openai_tool_name_too_long_raises PASSED
tests/test_tool_registry_schema.py::TestSchemaGeneration::test_to_anthropic_tool_name_too_long_raises PASSED
tests/test_tool_registry_schema.py::TestSchemaGeneration::test_tool_name_dot_to_underscore PASSED
tests/test_tool_registry_schema.py::TestSchemaGeneration::test_anthropic_name_dot_to_underscore PASSED

============================== 31 passed in 0.05s ==============================
```

## Known issues / decisions

1. **ToolRegistryConflict module-level definition**: The spec framework defined `OBaseRegistryConflict`
   inline inside the `register()` method body (creating a class inside a function). This is invalid under
   mypy strict and is an anti-pattern. Moved to module-level `ToolRegistryConflict(OBaseError)`.
   This is a spec-bug fix, not a design change.

2. **`_parse_docstring_args` indent detection bug**: The spec code used `stripped.startswith(" ")`
   after `stripped = line.strip()`, which is always False. Fixed to track `arg_indent` from the
   original line's indentation level. Correct result verified by `test_parse_docstring_args` and
   `test_parse_docstring_multiline_arg`.

3. **Test module name**: pytest loads tests as `test_tool_registry` (not `tests.test_tool_registry`)
   because `tests/` is not a package (no `__init__.py`). Test assertions use `fn._aegis_tool_meta.name`
   rather than hardcoded module paths for robustness.

4. **`__origin__ is tuple` dead branch (schema.py:128)**: In Python 3.14, `tuple[str, int]`
   (a `types.GenericAlias`) proxies `__name__ = "tuple"` to `__origin__`, so the name check fires
   first and the `__origin__` guard is unreachable. 99% coverage is acceptable; the guard is retained
   as defence-in-depth for hypothetical future Python behaviour.

5. **`OBaseRegistryConflict` in provider_registry.py**: The existing `provider_registry.py` defines
   `OBaseRegistryConflict(Exception)` (not `OBaseError`). The `tool_registry` uses
   `ToolRegistryConflict(OBaseError)` per spec requirement "用 obase.OBaseError 体系". This is
   consistent with the direction noted in CHANGELOG v0.1.0 Known Issues.
