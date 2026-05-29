"""Tests for obase.text.fuzzy_match."""

from __future__ import annotations

import pytest

from obase.text import FuzzyMatchError, FuzzyMatchResult, fuzzy_match


class TestExactMatch:
    def test_exact_returns_score_one(self):
        results = fuzzy_match(query="apple", candidates=["apple"], threshold=0.8)
        assert len(results) == 1
        assert results[0].candidate == "apple"
        assert results[0].score == 1.0

    def test_result_is_fuzzy_match_result_instance(self):
        results = fuzzy_match(query="hello", candidates=["hello", "world"])
        assert isinstance(results[0], FuzzyMatchResult)


class TestNoMatch:
    def test_no_candidates_above_threshold_returns_empty(self):
        results = fuzzy_match(query="xyz", candidates=["apple", "banana", "cherry"], threshold=0.9)
        assert results == []

    def test_empty_candidates_returns_empty(self):
        results = fuzzy_match(query="apple", candidates=[])
        assert results == []


class TestThresholdBoundary:
    def test_threshold_one_exact_match_included(self):
        results = fuzzy_match(query="python", candidates=["python"], threshold=1.0)
        assert len(results) == 1
        assert results[0].score == 1.0

    def test_threshold_one_non_exact_excluded(self):
        # "pythn" is close but not exact — must not pass threshold=1.0
        results = fuzzy_match(query="python", candidates=["pythn", "ruby"], threshold=1.0)
        assert results == []

    def test_threshold_zero_includes_all(self):
        results = fuzzy_match(
            query="a",
            candidates=["apple", "banana", "cherry"],
            threshold=0.0,
            top_k=10,
        )
        assert len(results) == 3


class TestMultiCandidateSorting:
    def test_results_sorted_by_score_descending(self):
        # "bank" is closer to "bank" than to "banking" or "tank"
        results = fuzzy_match(
            query="bank",
            candidates=["tank", "banking", "bank", "completely_unrelated_zzz"],
            threshold=0.5,
            top_k=3,
        )
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0].candidate == "bank"

    def test_top_k_limits_result_count(self):
        results = fuzzy_match(
            query="test",
            candidates=["test", "testing", "tested", "tester", "tests"],
            threshold=0.5,
            top_k=2,
        )
        assert len(results) <= 2


class TestUnicodeChinese:
    def test_exact_chinese_match(self):
        results = fuzzy_match(
            query="苹果",
            candidates=["苹果", "苹果公司", "香蕉"],
            threshold=0.7,
            top_k=3,
        )
        candidates_returned = [r.candidate for r in results]
        assert "苹果" in candidates_returned
        assert results[0].candidate == "苹果"
        assert results[0].score == 1.0

    def test_chinese_no_match(self):
        results = fuzzy_match(
            query="北京",
            candidates=["上海", "广州", "深圳"],
            threshold=0.9,
        )
        assert results == []

    def test_chinese_partial_theme_match(self):
        results = fuzzy_match(
            query="新能源",
            candidates=["新能源汽车", "传统能源", "新能源"],
            threshold=0.7,
            top_k=3,
        )
        assert len(results) >= 1
        assert results[0].candidate == "新能源"


class TestInvalidArguments:
    def test_threshold_above_one_raises(self):
        with pytest.raises(FuzzyMatchError, match="threshold"):
            fuzzy_match(query="x", candidates=["x"], threshold=1.1)

    def test_threshold_below_zero_raises(self):
        with pytest.raises(FuzzyMatchError, match="threshold"):
            fuzzy_match(query="x", candidates=["x"], threshold=-0.1)

    def test_top_k_zero_raises(self):
        with pytest.raises(FuzzyMatchError, match="top_k"):
            fuzzy_match(query="x", candidates=["x"], top_k=0)
