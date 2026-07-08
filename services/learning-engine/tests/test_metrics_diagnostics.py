"""
Tests for SPEC-030 diagnostic metric functions.

All functions are pure — no I/O, no mocking required.
"""

from datetime import datetime, timezone

import pytest
from app.metrics import (
    compute_category_performance,
    compute_confidence_buckets,
    compute_extremes,
    compute_model_performance,
    compute_ranking_effectiveness,
    compute_risk_effectiveness,
    compute_search_effectiveness,
    compute_weekly_drift,
    compute_yes_no_analysis,
)


def _p(
    prediction="Yes",
    confidence=0.75,
    model="qwen3:8b",
    category="finance",
    execution_ms=10000,
    outcome=None,
    search_used=False,
    approved=None,
    queue_priority_score=None,
    created_at=None,
):
    return {
        "prediction": prediction,
        "confidence": confidence,
        "model": model,
        "category": category,
        "execution_ms": execution_ms,
        "outcome": outcome,
        "search_used": search_used,
        "approved": approved,
        "queue_priority_score": queue_priority_score,
        "created_at": created_at or datetime(2026, 6, 1, tzinfo=timezone.utc),
    }


# ---------------------------------------------------------------------------
# compute_category_performance
# ---------------------------------------------------------------------------


def test_category_performance_empty():
    assert compute_category_performance([]) == []


def test_category_performance_single_category_no_outcomes():
    result = compute_category_performance([_p(category="finance")])
    assert len(result) == 1
    assert result[0]["category"] == "finance"
    assert result[0]["count"] == 1
    assert result[0]["resolved"] == 0
    assert result[0]["accuracy"] is None


def test_category_performance_accuracy_computed():
    preds = [
        _p(category="finance", prediction="Yes", outcome="Yes"),
        _p(category="finance", prediction="Yes", outcome="No"),
    ]
    result = compute_category_performance(preds)
    assert result[0]["accuracy"] == pytest.approx(0.5)


def test_category_performance_multiple_categories():
    preds = [
        _p(category="finance", prediction="Yes", outcome="Yes"),
        _p(category="sports", prediction="No", outcome="No"),
        _p(category="sports", prediction="No", outcome="Yes"),
    ]
    result = compute_category_performance(preds)
    assert len(result) == 2
    cats = {r["category"]: r for r in result}
    assert cats["finance"]["accuracy"] == pytest.approx(1.0)
    assert cats["sports"]["accuracy"] == pytest.approx(0.5)


def test_category_performance_sorted_alphabetically():
    preds = [_p(category="weather"), _p(category="finance"), _p(category="sports")]
    result = compute_category_performance(preds)
    assert [r["category"] for r in result] == ["finance", "sports", "weather"]


