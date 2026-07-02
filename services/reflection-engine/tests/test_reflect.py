import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_REFLECTION_ID_RE = re.compile(r"^reflection_\d{8}T\d{6}_[0-9a-f]{8}$")

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)

_MOCK_SUMMARY = {
    "analysis_id": "analysis_20260101T000000_aabbccdd",
    "analyzed_at": _TS,
    "time_range_start": _TS,
    "time_range_end": _TS,
    "predictions_analyzed": 10,
    "outcomes_available": 5,
    "accuracy": 0.80,
    "average_confidence": 0.78,
    "average_execution_ms": 90_000.0,
    "model_breakdown": {"qwen3:8b": 10},
    "category_breakdown": {"finance": 10},
    "observations": [
        "10 prediction(s) analyzed.",
        "Accuracy is 80.0% across 5 resolved prediction(s).",
    ],
}

_REQUIRED_FIELDS = (
    "reflection_id",
    "analysis_id",
    "generated_at",
    "strengths",
    "weaknesses",
    "patterns",
    "recommendations",
)

_VALID_REQUEST = {"analysis_id": "analysis_20260101T000000_aabbccdd"}


def _mock_fetch(summary=_MOCK_SUMMARY):
    return patch("app.postgres.fetch_summary", new=AsyncMock(return_value=summary))


def _mock_recent(summaries=None):
    return patch(
        "app.postgres.fetch_recent_summaries",
        new=AsyncMock(return_value=[_MOCK_SUMMARY] if summaries is None else summaries),
    )


def _mock_persist():
    return patch("app.postgres.persist_reflection", new=AsyncMock(return_value=None))


# --- response structure ---


def test_reflect_returns_200():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        response = client.post("/reflect", json=_VALID_REQUEST)
    assert response.status_code == 200


def test_reflect_returns_all_required_fields():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        response = client.post("/reflect", json=_VALID_REQUEST)
    data = response.json()
    for field in _REQUIRED_FIELDS:
        assert field in data, f"Missing field: {field}"


def test_analysis_id_echoed_in_response():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        response = client.post("/reflect", json=_VALID_REQUEST)
    assert response.json()["analysis_id"] == _VALID_REQUEST["analysis_id"]


# --- reflection_id ---


def test_reflection_id_matches_format():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        response = client.post("/reflect", json=_VALID_REQUEST)
    rid = response.json()["reflection_id"]
    assert _REFLECTION_ID_RE.match(rid), f"reflection_id '{rid}' does not match format"


def test_reflection_ids_unique_across_calls():
    ids = set()
    for _ in range(5):
        with _mock_fetch(), _mock_recent(), _mock_persist():
            response = client.post("/reflect", json=_VALID_REQUEST)
        ids.add(response.json()["reflection_id"])
    assert len(ids) == 5


# --- field types ---


def test_strengths_is_list():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        data = client.post("/reflect", json=_VALID_REQUEST).json()
    assert isinstance(data["strengths"], list)


def test_weaknesses_is_list():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        data = client.post("/reflect", json=_VALID_REQUEST).json()
    assert isinstance(data["weaknesses"], list)


def test_patterns_is_list():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        data = client.post("/reflect", json=_VALID_REQUEST).json()
    assert isinstance(data["patterns"], list)


def test_recommendations_is_list():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        data = client.post("/reflect", json=_VALID_REQUEST).json()
    assert isinstance(data["recommendations"], list)


def test_recommendations_non_empty():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        data = client.post("/reflect", json=_VALID_REQUEST).json()
    assert len(data["recommendations"]) > 0


# --- content produced from mock summary ---


def test_strengths_produced_for_high_accuracy_summary():
    with _mock_fetch(), _mock_recent(), _mock_persist():
        data = client.post("/reflect", json=_VALID_REQUEST).json()
    # _MOCK_SUMMARY has accuracy=0.80 with 5 outcomes → should produce at least one strength
    assert len(data["strengths"]) > 0


def test_weaknesses_produced_when_applicable():
    # Summary with no outcomes → weakness expected
    no_outcome_summary = {**_MOCK_SUMMARY, "outcomes_available": 0, "accuracy": None}
    with _mock_fetch(no_outcome_summary), _mock_recent([no_outcome_summary]), _mock_persist():
        data = client.post("/reflect", json=_VALID_REQUEST).json()
    assert len(data["weaknesses"]) > 0


# --- validation ---


def test_unknown_analysis_id_returns_404():
    with patch("app.postgres.fetch_summary", new=AsyncMock(return_value=None)):
        response = client.post("/reflect", json={"analysis_id": "analysis_does_not_exist"})
    assert response.status_code == 404


def test_missing_analysis_id_returns_422():
    response = client.post("/reflect", json={})
    assert response.status_code == 422


# --- persistence ---


def test_persist_called_once_per_reflection():
    mock = AsyncMock(return_value=None)
    with _mock_fetch(), _mock_recent(), patch("app.postgres.persist_reflection", new=mock):
        client.post("/reflect", json=_VALID_REQUEST)
    mock.assert_called_once()


def test_persist_receives_reflection_result():
    mock = AsyncMock(return_value=None)
    with _mock_fetch(), _mock_recent(), patch("app.postgres.persist_reflection", new=mock):
        client.post("/reflect", json=_VALID_REQUEST)
    reflection = mock.call_args[0][0]
    assert hasattr(reflection, "reflection_id")
    assert hasattr(reflection, "analysis_id")
    assert hasattr(reflection, "strengths")
    assert hasattr(reflection, "weaknesses")
    assert hasattr(reflection, "patterns")
    assert hasattr(reflection, "recommendations")


def test_persist_not_called_when_analysis_not_found():
    mock = AsyncMock(return_value=None)
    with (
        patch("app.postgres.fetch_summary", new=AsyncMock(return_value=None)),
        patch("app.postgres.persist_reflection", new=mock),
    ):
        client.post("/reflect", json={"analysis_id": "analysis_does_not_exist"})
    mock.assert_not_called()


# --- health ---


def test_health_ok():
    with patch("app.postgres.is_reachable", new=AsyncMock(return_value=True)):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["postgres"] is True
    assert "version" in data


def test_health_degraded_when_postgres_unreachable():
    with patch("app.postgres.is_reachable", new=AsyncMock(return_value=False)):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["postgres"] is False
