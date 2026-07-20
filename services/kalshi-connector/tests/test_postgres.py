from unittest.mock import AsyncMock, MagicMock, patch

import app.postgres as pg


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


async def test_init_pool_uses_retry_wrapper():
    mock_pool = MagicMock()
    mock_conn = MagicMock(execute=AsyncMock())
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    with patch(
        "app.postgres._create_pool_with_retry", new_callable=AsyncMock, return_value=mock_pool
    ) as mock_retry:
        result = await pg.init_pool("postgresql://x")
    mock_retry.assert_awaited_once()
    assert result is mock_pool
