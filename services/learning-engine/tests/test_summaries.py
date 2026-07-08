from app.models import Diagnostics, CategoryStat, DirectionStat, YesNoAnalysis, SearchEffectiveness
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


def test_high_confidence_accuracy_case_insensitive_kalshi_lowercase():
    # Kalshi returns "yes"/"no" (lowercase) in outcome; prediction-api stores
    # "Yes"/"No". High-confidence accuracy must not treat these as wrong.
    preds = [
        _p(prediction="Yes", confidence=0.9, outcome="yes"),
        _p(prediction="Yes", confidence=0.9, outcome="yes"),
        _p(prediction="Yes", confidence=0.9, outcome="yes"),
        _p(prediction="No",  confidence=0.9, outcome="no"),
        _p(prediction="No",  confidence=0.9, outcome="no"),
    ]
    obs = build_observations(
        preds, 1.0, 0.9, 10000.0, {"qwen3:8b": 5}, {"finance": 5}
    )
    assert any("High-confidence" in o for o in obs)
    assert any("100.0%" in o for o in obs)


# ---------------------------------------------------------------------------
# Diagnostic observations (SPEC-030)
# ---------------------------------------------------------------------------


def _diag_with_categories(finance_acc: float, sports_acc: float) -> Diagnostics:
    return Diagnostics(
        category_performance=[
            CategoryStat(category="finance", count=5, resolved=5, accuracy=finance_acc),
            CategoryStat(category="sports", count=5, resolved=5, accuracy=sports_acc),
        ]
    )


def test_diagnostic_obs_category_best_worst_when_enough_data():
    diag = _diag_with_categories(0.3, 0.9)
    obs = build_observations([_p()], None, 0.7, 10000.0, {}, {}, diagnostics=diag)
    combined = " ".join(obs)
    assert "sports" in combined
    assert "finance" in combined


def test_diagnostic_obs_category_skipped_when_insufficient_resolved():
    diag = Diagnostics(
        category_performance=[
            CategoryStat(category="finance", count=2, resolved=2, accuracy=0.3),
            CategoryStat(category="sports", count=2, resolved=2, accuracy=0.9),
        ]
    )
    obs = build_observations([_p()], None, 0.7, 10000.0, {}, {}, diagnostics=diag)
    # Neither category has >= 3 resolved — no category diagnostic
    assert not any("Strongest category" in o for o in obs)


def test_diagnostic_obs_yes_no_bias_when_delta_large():
    diag = Diagnostics(
        yes_no_analysis=YesNoAnalysis(
            yes=DirectionStat(count=5, resolved=5, accuracy=0.9),
            no=DirectionStat(count=5, resolved=5, accuracy=0.4),
        )
    )
    obs = build_observations([_p()], 0.5, 0.7, 10000.0, {}, {}, diagnostics=diag)
    assert any("YES" in o for o in obs)


def test_diagnostic_obs_yes_no_skipped_when_delta_small():
    diag = Diagnostics(
        yes_no_analysis=YesNoAnalysis(
            yes=DirectionStat(count=5, resolved=5, accuracy=0.60),
            no=DirectionStat(count=5, resolved=5, accuracy=0.62),
        )
    )
    obs = build_observations([_p()], 0.5, 0.7, 10000.0, {}, {}, diagnostics=diag)
    assert not any("outperform" in o for o in obs)


def test_diagnostic_obs_search_impact_when_meaningful():
    diag = Diagnostics(
        search_effectiveness=SearchEffectiveness(
            with_search_count=10,
            without_search_count=10,
            with_search_accuracy=0.8,
            without_search_accuracy=0.5,
            accuracy_delta=0.3,
        )
    )
    obs = build_observations([_p()], 0.5, 0.7, 10000.0, {}, {}, diagnostics=diag)
    assert any("SearXNG" in o for o in obs)


def test_diagnostic_obs_search_skipped_when_insufficient_samples():
    diag = Diagnostics(
        search_effectiveness=SearchEffectiveness(
            with_search_count=2,
            without_search_count=2,
            with_search_accuracy=0.8,
            without_search_accuracy=0.5,
            accuracy_delta=0.3,
        )
    )
    obs = build_observations([_p()], 0.5, 0.7, 10000.0, {}, {}, diagnostics=diag)
    assert not any("SearXNG" in o for o in obs)


def test_no_diagnostics_passed_backward_compatible():
    # Calling without diagnostics param works as before
    obs = build_observations(
        [_p()], None, 0.70, 10000.0, {"qwen3:8b": 1}, {"finance": 1}
    )
    assert len(obs) > 0


def test_diagnostic_obs_capped_at_five():
    # Construct diagnostics that would generate many observations
    diag = Diagnostics(
        category_performance=[
            CategoryStat(category=f"cat{i}", count=5, resolved=5, accuracy=i * 0.1)
            for i in range(1, 9)
        ],
        yes_no_analysis=YesNoAnalysis(
            yes=DirectionStat(count=5, resolved=5, accuracy=0.9),
            no=DirectionStat(count=5, resolved=5, accuracy=0.2),
        ),
        search_effectiveness=SearchEffectiveness(
            with_search_count=10,
            without_search_count=10,
            with_search_accuracy=0.9,
            without_search_accuracy=0.4,
            accuracy_delta=0.5,
        ),
    )
    obs = build_observations([_p()], 0.5, 0.7, 10000.0, {}, {}, diagnostics=diag)
    # The diagnostic portion is capped at 5 observations
    diag_obs = [o for o in obs if any(
        kw in o for kw in ("Strongest", "YES", "NO", "SearXNG", "Risk-approved")
    )]
    assert len(diag_obs) <= 5
