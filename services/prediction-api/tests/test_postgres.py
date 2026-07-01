import asyncio
import re
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import PredictionCategory, PredictionRequest, PredictionResponse
import app.postgres as pg

_PREDICTION_ID_RE = re.compile(r"^pred_\d{8}T\d{6}_[0-9a-f]{8}$")


def _request():
    return PredictionRequest(
        question="Will Bitcoin exceed $100,000 by end of March 2025?",
        category=PredictionCategory.finance,
        options=["Yes", "No"],
    )


def _response():
    return PredictionResponse(
        question="Will Bitcoin exceed $100,000 by end of March 2025?",
        prediction="Yes",
        confidence=0.72,
        reasoning="Market trends suggest upward momentum.",
        key_factors=["momentum", "institutional adoption"],
        model="qwen3:8b",
    )


# --- prediction_id ---


def test_prediction_id_matches_format():
    r = _response()
    assert _PREDICTION_ID_RE.match(r.prediction_id), (
        f"prediction_id '{r.prediction_id}' does not match expected format"
    )


def test_prediction_id_starts_with_pred():
    assert _response().prediction_id.startswith("pred_")


def test_prediction_id_contains_valid_timestamp():
    pid = _response().prediction_id
    ts_part = pid.split("_")[1]  # "YYYYMMDDTHHMMSS"
    parsed = datetime.strptime(ts_part, "%Y%m%dT%H%M%S")
    assert parsed.year >= 2024


def test_prediction_id_unique_across_100_calls():
    ids = {_response().prediction_id for _ in range(100)}
    assert len(ids) == 100


def test_prediction_id_lexicographic_order_matches_time():
    # IDs from the same second differ only in the random suffix, which is fine.
    # Verify that the timestamp portion is the dominant sort key.
    from datetime import timezone
    import time as t

    r1 = _response()
    t.sleep(1.1)  # cross a second boundary
    r2 = _response()

    assert r1.prediction_id < r2.prediction_id, (
        "Earlier prediction_id should sort before later one lexicographically"
    )


# --- graceful no-pool behaviour ---


def test_persist_is_noop_when_pool_is_none():
    pg._pool = None
    asyncio.run(pg.persist_prediction(_request(), _response(), execution_ms=4200))
    # No assertion needed — absence of exception is the assertion


def test_fetch_recent_returns_empty_when_pool_is_none():
    pg._pool = None
    result = asyncio.run(pg.fetch_recent_predictions())
    assert result == []


def test_fetch_historical_context_always_returns_empty():
    pg._pool = None
    result = asyncio.run(pg.fetch_historical_context("some question?"))
    assert result == []


# --- mock-pool behaviour ---


def _make_mock_pool():
    # conn.transaction() is a regular method returning an async CM (not a coroutine).
    # conn.execute() is a coroutine.
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.transaction.return_value = mock_tx
    mock_conn.execute = AsyncMock()

    # pool.acquire() is a regular method returning an async CM.
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire
    return mock_pool, mock_conn


def test_persist_executes_two_inserts():
    mock_pool, mock_conn = _make_mock_pool()
    pg._pool = mock_pool
    try:
        asyncio.run(pg.persist_prediction(_request(), _response(), execution_ms=4200))
        assert mock_conn.execute.call_count == 2
    finally:
        pg._pool = None


def test_persist_uses_transaction():
    mock_pool, mock_conn = _make_mock_pool()
    pg._pool = mock_pool
    try:
        asyncio.run(pg.persist_prediction(_request(), _response(), execution_ms=4200))
        mock_conn.transaction.assert_called_once()
    finally:
        pg._pool = None


def test_persist_first_insert_uses_prediction_id():
    mock_pool, mock_conn = _make_mock_pool()
    pg._pool = mock_pool
    response = _response()
    try:
        asyncio.run(pg.persist_prediction(_request(), response, execution_ms=4200))
        first_call_args = mock_conn.execute.call_args_list[0][0]
        assert response.prediction_id in first_call_args
    finally:
        pg._pool = None


def test_persist_second_insert_includes_execution_ms():
    mock_pool, mock_conn = _make_mock_pool()
    pg._pool = mock_pool
    try:
        asyncio.run(pg.persist_prediction(_request(), _response(), execution_ms=9999))
        second_call_args = mock_conn.execute.call_args_list[1][0]
        assert 9999 in second_call_args
    finally:
        pg._pool = None
