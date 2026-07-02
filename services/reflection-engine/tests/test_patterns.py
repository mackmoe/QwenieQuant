from app.patterns import (
    detect_accuracy_trend,
    detect_all,
    detect_category_dominance,
    detect_confidence_pattern,
    detect_data_volume_pattern,
    detect_model_consistency,
)


def _s(
    accuracy=None,
    average_confidence=0.75,
    predictions_analyzed=10,
    outcomes_available=5,
    model_breakdown=None,
    category_breakdown=None,
):
    return {
        "accuracy": accuracy,
        "average_confidence": average_confidence,
        "predictions_analyzed": predictions_analyzed,
        "outcomes_available": outcomes_available,
        "model_breakdown": model_breakdown if model_breakdown is not None else {"qwen3:8b": predictions_analyzed},
        "category_breakdown": category_breakdown if category_breakdown is not None else {"finance": predictions_analyzed},
    }


# --- accuracy trend ---


def test_accuracy_trend_none_with_one_summary():
    assert detect_accuracy_trend([_s(accuracy=0.8)]) is None


def test_accuracy_trend_none_with_no_outcomes():
    assert detect_accuracy_trend([_s(accuracy=None), _s(accuracy=None)]) is None


def test_accuracy_trend_improving():
    # DESC order: recent=0.9, older=0.7 → chronological [0.7, 0.9]
    result = detect_accuracy_trend([_s(accuracy=0.9), _s(accuracy=0.7)])
    assert result is not None
    assert "improving" in result


def test_accuracy_trend_declining():
    # DESC order: recent=0.5, older=0.8 → chronological [0.8, 0.5]
    result = detect_accuracy_trend([_s(accuracy=0.5), _s(accuracy=0.8)])
    assert result is not None
    assert "declining" in result


def test_accuracy_trend_stable():
    # spread 0.01 < 0.05 threshold → stable
    result = detect_accuracy_trend([_s(accuracy=0.81), _s(accuracy=0.80)])
    assert result is not None
    assert "stable" in result


def test_accuracy_trend_variable():
    # chronological [0.8, 0.5, 0.9] → not monotonic → varied
    result = detect_accuracy_trend([_s(accuracy=0.9), _s(accuracy=0.5), _s(accuracy=0.8)])
    assert result is not None
    assert "varied" in result


# --- confidence pattern ---


def test_confidence_pattern_none_with_one_summary():
    assert detect_confidence_pattern([_s()]) is None


def test_confidence_pattern_consistently_high():
    summaries = [_s(average_confidence=0.80), _s(average_confidence=0.82)]
    result = detect_confidence_pattern(summaries)
    assert result is not None
    assert "consistently" in result
    assert "high" in result


def test_confidence_pattern_varied():
    summaries = [_s(average_confidence=0.90), _s(average_confidence=0.50)]
    result = detect_confidence_pattern(summaries)
    assert result is not None
    assert "varied" in result


# --- category dominance ---


def test_category_dominance_single_dominant():
    summaries = [
        _s(category_breakdown={"finance": 8, "sports": 2}),
        _s(category_breakdown={"finance": 9, "sports": 1}),
    ]
    result = detect_category_dominance(summaries)
    assert result is not None
    assert "finance" in result


def test_category_dominance_none_when_empty():
    assert detect_category_dominance([_s(category_breakdown={})]) is None


# --- model consistency ---


def test_model_consistency_single_model():
    summaries = [_s(model_breakdown={"qwen3:8b": 10}), _s(model_breakdown={"qwen3:8b": 5})]
    result = detect_model_consistency(summaries)
    assert result is not None
    assert "All" in result
    assert "qwen3:8b" in result


def test_model_consistency_multiple_models():
    summaries = [_s(model_breakdown={"qwen3:8b": 8, "llama3:8b": 2})]
    result = detect_model_consistency(summaries)
    assert result is not None
    assert "2 models" in result


def test_model_consistency_none_when_empty():
    assert detect_model_consistency([_s(model_breakdown={})]) is None


# --- data volume ---


def test_data_volume_low():
    summaries = [_s(predictions_analyzed=2), _s(predictions_analyzed=3)]
    result = detect_data_volume_pattern(summaries)
    assert result is not None
    assert "low" in result


def test_data_volume_sufficient_returns_none():
    summaries = [_s(predictions_analyzed=10), _s(predictions_analyzed=15)]
    assert detect_data_volume_pattern(summaries) is None


def test_data_volume_none_with_one_summary():
    assert detect_data_volume_pattern([_s(predictions_analyzed=2)]) is None


# --- detect_all ---


def test_detect_all_returns_list():
    assert isinstance(detect_all([_s(), _s()]), list)


def test_detect_all_empty_summaries_returns_empty_list():
    assert detect_all([]) == []
