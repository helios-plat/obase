from __future__ import annotations

import pytest

from obase.hierarchical_context import (
    HierarchicalContextError,
    HierarchicalContextStore,
    RetrievalResult,
    TokenBudgetExceeded,
    retrieve,
)


class TestUriValidation:
    def test_non_3o_uri_raises(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        with pytest.raises(HierarchicalContextError):
            store.write("file:///etc/passwd", "x")

    def test_path_escape_is_blocked(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        with pytest.raises(PermissionError):
            store.write("3o://../../etc/passwd", "x")


class TestWriteReadRoundTrip:
    def test_l2_write_then_read(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/api.md", "full body text")
        assert store.read("3o://resources/veya/api.md") == "full body text"

    def test_l0_and_l1_written_alongside_l2(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write(
            "3o://resources/veya/api.md",
            "full body text",
            abstract="short summary",
            overview="a bit more detail",
        )
        assert store.read("3o://resources/veya/api.md", "L0") == "short summary"
        assert store.read("3o://resources/veya/api.md", "L1") == "a bit more detail"
        assert store.read("3o://resources/veya/api.md", "L2") == "full body text"

    def test_missing_layer_raises_file_not_found(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/api.md", "full body text")
        with pytest.raises(FileNotFoundError):
            store.read("3o://resources/veya/api.md", "L0")

    def test_exists_checks_the_right_layer(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/api.md", "body", abstract="short")
        assert store.exists("3o://resources/veya/api.md", "L0") is True
        assert store.exists("3o://resources/veya/api.md", "L1") is False

    def test_set_abstract_and_overview_independently(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/api.md", "body")
        store.set_abstract("3o://resources/veya/api.md", "short summary")
        assert store.read("3o://resources/veya/api.md", "L0") == "short summary"


class TestTokenBudgets:
    def test_abstract_over_120_tokens_raises(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/api.md", "body")
        too_long = "word " * 200  # ~250 tokens under the len//4 estimator
        with pytest.raises(TokenBudgetExceeded):
            store.set_abstract("3o://resources/veya/api.md", too_long)

    def test_overview_over_2048_tokens_raises(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/api.md", "body")
        too_long = "word " * 5000
        with pytest.raises(TokenBudgetExceeded):
            store.set_overview("3o://resources/veya/api.md", too_long)

    def test_abstract_within_budget_succeeds(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/api.md", "body")
        store.set_abstract("3o://resources/veya/api.md", "a short one-liner")


class TestListUris:
    def test_lists_only_l2_files_under_prefix(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/a.md", "a", abstract="abs-a")
        store.write("3o://resources/veya/b.md", "b", overview="ov-b")
        store.write("3o://resources/other/c.md", "c")
        uris = store.list_uris("3o://resources/veya")
        assert set(uris) == {"3o://resources/veya/a.md", "3o://resources/veya/b.md"}

    def test_missing_prefix_returns_empty(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        assert store.list_uris("3o://nothing/here") == []

    def test_single_file_prefix_returns_that_uri(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/a.md", "a")
        assert store.list_uris("3o://resources/veya/a.md") == ["3o://resources/veya/a.md"]


class TestRetrieve:
    def _keyword_scorer(self, query: str, text: str):
        return 1.0 if query.lower() in text.lower() else 0.0

    def test_only_l0_read_when_below_threshold(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/a.md", "body", abstract="unrelated abstract")
        result = retrieve(store, "orchestrator", ["3o://resources/veya/a.md"], self._keyword_scorer)
        assert result.items[0]["layer"] == "L0"
        assert result.items[0]["score"] == 0.0
        assert [s.layer for s in result.trajectory] == ["L0"]

    def test_escalates_to_l1_above_threshold(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write(
            "3o://resources/veya/a.md",
            "body",
            abstract="mentions orchestrator",
            overview="deep dive on orchestrator internals",
        )
        result = retrieve(store, "orchestrator", ["3o://resources/veya/a.md"], self._keyword_scorer)
        assert result.items[0]["layer"] == "L1"
        assert [s.layer for s in result.trajectory] == ["L0", "L1"]

    def test_never_reads_l2(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write(
            "3o://resources/veya/a.md",
            "body should not appear",
            abstract="orchestrator",
            overview="orchestrator overview",
        )
        result = retrieve(store, "orchestrator", ["3o://resources/veya/a.md"], self._keyword_scorer)
        assert all(item["layer"] != "L2" for item in result.items)
        assert all(step.layer != "L2" for step in result.trajectory)

    def test_missing_l0_recorded_in_trajectory_and_excluded_from_items(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        result = retrieve(
            store, "orchestrator", ["3o://resources/veya/ghost.md"], self._keyword_scorer
        )
        assert result.items == []
        assert result.trajectory[0].reason == "no L0 abstract"

    def test_top_k_limits_returned_items(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        for i in range(5):
            store.write(f"3o://resources/veya/{i}.md", "body", abstract=f"orchestrator {i}")
        result = retrieve(
            store,
            "orchestrator",
            [f"3o://resources/veya/{i}.md" for i in range(5)],
            self._keyword_scorer,
            top_k=2,
        )
        assert len(result.items) == 2

    def test_tokens_used_reflects_actual_reads(self, tmp_path):
        store = HierarchicalContextStore(root=tmp_path)
        store.write("3o://resources/veya/a.md", "body", abstract="unrelated")
        result = retrieve(store, "orchestrator", ["3o://resources/veya/a.md"], self._keyword_scorer)
        assert result.tokens_used > 0
        assert isinstance(result, RetrievalResult)
