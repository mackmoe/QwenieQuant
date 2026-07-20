import asyncio
import re
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import PredictionRequest, PredictionResponse
import app.postgres as pg

_PREDICTION_ID_RE = re.compile(r"^pred_\d{8}T\d{6}_[0-9a-f]{8}$")


def _request():
    return PredictionRequest(
        question="Will Bitcoin exceed $100,000 by end of March 2025?",
        category="Finance",
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


def test_fetch_historical_context_empty_shape_without_pool():
    pg._pool = None
    result = asyncio.run(pg.fetch_historical_context("Sports", "KXMLB-26-X"))
    assert result == {
        "category_stats": None,
        "series_stats": None,
        "lessons": [],
        "exemplars": [],
    }


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


# ---------------------------------------------------------------------------
# _create_pool_with_retry (startup race resilience)
# ---------------------------------------------------------------------------


async def test_create_pool_with_retry_succeeds_first_try():
    mock_pool = MagicMock()
    with patch("app.postgres.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool) as mock_create:
        result = await pg._create_pool_with_retry("postgresql://x", min_size=1)
    assert result is mock_pool
    mock_create.assert_awaited_once()


async def test_create_pool_with_retry_recovers_after_transient_failure():
    mock_pool = MagicMock()
    mock_create = AsyncMock(side_effect=[Exception("the database system is starting up"), mock_pool])
    with (
        patch("app.postgres.asyncpg.create_pool", mock_create),
        patch("app.postgres.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        result = await pg._create_pool_with_retry("postgresql://x", min_size=1)
    assert result is mock_pool
    assert mock_create.await_count == 2
    mock_sleep.assert_awaited_once()


async def test_create_pool_with_retry_raises_after_exhausting_attempts():
    mock_create = AsyncMock(side_effect=Exception("still down"))
    with (
        patch("app.postgres.asyncpg.create_pool", mock_create),
        patch("app.postgres.asyncio.sleep", new_callable=AsyncMock),
    ):
        raised = None
        try:
            await pg._create_pool_with_retry("postgresql://x", min_size=1)
        except Exception as exc:
            raised = exc
    assert raised is not None and str(raised) == "still down"
    assert mock_create.await_count == pg._POOL_CONNECT_MAX_ATTEMPTS


async def test_create_pool_with_retry_uses_exponential_backoff():
    mock_create = AsyncMock(side_effect=[Exception("a"), Exception("b"), MagicMock()])
    with (
        patch("app.postgres.asyncpg.create_pool", mock_create),
        patch("app.postgres.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        await pg._create_pool_with_retry("postgresql://x")
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [2.0, 4.0]


async def test_startup_uses_retry_wrapper():
    import app.postgres as pg_mod
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock(execute=AsyncMock()))
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("app.postgres.get_settings", return_value=type("S", (), {"postgres_url": "postgresql://x"})()),
        patch("app.postgres._create_pool_with_retry", new_callable=AsyncMock, return_value=mock_pool) as mock_retry,
    ):
        await pg_mod.startup()
    mock_retry.assert_awaited_once()
    pg_mod._pool = None
