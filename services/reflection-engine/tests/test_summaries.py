from app.summaries import extract_strengths, extract_weaknesses, generate_recommendations


def _s(
    predictions_analyzed=10,
    outcomes_available=5,
    accuracy=0.80,
    average_confidence=0.78,
    average_execution_ms=90_000.0,
    model_breakdown=None,
    category_breakdown=None,
):
    return {
        "predictions_analyzed": predictions_analyzed,
        "outcomes_available": outcomes_available,
        "accuracy": accuracy,
        "average_confidence": average_confidence,
        "average_execution_ms": average_execution_ms,
        "model_breakdown": model_breakdown or {"qwen3:8b": predictions_analyzed},
        "category_breakdown": category_breakdown or {"finance": predictions_analyzed},
    }


# --- strengths ---


def test_high_accuracy_is_strength():
    strengths = extract_strengths(_s(accuracy=0.85, outcomes_available=5))
    assert any("Accuracy" in s for s in strengths)


def test_low_accuracy_not_a_strength():
    strengths = extract_strengths(_s(accuracy=0.40, outcomes_available=5))
    assert not any("Accuracy" in s for s in strengths)


def test_insufficient_outcomes_suppresses_accuracy_strength():
    # 2 outcomes < 3 minimum → accuracy strength not produced even if high
    strengths = extract_strengths(_s(accuracy=0.95, outcomes_available=2))
    assert not any("Accuracy" in s for s in strengths)


def test_high_confidence_is_strength():
    strengths = extract_strengths(_s(average_confidence=0.80))
    assert any("confidence" in s.lower() for s in strengths)


def test_low_confidence_not_a_strength():
    strengths = extract_strengths(_s(average_confidence=0.50))
    assert not any("confidence" in s.lower() for s in strengths)


def test_fast_execution_is_strength():
    strengths = extract_strengths(_s(average_execution_ms=30_000.0))  # 30 s
    assert any("Inference" in s for s in strengths)


def test_slow_execution_not_a_strength():
    strengths = extract_strengths(_s(average_execution_ms=200_000.0))  # 200 s
    assert not any("within acceptable range" in s for s in strengths)


def test_sufficient_volume_is_strength():
    strengths = extract_strengths(_s(predictions_analyzed=10))
    assert any("10" in s for s in strengths)


def test_low_volume_not_a_strength():
    strengths = extract_strengths(_s(predictions_analyzed=3))
    assert not any("reasonable sample size" in s for s in strengths)


# --- weaknesses ---


def test_no_outcomes_is_weakness():
    weaknesses = extract_weaknesses(_s(outcomes_available=0, accuracy=None))
    assert any("accuracy cannot be assessed" in w for w in weaknesses)


def test_insufficient_outcomes_is_weakness():
    weaknesses = extract_weaknesses(_s(outcomes_available=2, accuracy=1.0))
    assert any("insufficient" in w for w in weaknesses)


def test_low_accuracy_is_weakness():
    weaknesses = extract_weaknesses(_s(accuracy=0.40, outcomes_available=5))
    assert any("below" in w for w in weaknesses)


def test_high_accuracy_not_a_weakness():
    weaknesses = extract_weaknesses(_s(accuracy=0.85, outcomes_available=5))
    assert not any("below" in w for w in weaknesses)


def test_low_confidence_is_weakness():
    weaknesses = extract_weaknesses(_s(average_confidence=0.40))
    assert any("low" in w.lower() for w in weaknesses)


def test_slow_execution_is_weakness():
    weaknesses = extract_weaknesses(_s(average_execution_ms=200_000.0))
    assert any("above" in w for w in weaknesses)


def test_low_volume_is_weakness():
    weaknesses = extract_weaknesses(_s(predictions_analyzed=2))
    assert any("insufficient" in w for w in weaknesses)


# --- recommendations ---


def test_no_outcomes_recommendation():
    recs = generate_recommendations([], [], _s(outcomes_available=0, accuracy=None))
    assert any("outcome" in r.lower() for r in recs)


def test_few_outcomes_recommendation():
    recs = generate_recommendations([], [], _s(outcomes_available=2, accuracy=0.5))
    assert any("more resolved" in r.lower() for r in recs)


def test_low_accuracy_recommendation():
    recs = generate_recommendations([], [], _s(accuracy=0.40, outcomes_available=5))
    assert any("calibration" in r.lower() for r in recs)


def test_low_volume_recommendation():
    recs = generate_recommendations([], [], _s(predictions_analyzed=3, outcomes_available=3))
    assert any("volume" in r.lower() for r in recs)


def test_default_recommendation_when_no_issues():
    recs = generate_recommendations(
        ["strength"],
        [],
        _s(accuracy=0.90, outcomes_available=10, predictions_analyzed=20),
    )
    assert len(recs) > 0
    assert any("monitoring" in r.lower() for r in recs)
