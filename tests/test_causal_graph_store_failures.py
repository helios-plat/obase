from __future__ import annotations

from obase.causal_graph_store import CausalGraphStore


class TestRecordFailure:
    def test_auto_creates_missing_node(self):
        store = CausalGraphStore()
        store.record_failure("plan", "check failed")
        assert "plan" in store.nodes()

    def test_appends_to_existing_node(self):
        store = CausalGraphStore()
        store.add_node("plan", p_fail=0.1)
        store.record_failure("plan", "check failed", {"passed": False})
        failures = store.get_failures("plan")
        assert len(failures) == 1
        assert failures[0]["message"] == "check failed"
        assert failures[0]["result"] == {"passed": False}
        assert "ts" in failures[0]

    def test_multiple_failures_accumulate_in_order(self):
        store = CausalGraphStore()
        store.record_failure("plan", "first")
        store.record_failure("plan", "second")
        messages = [f["message"] for f in store.get_failures("plan")]
        assert messages == ["first", "second"]

    def test_get_failures_on_unknown_node_returns_empty(self):
        store = CausalGraphStore()
        assert store.get_failures("nope") == []

    def test_record_failure_does_not_touch_p_fail(self):
        store = CausalGraphStore()
        store.add_node("plan", p_fail=0.3)
        store.record_failure("plan", "check failed")
        assert store.node_attr("plan")["p_fail"] == 0.3

    def test_survives_to_dict_from_dict_round_trip(self):
        store = CausalGraphStore()
        store.add_node("plan", p_fail=0.2)
        store.record_failure("plan", "check failed", {"passed": False})
        restored = CausalGraphStore.from_dict(store.to_dict())
        failures = restored.get_failures("plan")
        assert len(failures) == 1
        assert failures[0]["message"] == "check failed"
