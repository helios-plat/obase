"""Tests for obase.search_providers.LogSearchProvider and the SearchProvider
Protocol's integration with ProviderRegistry's generic-category mechanism
(no separate SearchProviderRegistry class)."""

from __future__ import annotations

import pytest

from obase.provider_registry import ProviderRegistry, SearchProvider
from obase.search_providers import LogSearchProvider


@pytest.fixture(autouse=True)
def _clean_registry():
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


class TestLogSearchProvider:
    async def test_upsert_doc_indexes_by_id(self):
        provider = LogSearchProvider()
        ok = await provider.upsert_doc(index="products", document={"id": "p1", "title": "T恤"})
        assert ok is True
        assert provider.indexed["products"]["p1"] == {"id": "p1", "title": "T恤"}

    async def test_upsert_doc_overwrites_existing(self):
        provider = LogSearchProvider()
        await provider.upsert_doc(index="products", document={"id": "p1", "title": "v1"})
        await provider.upsert_doc(index="products", document={"id": "p1", "title": "v2"})
        assert provider.indexed["products"]["p1"]["title"] == "v2"

    async def test_delete_doc_removes_and_returns_true(self):
        provider = LogSearchProvider()
        await provider.upsert_doc(index="products", document={"id": "p1", "title": "T恤"})
        removed = await provider.delete_doc(index="products", doc_id="p1")
        assert removed is True
        assert "p1" not in provider.indexed["products"]

    async def test_delete_missing_doc_returns_false(self):
        provider = LogSearchProvider()
        removed = await provider.delete_doc(index="products", doc_id="ghost")
        assert removed is False

    async def test_separate_indexes_are_isolated(self):
        provider = LogSearchProvider()
        await provider.upsert_doc(index="products", document={"id": "p1"})
        await provider.upsert_doc(index="categories", document={"id": "p1"})
        assert "p1" in provider.indexed["products"]
        assert "p1" in provider.indexed["categories"]
        await provider.delete_doc(index="products", doc_id="p1")
        assert "p1" not in provider.indexed["products"]
        assert "p1" in provider.indexed["categories"]


class TestSearchProviderRegistration:
    def test_log_provider_satisfies_protocol(self):
        provider = LogSearchProvider()
        assert isinstance(provider, SearchProvider)

    def test_register_and_retrieve_via_generic_category(self):
        provider = LogSearchProvider()
        ProviderRegistry.get().register_generic("search", "log", provider)
        retrieved = ProviderRegistry.get().generic("search", "log")
        assert retrieved is provider

    def test_unregistered_search_provider_raises(self):
        from obase.exceptions import ProviderNotFoundError

        with pytest.raises(ProviderNotFoundError, match="search.*ghost"):
            ProviderRegistry.get().generic("search", "ghost")
