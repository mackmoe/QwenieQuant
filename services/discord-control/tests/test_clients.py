from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.clients import LearningClient, PredictionClient, ReflectionClient, check_reachable


def _mock_http(json_data: dict = None, status_code: int = 200, raise_exc: Exception = None):
    """Return a mock httpx.AsyncClient-like object."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if raise_exc:
        response.raise_for_status.side_effect = raise_exc
    else:
        response.raise_for_status.return_value = None

    http = MagicMock()
    http.get = AsyncMock(return_value=response)
    http.post = AsyncMock(return_value=response)
    return http


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    response = MagicMock()
    response.status_code = status_code
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=MagicMock(), response=response
    )


# --- PredictionClient ---


async def test_prediction_health_ok():
    http = _mock_http({"status": "ok"})
    client = PredictionClient("http://prediction:8000", http)
    result = await client.health()
    assert result["status"] == "ok"


async def test_prediction_health_connection_error():
    http = MagicMock()
    http.get = AsyncMock(side_effect=Exception("Connection refused"))
    client = PredictionClient("http://prediction:8000", http)
    result = await client.health()
    assert "error" in result


async def test_prediction_predict_success():
    http = _mock_http({"prediction": "Yes", "confidence": 0.75, "reasoning": "X."})
    client = PredictionClient("http://prediction:8000", http)
    result = await client.predict("Will it rain?", "weather")
    assert result["prediction"] == "Yes"
    assert result["confidence"] == 0.75


async def test_prediction_predict_http_error():
    http = _mock_http(raise_exc=_http_status_error(503))
    client = PredictionClient("http://prediction:8000", http)
    result = await client.predict("Will it rain?", "weather")
    assert "error" in result
    assert "503" in result["error"]


# --- LearningClient ---


async def test_learning_health_ok():
    http = _mock_http({"status": "ok", "postgres": True})
    client = LearningClient("http://learning:8001", http)
    result = await client.health()
    assert result["postgres"] is True


async def test_learning_analyze_success():
    payload = {
        "analysis_id": "analysis_20260101T000000_aabbccdd",
        "predictions_analyzed": 5,
        "outcomes_available": 0,
        "accuracy": None,
        "average_confidence": 0.70,
        "observations": [],
    }
    http = _mock_http(payload)
    client = LearningClient("http://learning:8001", http)
    result = await client.analyze()
    assert result["analysis_id"] == "analysis_20260101T000000_aabbccdd"


# --- ReflectionClient ---


async def test_reflection_health_ok():
    http = _mock_http({"status": "ok", "postgres": True})
    client = ReflectionClient("http://reflection:8002", http)
    result = await client.health()
    assert result["status"] == "ok"


async def test_reflection_reflect_success():
    payload = {
        "reflection_id": "reflection_123",
        "strengths": ["High confidence."],
        "weaknesses": [],
        "patterns": [],
        "recommendations": ["Keep monitoring."],
    }
    http = _mock_http(payload)
    client = ReflectionClient("http://reflection:8002", http)
    result = await client.reflect("analysis_20260101T000000_aabbccdd")
    assert result["reflection_id"] == "reflection_123"


async def test_reflection_reflect_not_found_returns_error():
    http = _mock_http(raise_exc=_http_status_error(404))
    client = ReflectionClient("http://reflection:8002", http)
    result = await client.reflect("nonexistent_id")
    assert "error" in result
    assert "404" in result["error"]


# --- check_reachable ---


async def test_check_reachable_true_on_200():
    response = MagicMock()
    response.status_code = 200
    http = MagicMock()
    http.get = AsyncMock(return_value=response)
    assert await check_reachable(http, "http://ollama:11434/api/tags") is True


async def test_check_reachable_false_on_connection_error():
    http = MagicMock()
    http.get = AsyncMock(side_effect=Exception("Connection refused"))
    assert await check_reachable(http, "http://ollama:11434/api/tags") is False


async def test_check_reachable_false_on_500():
    response = MagicMock()
    response.status_code = 500
    http = MagicMock()
    http.get = AsyncMock(return_value=response)
    assert await check_reachable(http, "http://searxng:8080/healthz") is False