def test_category_performance_average_confidence():
    preds = [
        _p(category="finance", confidence=0.6),
        _p(category="finance", confidence=0.8),
    ]
    result = compute_category_performance(preds)
    assert result[0]["average_confidence"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# compute_yes_no_analysis
# ---------------------------------------------------------------------------


def test_yes_no_analysis_empty():
    result = compute_yes_no_analysis([])
    assert result["yes"]["count"] == 0
    assert result["no"]["count"] == 0
    assert result["yes"]["accuracy"] is None
    assert result["no"]["accuracy"] is None


def test_yes_no_analysis_only_yes():
    preds = [
        _p(prediction="Yes", outcome="Yes"),
        _p(prediction="Yes", outcome="No"),
    ]
    result = compute_yes_no_analysis(preds)
    assert result["yes"]["count"] == 2
    assert result["yes"]["resolved"] == 2
    assert result["yes"]["accuracy"] == pytest.approx(0.5)
    assert result["no"]["count"] == 0


def test_yes_no_analysis_mixed():
    preds = [
        _p(prediction="Yes", outcome="Yes"),
        _p(prediction="No", outcome="Yes"),
        _p(prediction="No", outcome="No"),
    ]
    result = compute_yes_no_analysis(preds)
    assert result["yes"]["accuracy"] == pytest.approx(1.0)
    assert result["no"]["accuracy"] == pytest.approx(0.5)


def test_yes_no_analysis_case_insensitive():
    preds = [_p(prediction="yes", outcome="yes"), _p(prediction="NO", outcome="no")]
    result = compute_yes_no_analysis(preds)
    assert result["yes"]["count"] == 1
    assert result["no"]["count"] == 1


# ---------------------------------------------------------------------------
# compute_confidence_buckets
# ---------------------------------------------------------------------------


def test_confidence_buckets_returns_five_buckets():
    result = compute_confidence_buckets([])
    assert len(result) == 5


def test_confidence_buckets_labels():
    result = compute_confidence_buckets([])
    labels = [b["label"] for b in result]
    assert "50-60%" in labels
    assert "90-100%" in labels


def test_confidence_buckets_routing():
    preds = [
        _p(confidence=0.55),
        _p(confidence=0.65),
        _p(confidence=0.75),
        _p(confidence=0.85),
        _p(confidence=0.95),
    ]
    result = compute_confidence_buckets(preds)
    for bucket in result:
        assert bucket["count"] == 1


def test_confidence_buckets_accuracy():
    preds = [
        _p(confidence=0.75, prediction="Yes", outcome="Yes"),
        _p(confidence=0.75, prediction="Yes", outcome="No"),
    ]
    result = compute_confidence_buckets(preds)
    bucket_70_80 = next(b for b in result if b["label"] == "70-80%")
    assert bucket_70_80["accuracy"] == pytest.approx(0.5)


def test_confidence_buckets_empty_bucket_null_accuracy():
    result = compute_confidence_buckets([])
    for bucket in result:
        assert bucket["accuracy"] is None
        assert bucket["count"] == 0


# ---------------------------------------------------------------------------
# compute_search_effectiveness
# ---------------------------------------------------------------------------


def test_search_effectiveness_empty():
    result = compute_search_effectiveness([])
    assert result["with_search_count"] == 0
    assert result["without_search_count"] == 0
    assert result["accuracy_delta"] is None


def test_search_effectiveness_partitions_correctly():
    preds = [
        _p(search_used=True),
        _p(search_used=True),
        _p(search_used=False),
    ]
    result = compute_search_effectiveness(preds)
    assert result["with_search_count"] == 2
    assert result["without_search_count"] == 1


def test_search_effectiveness_accuracy_delta():
    preds = [
        _p(search_used=True, prediction="Yes", outcome="Yes"),
        _p(search_used=False, prediction="Yes", outcome="No"),
    ]
    result = compute_search_effectiveness(preds)
    assert result["with_search_accuracy"] == pytest.approx(1.0)
    assert result["without_search_accuracy"] == pytest.approx(0.0)
    assert result["accuracy_delta"] == pytest.approx(1.0)


def test_search_effectiveness_no_delta_when_one_side_empty():
    preds = [_p(search_used=True, prediction="Yes", outcome="Yes")]
    result = compute_search_effectiveness(preds)
    assert result["accuracy_delta"] is None


def test_search_effectiveness_none_treated_as_false():
    preds = [
        _p(search_used=None),
        _p(search_used=False),
    ]
    result = compute_search_effectiveness(preds)
    assert result["without_search_count"] == 2
    assert result["with_search_count"] == 0


# ---------------------------------------------------------------------------
# compute_ranking_effectiveness
# ---------------------------------------------------------------------------


def test_ranking_effectiveness_empty():
    assert compute_ranking_effectiveness([]) == []


def test_ranking_effectiveness_no_scored_predictions():
    preds = [_p(queue_priority_score=None), _p(queue_priority_score=None)]
    assert compute_ranking_effectiveness(preds) == []


def test_ranking_effectiveness_high_tier():
    preds = [
        _p(queue_priority_score=85.0, prediction="Yes", outcome="Yes"),
        _p(queue_priority_score=90.0, prediction="Yes", outcome="Yes"),
    ]
    result = compute_ranking_effectiveness(preds)
    high = next((t for t in result if t["label"].startswith("High")), None)
    assert high is not None
    assert high["count"] == 2
    assert high["accuracy"] == pytest.approx(1.0)


def test_ranking_effectiveness_three_tiers():
    preds = [
        _p(queue_priority_score=85.0),
        _p(queue_priority_score=60.0),
        _p(queue_priority_score=30.0),
    ]
    result = compute_ranking_effectiveness(preds)
    assert len(result) == 3


def test_ranking_effectiveness_skips_empty_tiers():
    preds = [_p(queue_priority_score=85.0), _p(queue_priority_score=90.0)]
    result = compute_ranking_effectiveness(preds)
    # Only High tier has predictions
    assert len(result) == 1
    assert result[0]["label"].startswith("High")


# ---------------------------------------------------------------------------
# compute_risk_effectiveness
# ---------------------------------------------------------------------------


def test_risk_effectiveness_empty():
    result = compute_risk_effectiveness([])
    assert result["approved_count"] == 0
    assert result["rejected_count"] == 0
    assert result["approved_accuracy"] is None
    assert result["rejected_accuracy"] is None


def test_risk_effectiveness_approved_only():
    preds = [
        _p(approved=True, prediction="Yes", outcome="Yes"),
        _p(approved=True, prediction="Yes", outcome="No"),
    ]
    result = compute_risk_effectiveness(preds)
    assert result["approved_count"] == 2
    assert result["rejected_count"] == 0
    assert result["approved_accuracy"] == pytest.approx(0.5)
    assert result["rejected_accuracy"] is None


def test_risk_effectiveness_both_sides():
    preds = [
        _p(approved=True, prediction="Yes", outcome="Yes"),
        _p(approved=False, prediction="Yes", outcome="No"),
    ]
    result = compute_risk_effectiveness(preds)
    assert result["approved_accuracy"] == pytest.approx(1.0)
    assert result["rejected_accuracy"] == pytest.approx(0.0)


def test_risk_effectiveness_ignores_none_approved():
    preds = [
        _p(approved=None),
        _p(approved=True, prediction="Yes", outcome="Yes"),
    ]
    result = compute_risk_effectiveness(preds)
    assert result["approved_count"] == 1
    assert result["rejected_count"] == 0


# ---------------------------------------------------------------------------
# compute_weekly_drift
# ---------------------------------------------------------------------------


def test_weekly_drift_empty():
    assert compute_weekly_drift([]) == []


def test_weekly_drift_skips_missing_created_at():
    preds = [{"prediction": "Yes", "confidence": 0.7, "outcome": None, "created_at": None}]
    assert compute_weekly_drift(preds) == []


def test_weekly_drift_groups_by_iso_week():
    preds = [
        _p(created_at=datetime(2026, 6, 1, tzinfo=timezone.utc)),  # W23
        _p(created_at=datetime(2026, 6, 8, tzinfo=timezone.utc)),  # W24
        _p(created_at=datetime(2026, 6, 9, tzinfo=timezone.utc)),  # W24
    ]
    result = compute_weekly_drift(preds)
    assert len(result) == 2
    assert result[0]["count"] == 1  # W23 first (sorted)
    assert result[1]["count"] == 2  # W24


def test_weekly_drift_accuracy_per_week():
    preds = [
        _p(created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
           prediction="Yes", outcome="Yes"),
        _p(created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
           prediction="Yes", outcome="No"),
    ]
    result = compute_weekly_drift(preds)
    assert len(result) == 1
    assert result[0]["accuracy"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# compute_model_performance
# ---------------------------------------------------------------------------


def test_model_performance_empty():
    assert compute_model_performance([]) == []


def test_model_performance_single_model():
    preds = [
        _p(model="qwen3:8b", execution_ms=10000, prediction="Yes", outcome="Yes"),
        _p(model="qwen3:8b", execution_ms=20000, prediction="Yes", outcome="No"),
    ]
    result = compute_model_performance(preds)
    assert len(result) == 1
    assert result[0]["model"] == "qwen3:8b"
    assert result[0]["count"] == 2
    assert result[0]["accuracy"] == pytest.approx(0.5)
    assert result[0]["average_execution_ms"] == pytest.approx(15000.0)


def test_model_performance_multiple_models():
    preds = [
        _p(model="qwen3:8b", prediction="Yes", outcome="Yes"),
        _p(model="llama3:8b", prediction="Yes", outcome="No"),
    ]
    result = compute_model_performance(preds)
    assert len(result) == 2
    models = {r["model"]: r for r in result}
    assert models["qwen3:8b"]["accuracy"] == pytest.approx(1.0)
    assert models["llama3:8b"]["accuracy"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_extremes
# ---------------------------------------------------------------------------


def test_extremes_empty_inputs():
    failures, successes = compute_extremes([], {}, [], [], {})
    assert failures == []
    assert successes == []


def test_extremes_insufficient_resolved():
    cat_perf = [
        {"category": "finance", "accuracy": 0.3, "resolved": 2},
    ]
    failures, successes = compute_extremes(cat_perf, {}, [], [], {})
    assert failures == []
    assert successes == []


def test_extremes_identifies_worst_segment():
    cat_perf = [
        {"category": "finance", "accuracy": 0.3, "resolved": 5},
        {"category": "sports", "accuracy": 0.9, "resolved": 5},
    ]
    failures, successes = compute_extremes(cat_perf, {}, [], [], {})
    assert any("finance" in f for f in failures)
    assert any("sports" in s for s in successes)


def test_extremes_includes_yes_no_when_sufficient():
    yes_no = {
        "yes": {"accuracy": 0.2, "resolved": 10},
        "no": {"accuracy": 0.8, "resolved": 10},
    }
    failures, successes = compute_extremes([], yes_no, [], [], {})
    assert any("YES" in f for f in failures)
    assert any("NO" in s for s in successes)


def test_extremes_caps_at_five():
    cat_perf = [
        {"category": f"cat{i}", "accuracy": i * 0.1, "resolved": 5}
        for i in range(10)
    ]
    failures, successes = compute_extremes(cat_perf, {}, [], [], {})
    assert len(failures) <= 5
    assert len(successes) <= 5
