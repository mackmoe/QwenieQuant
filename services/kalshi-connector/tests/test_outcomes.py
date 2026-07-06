"""
Tests for app/outcomes.py.

All external dependencies (postgres, Kalshi, Learning Engine) are mocked.
No live connections.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.client import MarketNotFoundError
from app.config import Settings
from app.markets import Market
from app.outcomes import _determine_correctness, run_poll


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    defaults = dict(
        kalshi_api_key="key",
        kalshi_environment="demo",
        postgres_url="postgresql://x/x",
        outcome_collection_enabled=True,
        outcome_poll_seconds=300,
        learning_engine_url="http://mock-learning:8001",
        http_timeout=30.0,
        max_retries=0,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _pred(prediction_id="pred_001", market_id="MKT-1", predicted_value="Yes", **kw) -> dict:
    return {
        "prediction_id": prediction_id,
        "market_id": market_id,
        "question": "Will it happen?",
        "predicted_value": predicted_value,
        "confidence": 0.80,
        **kw,
    }


def _market(result=None, status="active", close_time=None) -> Market:
    return Market(
        ticker="MKT-1",
        title="Will it happen?",
        status=status,
        yes_bid=45,
        yes_ask=55,
        result=result,
        close_time=close_time,
    )


# ---------------------------------------------------------------------------
# Tests: _determine_correctness
# ---------------------------------------------------------------------------


class TestDetermineCorrectness:
    def test_yes_matches_yes(self):
        assert _determine_correctness("Yes", "yes") is True

    def test_no_matches_no(self):
        assert _determine_correctness("No", "no") is True

    def test_yes_does_not_match_no(self):
        assert _determine_correctness("Yes", "no") is False

    def test_case_insensitive(self):
        assert _determine_correctness("YES", "yes") is True

    def test_empty_predicted_returns_none(self):
        assert _determine_correctness("", "yes") is None

    def test_empty_actual_returns_none(self):
        assert _determine_correctness("Yes", "") is None

    def test_whitespace_is_stripped(self):
        assert _determine_correctness("  yes  ", "yes") is True


# ---------------------------------------------------------------------------
# Tests: run_poll
# ---------------------------------------------------------------------------


class TestRunPoll:
    async def test_empty_unresolved_returns_zero(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        with patch(
            "app.outcomes.postgres_module.get_unresolved_predictions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            checked, stored = await run_poll(pool, client, http, s)

        assert checked == 0
        assert stored == 0

    async def test_open_market_skipped(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=[_pred()],
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result=None),
            ),
        ):
            checked, stored = await run_poll(pool, client, http, s)

        assert checked == 1
        assert stored == 0

    async def test_resolved_market_outcome_stored(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=[_pred(predicted_value="Yes")],
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result="yes"),
            ),
            patch(
                "app.outcomes.postgres_module.persist_outcome",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_persist,
            patch("app.outcomes._trigger_learning", new_callable=AsyncMock),
        ):
            checked, stored = await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        assert checked == 1
        assert stored == 1
        mock_persist.assert_called_once()

    async def test_correct_prediction_recorded(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        captured = {}

        async def _fake_persist(p, **kwargs):
            captured.update(kwargs)
            return True

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=[_pred(predicted_value="Yes")],
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result="yes"),
            ),
            patch("app.outcomes.postgres_module.persist_outcome", _fake_persist),
            patch("app.outcomes._trigger_learning", new_callable=AsyncMock),
        ):
            await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        assert captured["prediction_correct"] is True

    async def test_incorrect_prediction_recorded(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        captured = {}

        async def _fake_persist(p, **kwargs):
            captured.update(kwargs)
            return True

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=[_pred(predicted_value="No")],
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result="yes"),
            ),
            patch("app.outcomes.postgres_module.persist_outcome", _fake_persist),
            patch("app.outcomes._trigger_learning", new_callable=AsyncMock),
        ):
            await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        assert captured["prediction_correct"] is False

    async def test_learning_triggered_once_on_new_outcome(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()
        mock_trigger = AsyncMock()

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=[_pred()],
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result="yes"),
            ),
            patch(
                "app.outcomes.postgres_module.persist_outcome",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("app.outcomes._trigger_learning", mock_trigger),
        ):
            await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        mock_trigger.assert_called_once()

    async def test_learning_not_triggered_when_outcome_already_exists(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()
        mock_trigger = AsyncMock()

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=[_pred()],
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result="yes"),
            ),
            patch(
                "app.outcomes.postgres_module.persist_outcome",
                new_callable=AsyncMock,
                return_value=False,  # ON CONFLICT DO NOTHING
            ),
            patch("app.outcomes._trigger_learning", mock_trigger),
        ):
            await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        mock_trigger.assert_not_called()

    async def test_kalshi_error_skips_prediction_continues_to_next(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        predictions = [
            _pred(prediction_id="pred_001", market_id="MKT-1"),
            _pred(prediction_id="pred_002", market_id="MKT-2"),
        ]

        call_count = 0

        async def _market_or_error(c, ticker):
            nonlocal call_count
            call_count += 1
            if ticker == "MKT-1":
                raise MarketNotFoundError("MKT-1")
            return _market(result="yes")

        mock_persist = AsyncMock(return_value=True)
        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=predictions,
            ),
            patch("app.outcomes.get_market", _market_or_error),
            patch("app.outcomes.postgres_module.persist_outcome", mock_persist),
            patch("app.outcomes._trigger_learning", new_callable=AsyncMock),
        ):
            checked, stored = await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        assert checked == 2
        assert stored == 1
        assert call_count == 2

    async def test_multiple_resolved_markets_all_stored(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        predictions = [
            _pred(prediction_id=f"pred_{i}", market_id=f"MKT-{i}")
            for i in range(3)
        ]

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=predictions,
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result="yes"),
            ),
            patch(
                "app.outcomes.postgres_module.persist_outcome",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("app.outcomes._trigger_learning", new_callable=AsyncMock),
        ):
            checked, stored = await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        assert checked == 3
        assert stored == 3

    async def test_learning_failure_does_not_stop_poll(self):
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        async def _failing_trigger(http, settings, prediction_id):
            raise Exception("learning engine down")

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=[_pred()],
            ),
            patch(
                "app.outcomes.get_market",
                new_callable=AsyncMock,
                return_value=_market(result="yes"),
            ),
            patch(
                "app.outcomes.postgres_module.persist_outcome",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("app.outcomes._trigger_learning", _failing_trigger),
        ):
            # Should not raise even though learning fails
            checked, stored = await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        assert stored == 1

    async def test_checked_and_stored_counts(self):
        """Two checked: one open (not stored), one resolved (stored)."""
        s = _settings()
        pool = MagicMock()
        client = MagicMock()
        http = MagicMock()

        predictions = [
            _pred(prediction_id="pred_open", market_id="OPEN"),
            _pred(prediction_id="pred_resolved", market_id="RESOLVED"),
        ]

        async def _market_by_ticker(c, ticker):
            if ticker == "OPEN":
                return _market(result=None)
            return _market(result="yes")

        with (
            patch(
                "app.outcomes.postgres_module.get_unresolved_predictions",
                new_callable=AsyncMock,
                return_value=predictions,
            ),
            patch("app.outcomes.get_market", _market_by_ticker),
            patch(
                "app.outcomes.postgres_module.persist_outcome",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("app.outcomes._trigger_learning", new_callable=AsyncMock),
        ):
            checked, stored = await run_poll(pool, client, http, s)
            await asyncio.sleep(0)

        assert checked == 2
        assert stored == 1
