import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_VALID_REQUEST = {
    "question": "Will the S&P 500 close above 5000 by end of March 2025?",
    "category": "finance",
    "options": ["Yes", "No"],
}

_MOCK_LLM_RESPONSE = json.dumps(
    {
        "prediction": "Yes",
        "confidence": 0.72,
        "reasoning": (
            "Recent market trends show upward momentum. "
            "Historical Q1 patterns are favorable for this threshold."
        ),
        "key_factors": [
            "upward momentum",
            "historical Q1 patterns",
            "current level near target",
        ],
    }
)


def _mock_chat(response_json: str):
    return patch("app.ollama.chat", new=AsyncMock(return_value=(response_json, None)))


def test_predict_success():
    with _mock_chat(_MOCK_LLM_RESPONSE):
        response = client.post("/predict", json=_VALID_REQUEST)
    assert response.status_code == 200
    data = response.json()
    assert data["prediction"] == "Yes"
    assert 0.0 <= data["confidence"] <= 1.0
    assert len(data["reasoning"]) > 0
    assert isinstance(data["key_factors"], list)
    assert "prediction_id" in data
    assert "created_at" in data
    assert data["model"] == "qwen3:8b"
    assert data["search_context_used"] is False


def test_predict_returns_all_required_fields():
    with _mock_chat(_MOCK_LLM_RESPONSE):
        response = client.post("/predict", json=_VALID_REQUEST)
    data = response.json()
    for field in ("prediction_id", "question", "prediction", "confidence",
                  "reasoning", "key_factors", "model", "created_at"):
        assert field in data, f"Missing field: {field}"


def test_predict_with_context_and_resolution_date():
    request = {
        **_VALID_REQUEST,
        "context": {"current_value": 4900, "trend": "upward"},
        "resolution_date": "2025-03-31",
        "market_id": "market-abc-123",
    }
    with _mock_chat(_MOCK_LLM_RESPONSE):
        response = client.post("/predict", json=request)
    assert response.status_code == 200


def test_predict_invalid_category():
    bad = {**_VALID_REQUEST, "category": "astrology"}
    response = client.post("/predict", json=bad)
    assert response.status_code == 422


def test_predict_question_too_short():
    bad = {**_VALID_REQUEST, "question": "Short?"}
    response = client.post("/predict", json=bad)
    assert response.status_code == 422


def test_predict_question_missing():
    bad = {"category": "finance"}
    response = client.post("/predict", json=bad)
    assert response.status_code == 422


def test_predict_invalid_llm_json():
    with _mock_chat("this is not json at all"):
        response = client.post("/predict", json=_VALID_REQUEST)
    assert response.status_code == 502


def test_predict_llm_missing_required_fields():
    incomplete = json.dumps({"prediction": "Yes"})
    with _mock_chat(incomplete):
        response = client.post("/predict", json=_VALID_REQUEST)
    assert response.status_code == 502


def test_predict_llm_returns_invalid_option():
    bad_prediction = json.dumps(
        {
            "prediction": "Maybe",
            "confidence": 0.5,
            "reasoning": "Hard to say.",
            "key_factors": ["uncertainty"],
        }
    )
    with _mock_chat(bad_prediction):
        response = client.post("/predict", json=_VALID_REQUEST)
    assert response.status_code == 502


def test_predict_confidence_out_of_range():
    bad_confidence = json.dumps(
        {
            "prediction": "Yes",
            "confidence": 1.5,
            "reasoning": "Very confident.",
            "key_factors": ["factor"],
        }
    )
    with _mock_chat(bad_confidence):
        response = client.post("/predict", json=_VALID_REQUEST)
    assert response.status_code == 502


def test_predict_ollama_unreachable():
    with patch(
        "app.ollama.chat",
        new=AsyncMock(side_effect=Exception("connection refused")),
    ):
        response = client.post("/predict", json=_VALID_REQUEST)
    assert response.status_code == 503


def test_predict_custom_options():
    request = {
        "question": "Which team will win the championship this season?",
        "category": "sports",
        "options": ["Team A", "Team B", "Draw"],
    }
    mock_response = json.dumps(
        {
            "prediction": "Team A",
            "confidence": 0.6,
            "reasoning": "Team A has the stronger record.",
            "key_factors": ["win rate", "recent form"],
        }
    )
    with _mock_chat(mock_response):
        response = client.post("/predict", json=request)
    assert response.status_code == 200
    assert response.json()["prediction"] == "Team A"
