from app.summaries import build_observations


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


def test_empty_predictions_returns_no_history_message():
    obs = build_observations([], None, None, None, {}, {})
    assert len(obs) == 1
    assert "No prediction history" in obs[0]


def test_no_outcomes_produces_accuracy_unavailable_observation():
    obs = build_observations(
        [_p()], None, 0.70, 10000.0, {"qwen3:8b": 1}, {"finance": 1}
    )
    assert any("accuracy cannot be calculated" in o for o in obs)


def test_accuracy_observation_when_outcomes_present():
    preds = [
        _p(prediction="Yes", outcome="Yes"),
        _p(prediction="No", outcome="No"),
    ]
    obs = build_observations(
        preds,
        accuracy=1.0,
        avg_confidence=0.70,
        avg_execution_ms=10000.0,
        model_breakdown={"qwen3:8b": 2},
        category_breakdown={"finance": 2},
    )
    assert any("100.0%" in o for o in obs)


def test_partial_accuracy():
    preds = [
        _p(prediction="Yes", outcome="Yes"),
        _p(prediction="Yes", outcome="No"),
    ]
    obs = build_observations(
        preds,
        accuracy=0.5,
        avg_confidence=0.70,
        avg_execution_ms=10000.0,
        model_breakdown={"qwen3:8b": 2},
        category_breakdown={"finance": 2},
    )
    assert any("50.0%" in o for o in obs)


def test_single_model_observation():
    obs = build_observations(
        [_p()], None, 0.70, 10000.0, {"qwen3:8b": 1}, {"finance": 1}
    )
    assert any("qwen3:8b" in o for o in obs)


def test_multiple_models_observation():
    obs = build_observations(
        [_p(model="a"), _p(model="b"), _p(model="a")],
        None, 0.70, 10000.0, {"a": 2, "b": 1}, {"finance": 3},
    )
    assert any("2 models" in o for o in obs)


def test_category_observation():
    obs = build_observations(
        [_p()], None, 0.70, 10000.0, {"qwen3:8b": 1}, {"finance": 1}
    )
    assert any("finance" in o for o in obs)


def test_execution_time_observation():
    obs = build_observations(
        [_p(execution_ms=120000)],
        None, 0.70, 120000.0, {"qwen3:8b": 1}, {}
    )
    assert any("120.0s" in o for o in obs)


def test_high_confidence_accuracy_not_shown_below_threshold():
    # fewer than 5 outcomes → no high-confidence calibration observation
    preds = [
        _p(prediction="Yes", confidence=0.9, outcome="Yes"),
        _p(prediction="Yes", confidence=0.9, outcome="No"),
    ]
    obs = build_observations(
        preds, 0.5, 0.9, 10000.0, {"qwen3:8b": 2}, {"finance": 2}
    )
    assert not any("High-confidence" in o for o in obs)


def test_high_confidence_accuracy_shown_at_threshold():
    preds = [
        _p(prediction="Yes", confidence=0.9, outcome="Yes"),
        _p(prediction="Yes", confidence=0.9, outcome="Yes"),
        _p(prediction="Yes", confidence=0.9, outcome="Yes"),
        _p(prediction="Yes", confidence=0.9, outcome="Yes"),
        _p(prediction="Yes", confidence=0.9, outcome="Yes"),
    ]
    obs = build_observations(
        preds, 1.0, 0.9, 10000.0, {"qwen3:8b": 5}, {"finance": 5}
    )
    assert any("High-confidence" in o for o in obs)


def test_count_observation_present():
    obs = build_observations(
        [_p(), _p()], None, 0.70, 10000.0, {"qwen3:8b": 2}, {"finance": 2}
    )
    assert any("2 prediction(s)" in o for o in obs)
