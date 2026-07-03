from unittest.mock import AsyncMock, MagicMock

from app.commands import (
    handle_analyze,
    handle_predict,
    handle_reflect,
    handle_status,
    is_authorized,
)
from app.formatter import UNAUTHORIZED_MESSAGE

_ALLOWED_IDS = [111111111111111111, 222222222222222222]

_ANALYSIS_RESULT = {
    "analysis_id": "analysis_20260101T000000_aabbccdd",
    "predictions_analyzed": 5,
    "outcomes_available": 0,
    "accuracy": None,
    "average_confidence": 0.70,
    "time_range": "all time",
    "observations": ["5 prediction(s) analyzed."],
}

_REFLECTION_RESULT = {
    "reflection_id": "reflection_20260101T000000_aabbccdd",
    "analysis_id": "analysis_20260101T000000_aabbccdd",
    "strengths": ["High confidence."],
    "weaknesses": ["Low volume."],
    "patterns": [],
    "recommendations": ["Collect more data."],
}


def _settings(allowed_ids=_ALLOWED_IDS):
    s = MagicMock()
    s.allowed_user_ids = list(allowed_ids)
    s.ollama_url = "http://ollama:11434"
    s.searxng_url = "http://searxng:8080"
    return s


def _pred_client(health=None, predict=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or {"status": "ok"})
    c.predict = AsyncMock(return_value=predict or {
        "prediction": "Yes",
        "confidence": 0.75,
        "reasoning": "Strong data supports this.",
    })
    return c


def _learn_client(health=None, analyze=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or {"status": "ok", "postgres": True})
    c.analyze = AsyncMock(return_value=analyze or _ANALYSIS_RESULT)
    return c


def _reflect_client(health=None, reflect=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or {"status": "ok", "postgres": True})
    c.reflect = AsyncMock(return_value=reflect or _REFLECTION_RESULT)
    return c


def _http(reachable=True):
    response = MagicMock()
    response.status_code = 200 if reachable else 500
    http = MagicMock()
    http.get = AsyncMock(return_value=response)
    return http


# ── authorization ──────────────────────────────────────────────────────────


def test_authorized_user_allowed():
    assert is_authorized(_ALLOWED_IDS[0], _ALLOWED_IDS) is True


def test_unauthorized_user_denied():
    assert is_authorized(999999999999999999, _ALLOWED_IDS) is False


def test_empty_allowlist_denies_everyone():
    assert is_authorized(_ALLOWED_IDS[0], []) is False


def test_all_allowed_users_pass():
    for uid in _ALLOWED_IDS:
        assert is_authorized(uid, _ALLOWED_IDS) is True


# ── handle_status ──────────────────────────────────────────────────────────


async def test_handle_status_returns_string():
    result = await handle_status(
        _pred_client(), _learn_client(), _reflect_client(), _http(), _settings()
    )
    assert isinstance(result, str)


async def test_handle_status_contains_platform_heading():
    result = await handle_status(
        _pred_client(), _learn_client(), _reflect_client(), _http(), _settings()
    )
    assert "Platform Status" in result


async def test_handle_status_includes_all_services():
    result = await handle_status(
        _pred_client(), _learn_client(), _reflect_client(), _http(), _settings()
    )
    for service in ("Prediction API", "Learning Engine", "Reflection Engine"):
        assert service in result, f"Missing: {service}"


async def test_handle_status_degraded_service_shows_cross():
    result = await handle_status(
        _pred_client(health={"status": "degraded"}),
        _learn_client(),
        _reflect_client(),
        _http(),
        _settings(),
    )
    assert "❌" in result


# ── handle_predict ─────────────────────────────────────────────────────────


async def test_handle_predict_success_contains_prediction():
    result = await handle_predict("Will it rain?", "weather", _ALLOWED_IDS[0], _pred_client())
    assert "Yes" in result


async def test_handle_predict_error_shows_cross():
    client = _pred_client(predict={"error": "Ollama unreachable"})
    result = await handle_predict("Will it rain?", "weather", _ALLOWED_IDS[0], client)
    assert "❌" in result


async def test_handle_predict_forwards_question_and_category():
    mock_client = _pred_client()
    await handle_predict("Will the market close up?", "finance", _ALLOWED_IDS[0], mock_client)
    mock_client.predict.assert_called_once_with("Will the market close up?", "finance")


# ── handle_analyze ─────────────────────────────────────────────────────────


async def test_handle_analyze_success_contains_analysis_heading():
    result = await handle_analyze(_ALLOWED_IDS[0], _learn_client())
    assert "Analysis" in result


async def test_handle_analyze_error_shows_cross():
    client = _learn_client(analyze={"error": "Engine unavailable"})
    result = await handle_analyze(_ALLOWED_IDS[0], client)
    assert "❌" in result


# ── handle_reflect ─────────────────────────────────────────────────────────


async def test_handle_reflect_success_contains_reflection():
    result = await handle_reflect(_ALLOWED_IDS[0], _learn_client(), _reflect_client())
    assert "Reflection" in result


async def test_handle_reflect_analysis_error_propagates():
    client = _learn_client(analyze={"error": "No history"})
    result = await handle_reflect(_ALLOWED_IDS[0], client, _reflect_client())
    assert "❌" in result
    assert "No history" in result


async def test_handle_reflect_uses_analysis_id_from_analyze():
    learning = _learn_client()
    reflection = _reflect_client()
    await handle_reflect(_ALLOWED_IDS[0], learning, reflection)
    reflection.reflect.assert_called_once_with("analysis_20260101T000000_aabbccdd")


async def test_handle_reflect_missing_analysis_id_returns_error():
    # analyze returns a result with no analysis_id key
    learning = _learn_client(analyze={"predictions_analyzed": 0})
    result = await handle_reflect(_ALLOWED_IDS[0], learning, _reflect_client())
    assert "❌" in result
