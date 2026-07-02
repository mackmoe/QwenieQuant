import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_ANALYSIS_ID_RE = re.compile(r"^analysis_\d{8}T\d{6}_[0-9a-f]{8}$")

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)

_MOCK_PREDICTIONS = [
    {
        "prediction_id": "pred_20260101T000000_aabbccdd",
        "question": "Will X happen by end of Q1?",
        "category": "finance",
        "created_at": _TS,
        "prediction": "Yes",
        "confidence": 0.75,
        "model": "qwen3:8b",
        "execution_ms": 120000,
        "outcome": None,
    }
]

_REQUIRED_FIELDS = (
    "analysis_id", "analyzed_at", "time_range",
    "predictions_analyzed", "outcomes_available",
    "accuracy", "average_confidence", "average_execution_ms",
    "model_breakdown", "category_breakdown", "observations",
)


def _mock_fetch(predictions=None):
    return patch(
        "app.postgres.fetch_predictions",
        new=AsyncMock(return_value=_MOCK_PREDICTIONS if predictions is None else predictions),
    )


def _mock_persist():
    return patch("app.postgres.persist_summary", new=AsyncMock(return_value=None))


# --- response structure ---


def test_analyze_returns_200():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.status_code == 200


def test_analyze_returns_all_required_fields():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    data = response.json()
    for field in _REQUIRED_FIELDS:
        assert field in data, f"Missing field: {field}"


def test_analyze_time_range_string_present():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert isinstance(response.json()["time_range"], str)
    assert len(response.json()["time_range"]) > 0


# --- analysis_id ---


def test_analysis_id_matches_format():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    analysis_id = response.json()["analysis_id"]
    assert _ANALYSIS_ID_RE.match(analysis_id), (
        f"analysis_id '{analysis_id}' does not match expected format"
    )


def test_analysis_ids_unique_across_calls():
    ids = set()
    for _ in range(5):
        with _mock_fetch(), _mock_persist():
            response = client.post("/analyze", json={})
        ids.add(response.json()["analysis_id"])
    assert len(ids) == 5


# --- counts and aggregates ---


def test_predictions_analyzed_count():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.json()["predictions_analyzed"] == 1


def test_outcomes_available_count_no_outcomes():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.json()["outcomes_available"] == 0


def test_accuracy_null_when_no_outcomes():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.json()["accuracy"] is None


def test_accuracy_computed_when_outcomes_present():
    preds_with_outcome = [{**_MOCK_PREDICTIONS[0], "outcome": "Yes"}]
    with _mock_fetch(preds_with_outcome), _mock_persist():
        response = client.post("/analyze", json={})
    data = response.json()
    assert data["outcomes_available"] == 1
    assert data["accuracy"] == pytest.approx(1.0)


def test_average_confidence_computed():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.json()["average_confidence"] == pytest.approx(0.75)


def test_average_execution_ms_computed():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.json()["average_execution_ms"] == pytest.approx(120000.0)


def test_model_breakdown():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.json()["model_breakdown"] == {"qwen3:8b": 1}


def test_category_breakdown():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.json()["category_breakdown"] == {"finance": 1}


# --- observations ---


def test_observations_is_list():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert isinstance(response.json()["observations"], list)


def test_observations_non_empty():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert len(response.json()["observations"]) > 0


def test_empty_history_observation():
    with _mock_fetch([]), _mock_persist():
        response = client.post("/analyze", json={})
    data = response.json()
    assert data["predictions_analyzed"] == 0
    assert "No prediction history" in data["observations"][0]


# --- persistence ---


def test_persist_called_once_per_analysis():
    mock = AsyncMock(return_value=None)
    with _mock_fetch(), patch("app.postgres.persist_summary", new=mock):
        client.post("/analyze", json={})
    mock.assert_called_once()


def test_persist_receives_analysis_summary():
    mock = AsyncMock(return_value=None)
    with _mock_fetch(), patch("app.postgres.persist_summary", new=mock):
        client.post("/analyze", json={})
    args = mock.call_args[0]
    summary = args[0]
    assert hasattr(summary, "analysis_id")
    assert hasattr(summary, "predictions_analyzed")


# --- request validation ---


def test_limit_too_low_rejected():
    response = client.post("/analyze", json={"limit": 0})
    assert response.status_code == 422


def test_limit_too_high_rejected():
    response = client.post("/analyze", json={"limit": 99999})
    assert response.status_code == 422


def test_explicit_limit_accepted():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={"limit": 50})
    assert response.status_code == 200


def test_empty_body_uses_defaults():
    with _mock_fetch(), _mock_persist():
        response = client.post("/analyze", json={})
    assert response.status_code == 200


