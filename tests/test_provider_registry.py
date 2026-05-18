from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from obase.exceptions import ProviderDiscoveryError, ProviderNotFoundError
from obase.provider_registry import OBaseRegistryConflict, ProviderRegistry


def _mock_fn():
    return "result"


class TestProviderRegistry:
    def test_register_and_get(self):
        ProviderRegistry.register("llm", "mock", _mock_fn)
        fn = ProviderRegistry.get("llm", "mock")
        assert fn is _mock_fn

    def test_get_missing_raises(self):
        with pytest.raises(ProviderNotFoundError, match="llm.*ghost"):
            ProviderRegistry.get("llm", "ghost")

    def test_has(self):
        ProviderRegistry.register("tts", "azure", _mock_fn)
        assert ProviderRegistry.has("tts", "azure") is True
        assert ProviderRegistry.has("tts", "aws") is False

    def test_register_duplicate_raises(self):
        ProviderRegistry.register("llm", "dup", _mock_fn)
        with pytest.raises(OBaseRegistryConflict):
            ProviderRegistry.register("llm", "dup", _mock_fn)

    def test_register_replace(self):
        def fn_a():
            return "a"

        def fn_b():
            return "b"

        ProviderRegistry.register("llm", "replaceable", fn_a)
        ProviderRegistry.register("llm", "replaceable", fn_b, replace=True)
        assert ProviderRegistry.get("llm", "replaceable")() == "b"

    def test_list_providers_all(self):
        ProviderRegistry.register("img", "dalle", _mock_fn)
        ProviderRegistry.register("llm", "gpt4", _mock_fn)
        providers = ProviderRegistry.list_providers()
        assert ("img", "dalle") in providers
        assert ("llm", "gpt4") in providers

    def test_list_providers_filtered(self):
        ProviderRegistry.register("img", "sd", _mock_fn)
        ProviderRegistry.register("tts", "elevenlabs", _mock_fn)
        providers = ProviderRegistry.list_providers("img")
        assert all(cat == "img" for cat, _ in providers)

    def test_clear(self):
        ProviderRegistry.register("llm", "to_clear", _mock_fn)
        ProviderRegistry.clear()
        assert not ProviderRegistry.has("llm", "to_clear")

    def test_auto_discover_no_entry_points(self):
        """auto_discover with no registered entry points completes without error."""
        with patch("obase.provider_registry.entry_points", return_value=[]):
            ProviderRegistry.auto_discover()

    def test_auto_discover_registers_providers(self):
        mock_ep = MagicMock()
        mock_ep.name = "llm.mock_auto"
        mock_ep.load.return_value = _mock_fn

        with patch("obase.provider_registry.entry_points", return_value=[mock_ep]):
            ProviderRegistry.auto_discover()

        assert ProviderRegistry.has("llm", "mock_auto")

    def test_auto_discover_bad_ep_name_skipped(self):
        mock_ep = MagicMock()
        mock_ep.name = "no_dot_here"
        mock_ep.load.return_value = _mock_fn

        with patch("obase.provider_registry.entry_points", return_value=[mock_ep]):
            ProviderRegistry.auto_discover()

    def test_auto_discover_load_failure_raises(self):
        mock_ep = MagicMock()
        mock_ep.name = "llm.broken"
        mock_ep.load.side_effect = ImportError("missing dep")

        with patch("obase.provider_registry.entry_points", return_value=[mock_ep]):
            with pytest.raises(ProviderDiscoveryError, match="broken"):
                ProviderRegistry.auto_discover()
