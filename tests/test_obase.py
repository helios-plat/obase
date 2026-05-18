"""Tests for Stratum-native obase modules.

Covers: errors, logging, config, cost_tracker (module-level functions).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestErrors:
    def test_stratum_error_is_exception(self):
        from obase.errors import StratumError
        assert issubclass(StratumError, Exception)
        e = StratumError("base error")
        assert str(e) == "base error"

    def test_all_subclasses_inherit_stratum_error(self):
        from obase.errors import (
            ConfigError, DuplicateSubstrateError, EmbeddingError,
            FulltextError, IngestError, LLMError, LLMRateLimitError,
            MetaDBError, PDFParseError, QuotaExceededError, StratumError,
            UnsupportedFileTypeError, UnsupportedImageError, VectorDBError,
        )
        classes = [
            ConfigError, PDFParseError, UnsupportedFileTypeError,
            UnsupportedImageError, EmbeddingError, QuotaExceededError,
            VectorDBError, FulltextError, MetaDBError, LLMError,
            LLMRateLimitError, IngestError, DuplicateSubstrateError,
        ]
        for cls in classes:
            assert issubclass(cls, StratumError), f"{cls} should inherit StratumError"

    def test_llm_rate_limit_inherits_llm_error(self):
        from obase.errors import LLMError, LLMRateLimitError
        assert issubclass(LLMRateLimitError, LLMError)

    def test_exceptions_raise_and_catch(self):
        from obase.errors import PDFParseError, StratumError
        with pytest.raises(PDFParseError):
            raise PDFParseError("test")
        with pytest.raises(StratumError):
            raise PDFParseError("catches as base")

    def test_exception_message(self):
        from obase.errors import VectorDBError
        e = VectorDBError("vector db is broken")
        assert "vector db is broken" in str(e)


class TestLogging:
    def test_setup_logging_idempotent(self):
        from obase import logging as olog
        olog.setup_logging("DEBUG")
        olog.setup_logging("INFO")

    def test_emit_does_not_crash(self):
        from obase import logging as olog
        olog.emit("test_event", key="value", num=42)

    def test_error_does_not_crash(self):
        from obase import logging as olog
        olog.error("something broke", context="test")

    def test_warning_does_not_crash(self):
        from obase import logging as olog
        olog.warning("be careful", step=1)

    def test_info_does_not_crash(self):
        from obase import logging as olog
        olog.info("all good", status="ok")

    def test_payload_contains_event_and_ts(self):
        import json
        from obase import logging as olog
        payload = olog._payload("my_event", x=1)
        data = json.loads(payload)
        assert data["event"] == "my_event"
        assert "ts" in data
        assert data["x"] == 1


class TestConfig:
    def test_get_returns_default_when_absent(self):
        from obase import config as cfg
        cfg.load_config(Path("/nonexistent/path/config.yaml"))
        result = cfg.get("TOTALLY_MISSING_KEY_XYZ", "fallback_value")
        assert result == "fallback_value"

    def test_get_returns_none_by_default(self):
        from obase import config as cfg
        cfg.load_config(Path("/nonexistent/path/config.yaml"))
        result = cfg.get("ANOTHER_MISSING_KEY_ABC")
        assert result is None

    def test_env_var_override(self, monkeypatch):
        from obase import config as cfg
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-123")
        cfg.load_config(Path("/nonexistent/path/config.yaml"))
        assert cfg.get("DASHSCOPE_API_KEY") == "test-key-123"

    def test_stratum_prefix_env_override(self, monkeypatch):
        from obase import config as cfg
        monkeypatch.setenv("STRATUM_FOO", "bar")
        cfg.load_config(Path("/nonexistent/path/config.yaml"))
        assert cfg.get("STRATUM_FOO") == "bar"

    def test_load_config_from_yaml(self, tmp_path):
        from obase import config as cfg
        config_file = tmp_path / "config.yaml"
        config_file.write_text("MY_SETTING: hello\nNUM: 42\n")
        loaded = cfg.load_config(config_file)
        assert loaded["MY_SETTING"] == "hello"
        assert cfg.get("MY_SETTING") == "hello"

    def test_env_var_fallback_when_not_in_cfg(self, monkeypatch):
        from obase import config as cfg
        monkeypatch.setenv("SOME_DIRECT_ENV", "direct_value")
        cfg.load_config(Path("/nonexistent/path/config.yaml"))
        assert cfg.get("SOME_DIRECT_ENV") == "direct_value"


class TestCostTracker:
    def setup_method(self):
        from obase.cost_tracker import reset
        reset()

    def teardown_method(self):
        from obase.cost_tracker import reset
        reset()

    def test_track_accumulates(self):
        from obase.cost_tracker import get_records, total_cost, track
        track("dashscope", "text-embedding-v3", 1000, 0, 0.001)
        track("claude", "claude-sonnet-4-6", 500, 200, 0.005)
        records = get_records()
        assert len(records) == 2
        assert abs(total_cost() - 0.006) < 1e-9

    def test_total_cost_sums_correctly(self):
        from obase.cost_tracker import total_cost, track
        track("p", "m", 100, 50, 0.01)
        track("p", "m", 200, 100, 0.02)
        assert abs(total_cost() - 0.03) < 1e-9

    def test_reset_clears_records(self):
        from obase.cost_tracker import get_records, reset, total_cost, track
        track("p", "m", 100, 0, 0.01)
        reset()
        assert get_records() == []
        assert total_cost() == 0.0

    def test_record_fields(self):
        from obase.cost_tracker import get_records, track
        track("provider_x", "model_y", 300, 150, 0.007)
        rec = get_records()[0]
        assert rec.provider == "provider_x"
        assert rec.model == "model_y"
        assert rec.input_tokens == 300
        assert rec.output_tokens == 150
        assert abs(rec.cost_usd - 0.007) < 1e-9

    def test_zero_cost_record(self):
        from obase.cost_tracker import total_cost, track
        track("p", "m", 0, 0, 0.0)
        assert total_cost() == 0.0

    def test_cost_record_dataclass(self):
        from obase.cost_tracker import CostRecord
        rec = CostRecord(provider="p", model="m", input_tokens=10, output_tokens=5, cost_usd=0.001)
        assert rec.provider == "p"
        assert rec.cost_usd == 0.001
