from unittest.mock import AsyncMock, MagicMock, patch

import app.postgres as pg
from app.postgres import (
    get_recent_decisions,
    get_today_approved_exposure,
    is_reachable,
    persist_decision,
)


def _mock_pool(fetchrow_result=None, fetch_result=None):
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result or {"total_exposure": 0})
    conn.fetch = AsyncMock(return_value=fetch_result or [])
    conn.fetchval = AsyncMock(return_value=1)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


# ── persist_decision ─────────────────────────────────────────────────────────


async def test_persist_decision_executes_insert():
    pool, conn = _mock_pool()
    await persist_decision(
        pool, "decision_1", "pred_1", True, "approved", 3, 55, 120,
        {"confidence": True}
    )
    conn.execute.assert_called_once()


async def test_persist_decision_with_no_sizing():
    pool, conn = _mock_pool()
    await persist_decision(
        pool, "decision_2", "pred_2", False, "denied", None, None, 50,
        {"confidence": False}
    )
    conn.execute.assert_called_once()


async def test_persist_decision_silently_handles_db_error():
    pool, conn = _mock_pool()
    conn.execute = AsyncMock(side_effect=Exception("DB error"))
    # Should not raise
    await persist_decision(
        pool, "d", "p", False, "denied", None, None, 0, {}
    )


# ── get_today_approved_exposure ───────────────────────────────────────────────


async def test_get_today_approved_exposure_returns_value():
    pool, _ = _mock_pool(fetchrow_result={"total_exposure": 5_000})
    result = await get_today_approved_exposure(pool)
    assert result == 5_000


async def test_get_today_approved_exposure_returns_zero_on_error():
    pool, conn = _mock_pool()
    conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))
    result = await get_today_approved_exposure(pool)
    assert result == 0


async def test_get_today_approved_exposure_returns_zero_when_none():
    pool, _ = _mock_pool(fetchrow_result={"total_exposure": 0})
    result = await get_today_approved_exposure(pool)
    assert result == 0


# ── get_recent_decisions ──────────────────────────────────────────────────────


async def test_get_recent_decisions_returns_list():
    rows = [MagicMock(), MagicMock()]
    rows[0].__iter__ = MagicMock(return_value=iter([("approved", True)]))
    rows[1].__iter__ = MagicMock(return_value=iter([("approved", False)]))
    # Use dict-style rows (asyncpg Record-like)
    pool, conn = _mock_pool()
    conn.fetch = AsyncMock(return_value=[
        {"approved": True},
        {"approved": False},
    ])
    result = await get_recent_decisions(pool, limit=10)
    assert len(result) == 2
    assert result[0]["approved"] is True
    assert result[1]["approved"] is False


async def test_get_recent_decisions_returns_empty_on_error():
    pool, conn = _mock_pool()
    conn.fetch = AsyncMock(side_effect=Exception("DB error"))
    result = await get_recent_decisions(pool)
    assert result == []


# ── is_reachable ──────────────────────────────────────────────────────────────


async def test_is_reachable_true_with_pool():
    pool, _ = _mock_pool()
    assert await is_reachable(pool) is True


async def test_is_reachable_false_when_pool_is_none():
    assert await is_reachable(None) is False


async def test_is_reachable_false_on_db_error():
    pool, conn = _mock_pool()
    conn.fetchval = AsyncMock(side_effect=Exception("DB error"))
    assert await is_reachable(pool) is False


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

