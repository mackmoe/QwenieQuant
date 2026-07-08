from app.patterns import (
    detect_accuracy_trend,
    detect_all,
    detect_calibration_gap,
    detect_category_dominance,
    detect_confidence_pattern,
    detect_data_volume_pattern,
    detect_model_consistency,
    detect_search_impact,
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


# --- detect_calibration_gap ---


def _s_with_calibration(low_acc, high_acc, low_resolved=5, high_resolved=5):
    return {
        **_s(),
        "diagnostics": {
            "confidence_buckets": [
                {"label": "50-60%", "accuracy": low_acc, "resolved": low_resolved},
                {"label": "80-90%", "accuracy": high_acc, "resolved": high_resolved},
            ]
        },
    }


def test_calibration_gap_detected_when_gap_narrow():
    result = detect_calibration_gap([_s_with_calibration(0.60, 0.62)])
    assert result is not None
    assert "calibration" in result.lower()


def test_calibration_gap_none_when_gap_sufficient():
    result = detect_calibration_gap([_s_with_calibration(0.50, 0.80)])
    assert result is None


def test_calibration_gap_none_without_diagnostics():
    assert detect_calibration_gap([_s()]) is None


def test_calibration_gap_none_when_insufficient_resolved():
    result = detect_calibration_gap([_s_with_calibration(0.60, 0.62, low_resolved=2, high_resolved=2)])
    assert result is None


def test_calibration_gap_none_when_no_accuracy():
    s = {
        **_s(),
        "diagnostics": {
            "confidence_buckets": [
                {"label": "50-60%", "accuracy": None, "resolved": 5},
                {"label": "80-90%", "accuracy": None, "resolved": 5},
            ]
        },
    }
    assert detect_calibration_gap([s]) is None


# --- detect_search_impact ---


def _s_with_search(with_acc, without_acc, with_n=5, without_n=5):
    delta = with_acc - without_acc if with_acc is not None and without_acc is not None else None
    return {
        **_s(),
        "diagnostics": {
            "search_effectiveness": {
                "with_search_count": with_n,
                "without_search_count": without_n,
                "with_search_accuracy": with_acc,
                "without_search_accuracy": without_acc,
                "accuracy_delta": delta,
            }
        },
    }


def test_search_impact_positive_reported():
    result = detect_search_impact([_s_with_search(0.80, 0.60)])
    assert result is not None
    assert "improves" in result


def test_search_impact_negative_reported():
    result = detect_search_impact([_s_with_search(0.40, 0.70)])
    assert result is not None
    assert "reduces" in result


def test_search_impact_none_without_diagnostics():
    assert detect_search_impact([_s()]) is None


def test_search_impact_none_when_insufficient_samples():
    result = detect_search_impact([_s_with_search(0.80, 0.50, with_n=2, without_n=2)])
    assert result is None


def test_search_impact_none_when_no_delta():
    s = {
        **_s(),
        "diagnostics": {
            "search_effectiveness": {
                "with_search_count": 5,
                "without_search_count": 5,
                "with_search_accuracy": None,
                "without_search_accuracy": None,
                "accuracy_delta": None,
            }
        },
    }
    assert detect_search_impact([s]) is None
