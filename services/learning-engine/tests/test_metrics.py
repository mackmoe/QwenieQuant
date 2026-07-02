import pytest
from app.metrics import (
    compute_accuracy,
    compute_average_confidence,
    compute_average_execution_ms,
    compute_category_breakdown,
    compute_model_breakdown,
)


def _p(
    prediction="Yes",
    confidence=0.70,
    model="qwen3:8b",
    category="finance",
    execution_ms=10000,
    outcome=None,
):
    return {
        "prediction": prediction,
        "confidence": confidence,
        "model": model,
        "category": category,
        "execution_ms": execution_ms,
        "outcome": outcome,
    }


# --- accuracy ---


def test_accuracy_returns_none_when_no_outcomes():
    assert compute_accuracy([_p(), _p()]) is None


def test_accuracy_returns_none_for_empty_list():
    assert compute_accuracy([]) is None


def test_accuracy_all_correct():
    preds = [_p(prediction="Yes", outcome="Yes"), _p(prediction="No", outcome="No")]
    assert compute_accuracy(preds) == 1.0


def test_accuracy_all_incorrect():
    preds = [_p(prediction="Yes", outcome="No"), _p(prediction="No", outcome="Yes")]
    assert compute_accuracy(preds) == 0.0


def test_accuracy_mixed():
    preds = [
        _p(prediction="Yes", outcome="Yes"),
        _p(prediction="Yes", outcome="No"),
    ]
    assert compute_accuracy(preds) == 0.5


def test_accuracy_ignores_unresolved_predictions():
    preds = [
        _p(prediction="Yes", outcome="Yes"),
        _p(prediction="Yes", outcome=None),
    ]
    assert compute_accuracy(preds) == 1.0


def test_accuracy_only_resolved_count():
    preds = [
        _p(prediction="Yes", outcome="Yes"),
        _p(prediction="No", outcome="No"),
        _p(prediction="Yes", outcome=None),
    ]
    assert compute_accuracy(preds) == 1.0


# --- confidence ---


def test_average_confidence_empty():
    assert compute_average_confidence([]) is None


def test_average_confidence_single():
    assert compute_average_confidence([_p(confidence=0.8)]) == pytest.approx(0.8)


def test_average_confidence_multiple():
    preds = [_p(confidence=0.6), _p(confidence=0.8)]
    assert compute_average_confidence(preds) == pytest.approx(0.7)


# --- execution time ---


def test_average_execution_ms_empty():
    assert compute_average_execution_ms([]) is None


def test_average_execution_ms_single():
    assert compute_average_execution_ms([_p(execution_ms=100)]) == pytest.approx(100.0)


def test_average_execution_ms_multiple():
    preds = [_p(execution_ms=100), _p(execution_ms=200)]
    assert compute_average_execution_ms(preds) == pytest.approx(150.0)


# --- breakdowns ---


def test_model_breakdown_single_model():
    preds = [_p(model="qwen3:8b"), _p(model="qwen3:8b")]
    assert compute_model_breakdown(preds) == {"qwen3:8b": 2}


def test_model_breakdown_multiple_models():
    preds = [_p(model="a"), _p(model="b"), _p(model="a")]
    assert compute_model_breakdown(preds) == {"a": 2, "b": 1}


def test_model_breakdown_empty():
    assert compute_model_breakdown([]) == {}


def test_category_breakdown():
    preds = [
        _p(category="finance"),
        _p(category="sports"),
        _p(category="finance"),
    ]
    assert compute_category_breakdown(preds) == {"finance": 2, "sports": 1}


def test_category_breakdown_empty():
    assert compute_category_breakdown([]) == {}


