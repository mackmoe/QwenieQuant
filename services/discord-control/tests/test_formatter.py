from app.formatter import (
    UNAUTHORIZED_MESSAGE,
    format_analysis,
    format_error,
    format_prediction,
    format_reflection,
    format_status,
)

_HEALTH_ALL_OK = {
    "prediction_api": {"status": "ok"},
    "learning_engine": {"status": "ok", "postgres": True},
    "reflection_engine": {"status": "ok"},
    "ollama": {"reachable": True},
    "searxng": {"reachable": True},
}

_PREDICTION_OK = {
    "prediction": "Yes",
    "confidence": 0.75,
    "reasoning": "Because recent economic data suggests strong growth.",
}

_ANALYSIS_OK = {
    "analysis_id": "analysis_20260101T000000_aabbccdd",
    "predictions_analyzed": 10,
    "outcomes_available": 5,
    "accuracy": 0.80,
    "average_confidence": 0.75,
    "time_range": "2026-01-01 to 2026-07-01",
    "observations": ["10 prediction(s) analyzed.", "Accuracy is 80.0%."],
}

_REFLECTION_OK = {
    "reflection_id": "reflection_20260101T000000_aabbccdd",
    "strengths": ["High accuracy."],
    "weaknesses": ["Low volume."],
    "patterns": ["Single model used."],
    "recommendations": ["Collect more data."],
}


# --- format_status ---


def test_format_status_all_ok_has_checkmarks():
    result = format_status(_HEALTH_ALL_OK)
    assert result.count("✅") == 6


def test_format_status_includes_all_six_services():
    result = format_status(_HEALTH_ALL_OK)
    for service in ("Prediction API", "Learning Engine", "Reflection Engine",
                    "PostgreSQL", "Ollama", "SearXNG"):
        assert service in result, f"Missing: {service}"


def test_format_status_degraded_shows_cross():
    health = {**_HEALTH_ALL_OK, "prediction_api": {"status": "degraded"}}
    result = format_status(health)
    assert "❌" in result


def test_format_status_unreachable_postgres():
    health = {**_HEALTH_ALL_OK, "learning_engine": {"status": "ok", "postgres": False}}
    result = format_status(health)
    assert "❌" in result


def test_format_status_missing_service_shows_unreachable():
    result = format_status({"prediction_api": {}, "learning_engine": {},
                            "reflection_engine": {}, "ollama": {}, "searxng": {}})
    assert "unreachable" in result


# --- format_prediction ---


def test_format_prediction_shows_answer():
    result = format_prediction(_PREDICTION_OK)
    assert "Yes" in result


def test_format_prediction_shows_confidence():
    result = format_prediction(_PREDICTION_OK)
    assert "75%" in result


def test_format_prediction_truncates_long_reasoning():
    long_pred = {**_PREDICTION_OK, "reasoning": "X" * 500}
    result = format_prediction(long_pred)
    assert len(result) < 600


def test_format_prediction_error():
    result = format_prediction({"error": "Service unavailable"})
    assert "❌" in result
    assert "Service unavailable" in result


# --- format_analysis ---


def test_format_analysis_shows_counts():
    result = format_analysis(_ANALYSIS_OK)
    assert "10" in result  # predictions_analyzed


def test_format_analysis_shows_accuracy():
    result = format_analysis(_ANALYSIS_OK)
    assert "80" in result


def test_format_analysis_null_accuracy_shows_na():
    summary = {**_ANALYSIS_OK, "accuracy": None}
    result = format_analysis(summary)
    assert "N/A" in result


def test_format_analysis_shows_observations():
    result = format_analysis(_ANALYSIS_OK)
    assert "Observations" in result


def test_format_analysis_error():
    result = format_analysis({"error": "Engine down"})
    assert "❌" in result


# --- format_reflection ---


def test_format_reflection_has_all_sections():
    result = format_reflection(_REFLECTION_OK)
    for section in ("Strengths", "Weaknesses", "Patterns", "Recommendations"):
        assert section in result, f"Missing section: {section}"


def test_format_reflection_empty_sections_omitted():
    reflection = {**_REFLECTION_OK, "patterns": [], "weaknesses": []}
    result = format_reflection(reflection)
    assert "Patterns" not in result
    assert "Weaknesses" not in result
    assert "Strengths" in result


def test_format_reflection_error():
    result = format_reflection({"error": "Not found"})
    assert "❌" in result


# --- format_error ---


def test_format_error_has_cross():
    assert "❌" in format_error("Something failed")


def test_format_error_includes_message():
    assert "Something failed" in format_error("Something failed")


# --- UNAUTHORIZED_MESSAGE ---


def test_unauthorized_message_has_cross():
    assert "❌" in UNAUTHORIZED_MESSAGE
