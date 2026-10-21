"""Tests for obase.skills_registry, adaptive_scraper, dlt_pipeline_store."""

from __future__ import annotations

import pytest

from obase.adaptive_scraper import adaptive_scraper
from obase.dlt_pipeline_store import DltPipelineStore
from obase.skills_registry import SkillsRegistry, SkillsRegistryError

# ============================================================================
# SkillsRegistry
# ============================================================================


class TestSkillsRegistry:
    def test_match_python_extension(self):
        reg = SkillsRegistry()
        rules = reg.match_rules("main.py")
        assert any("PEP8" in r for r in rules)

    def test_match_rust_extension(self):
        reg = SkillsRegistry()
        rules = reg.match_rules("lib.rs")
        assert any("Rust" in r for r in rules)

    def test_match_typescript(self):
        reg = SkillsRegistry()
        rules = reg.match_rules("component.tsx")
        assert any("React" in r for r in rules)

    def test_match_solana_keyword(self):
        reg = SkillsRegistry()
        rules = reg.match_rules("solana_program.rs")
        assert any("account ownership" in r.lower() for r in rules)

    def test_match_security_keyword(self):
        reg = SkillsRegistry()
        rules = reg.match_rules("auth_security.py")
        assert any("least privilege" in r.lower() for r in rules)

    def test_match_multiple_rules(self):
        reg = SkillsRegistry()
        rules = reg.match_rules("solana_security.rs")
        # Should match .rs, solana, and security
        assert len(rules) >= 2

    def test_empty_context_returns_empty(self):
        reg = SkillsRegistry()
        assert reg.match_rules("") == []

    def test_register_rule(self):
        reg = SkillsRegistry()
        reg.register_rule(".custom", "Custom rule set for testing.")
        rules = reg.match_rules("file.custom")
        assert any("Custom rule set" in r for r in rules)

    def test_register_empty_key_raises(self):
        reg = SkillsRegistry()
        with pytest.raises(SkillsRegistryError):
            reg.register_rule("", "some rule")

    def test_remove_rule(self):
        reg = SkillsRegistry()
        reg.register_rule(".tmp", "temp")
        assert reg.remove_rule(".tmp") is True
        assert reg.remove_rule(".nonexistent") is False

    def test_list_rules_returns_copy(self):
        reg = SkillsRegistry()
        rules = reg.list_rules()
        assert isinstance(rules, dict)
        assert len(rules) > 0

    def test_health(self):
        reg = SkillsRegistry()
        h = reg.health()
        assert h["status"] == "healthy"
        assert h["rules_count"] > 0


# ============================================================================
# AdaptiveScraper
# ============================================================================


class TestAdaptiveScraper:
    """D0 迁移: obase.adaptive_scraper 唯一实现 = 可调用入口 (Veya L4 resolve_element 依赖)。"""

    def test_element_is_callable_entrypoint(self):
        import obase

        assert callable(obase.adaptive_scraper)

    def test_signature_contract(self):
        import inspect

        params = inspect.signature(adaptive_scraper).parameters
        assert list(params)[:3] == ["url", "selector", "context"]
        assert params["url"].default is inspect.Parameter.empty
        assert params["selector"].default is None
        assert params["context"].default is None


# ============================================================================
# DltPipelineStore
# ============================================================================


class TestDltPipelineStore:
    def test_auto_infer_and_load(self):
        store = DltPipelineStore("test_ds")
        records = [{"name": "Alice", "age": "30"}]
        result = store.auto_infer_and_load("users", records)
        assert result["status"] == "success"
        assert result["rows_inserted"] == 1
        assert list(result["schema"]) == ["name", "age"]

    def test_empty_records(self):
        store = DltPipelineStore()
        result = store.auto_infer_and_load("empty_table", [])
        assert result["status"] == "empty"
        assert result["rows_inserted"] == 0

    def test_schema_inference(self):
        store = DltPipelineStore()
        records = [{"id": 1, "title": "Hello", "body": "World"}]
        store.auto_infer_and_load("posts", records)
        schema = store.get_schema("posts")
        assert "id" in schema
        assert "title" in schema
        assert "body" in schema

    def test_row_count(self):
        store = DltPipelineStore()
        store.auto_infer_and_load("data", [{"a": 1}, {"a": 2}, {"a": 3}])
        assert store.row_count("data") == 3

    def test_get_table(self):
        store = DltPipelineStore()
        records = [{"x": "1"}, {"x": "2"}]
        store.auto_infer_and_load("t", records)
        table = store.get_table("t")
        assert len(table) == 2

    def test_list_tables(self):
        store = DltPipelineStore()
        store.auto_infer_and_load("a", [{"k": "v"}])
        store.auto_infer_and_load("b", [{"k": "v"}])
        tables = store.list_tables()
        assert "a" in tables
        assert "b" in tables

    def test_truncate_table(self):
        store = DltPipelineStore()
        store.auto_infer_and_load("temp", [{"d": 1}, {"d": 2}])
        store.truncate_table("temp")
        assert store.row_count("temp") == 0
        assert store.get_schema("temp") == []

    def test_health(self):
        store = DltPipelineStore("myds")
        store.auto_infer_and_load("items", [{"name": "pen"}])
        h = store.health()
        assert h["status"] == "healthy"
        assert h["dataset_name"] == "myds"
        assert h["table_count"] == 1
