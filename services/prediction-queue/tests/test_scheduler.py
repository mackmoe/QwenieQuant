"""
Tests for app/scheduler.py.

run_refresh() is tested directly; scheduler_loop() is mocked in route tests.
The autouse fixture resets both queue and scheduler state before every test.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import queue as qm
from app import scheduler as scheduler_module
from app.config import Settings
from app.models import AddOpportunity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    defaults = dict(
        postgres_url="postgresql://x/x",
        queue_max_size=100,
        queue_priority_weight=0.70,
        queue_wait_weight=0.30,
        queue_refresh_seconds=1,
        queue_expiration_buffer_seconds=0,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _opp(market_id: str, score: float, expiration_time=None) -> AddOpportunity:
    return AddOpportunity(
        market_id=market_id,
        ticker=market_id,
        priority_score=score,
        expiration_time=expiration_time,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_state():
    qm._set_state([])
    scheduler_module._set_state(None)
    yield
    qm._set_state([])
    scheduler_module._set_state(None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunRefresh:
    async def test_refresh_sets_last_refresh_timestamp(self):
        await scheduler_module.run_refresh(None, _settings())
        assert scheduler_module.get_last_refresh() is not None

    async def test_refresh_timestamp_is_recent(self):
        before = _now()
        await scheduler_module.run_refresh(None, _settings())
        after = _now()
        ts = scheduler_module.get_last_refresh()
        assert before <= ts <= after

    async def test_refresh_expires_stale_entries(self):
        s = _settings(queue_expiration_buffer_seconds=0)
        past = _now() - timedelta(hours=1)
        qm.add_or_update([_opp("MKT-1", 50.0, expiration_time=past)], s)
        assert qm.queue_size() == 1
        await scheduler_module.run_refresh(None, s)
        assert qm.queue_size() == 0

    async def test_refresh_recalculates_priorities(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 50.0)], s)
        await scheduler_module.run_refresh(None, s)
        assert qm.queue_size() == 1

    async def test_refresh_calls_postgres_upsert_when_pool_provided(self):
        s = _settings()
        mock_pool = MagicMock()
        with patch(
            "app.scheduler.postgres_module.upsert_entries",
            new_callable=AsyncMock,
        ) as mock_upsert:
            await scheduler_module.run_refresh(mock_pool, s)
            mock_upsert.assert_called_once()

    async def test_refresh_skips_postgres_upsert_when_pool_is_none(self):
        s = _settings()
        with patch(
            "app.scheduler.postgres_module.upsert_entries",
            new_callable=AsyncMock,
        ) as mock_upsert:
            await scheduler_module.run_refresh(None, s)
            mock_upsert.assert_not_called()

    async def test_refresh_postgres_failure_does_not_raise(self):
        s = _settings()
        mock_pool = MagicMock()
        with patch(
            "app.scheduler.postgres_module.upsert_entries",
            new_callable=AsyncMock,
            side_effect=Exception("db down"),
        ):
            await scheduler_module.run_refresh(mock_pool, s)
        assert scheduler_module.get_last_refresh() is not None

    async def test_refresh_returns_expired_and_updated_counts(self):
        s = _settings(queue_expiration_buffer_seconds=0)
        past = _now() - timedelta(hours=1)
        qm.add_or_update(
            [_opp("MKT-1", 50.0, expiration_time=past), _opp("MKT-2", 70.0)],
            s,
        )
        expired, updated = await scheduler_module.run_refresh(None, s)
        assert expired == 1
        assert updated == 1  # MKT-2 remains active
