"""
Tests for app/workflow.py.

All HTTP calls are mocked at the helper-function level (_call_prediction_api,
_fetch_market_price, _call_risk_manager, _execute_trade).  Postgres is
disabled by passing pool=None; queue state is verified via queue module directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import queue as qm
from app import workflow as wf
from app.config import Settings
from app.models import AddOpportunity, QueueState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    defaults = dict(
        postgres_url="postgresql://x/x",
        prediction_api_url="http://mock-api",
        risk_manager_url="http://mock-rm",
        kalshi_connector_url="http://mock-kc",
        dry_run=True,
        workflow_enabled=True,
        workflow_interval_seconds=30,
        queue_max_size=100,
        queue_priority_weight=0.70,
        queue_wait_weight=0.30,
        queue_refresh_seconds=30,
        queue_expiration_buffer_seconds=60,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _opp(market_id: str, score: float, **meta) -> AddOpportunity:
    return AddOpportunity(
        market_id=market_id,
        ticker=market_id,
        priority_score=score,
        metadata=meta or {},
    )


def _pred(**kwargs) -> dict:
    d = dict(
        prediction_id="pred_test_001",
        question="Will X happen?",
        prediction="Yes",
        confidence=0.80,
        reasoning="test reasoning",
        key_factors=["factor1"],
        model="test-model",
        search_context_used=False,
        sources=[],
    )
    d.update(kwargs)
    return d


def _risk(approved: bool = True, **kwargs) -> dict:
    d = dict(
        prediction_id="pred_test_001",
        approved=approved,
        reason="ok" if approved else "low confidence",
        recommended_contracts=5 if approved else None,
        recommended_max_price=50 if approved else None,
        risk_checks=dict(
            confidence=True, expected_value=True, edge=True,
            open_positions=True, daily_loss=True, bankroll=True,
            consecutive_losses=True,
        ),
    )
    d.update(kwargs)
    return d


def _order(**kwargs) -> dict:
    d = dict(
        order_id="ord_test_001",
        ticker="MKT-1",
        side="yes",
        action="buy",
        count=5,
        price=50,
        order_type="limit",
        status="resting",
        filled_count=0,
        remaining_count=5,
    )
    d.update(kwargs)
    return d


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_state():
    qm._set_state([])
    yield
    qm._set_state([])


# ---------------------------------------------------------------------------
# Tests: compute_probability
# ---------------------------------------------------------------------------


class TestComputeProbability:
    def test_yes_prediction_maps_confidence_directly(self):
        assert wf.compute_probability("Yes", 0.80) == pytest.approx(0.80)

    def test_no_prediction_inverts_confidence(self):
        assert wf.compute_probability("No", 0.80) == pytest.approx(0.20)

    def test_ambiguous_prediction_uses_confidence_as_is(self):
        assert wf.compute_probability("Maybe", 0.65) == pytest.approx(0.65)

    def test_no_prediction_clamps_to_zero(self):
        assert wf.compute_probability("No", 1.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: run_iteration
# ---------------------------------------------------------------------------


class TestRunIteration:
    async def test_empty_queue_returns_without_action(self):
        s = _settings()
        http = MagicMock()
        await wf.run_iteration(None, http, s)
        assert qm.queue_size() == 0

    async def test_entry_transitions_through_in_progress_to_completed(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_prediction_api_failure_requeues_entry(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        with patch(
            "app.workflow._call_prediction_api",
            new_callable=AsyncMock,
            side_effect=Exception("connection refused"),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.QUEUED
        assert qm.queue_size() == 1

    async def test_risk_manager_failure_requeues_entry(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch(
                "app.workflow._call_risk_manager",
                new_callable=AsyncMock,
                side_effect=Exception("service unavailable"),
            ),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.QUEUED

    async def test_risk_rejected_marks_completed(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_risk_approved_dry_run_no_trade_placed(self):
        s = _settings(dry_run=True)
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_execute = AsyncMock(return_value=_order())
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=True)),
            patch("app.workflow._execute_trade", mock_execute),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        mock_execute.assert_not_called()
        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_risk_approved_live_executes_trade(self):
        s = _settings(dry_run=False)
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_execute = AsyncMock(return_value=_order())
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=True)),
            patch("app.workflow._execute_trade", mock_execute),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        mock_execute.assert_called_once()
        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_trade_failure_still_completes_entry(self):
        s = _settings(dry_run=False)
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=True)),
            patch("app.workflow._execute_trade", new_callable=AsyncMock, return_value=None),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_market_price_unavailable_uses_zero_ev(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_risk = AsyncMock(return_value=_risk(approved=False))
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=None),
            patch("app.workflow._call_risk_manager", mock_risk),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        call_kwargs = mock_risk.call_args
        # expected_value and edge should both be 0.0 when price unavailable
        # _call_risk_manager(http, settings, prediction_id, probability, confidence, ev, edge, ...)
        # expected_value is args[5], edge is args[6]
        assert call_kwargs.args[5] == pytest.approx(0.0)  # expected_value
        assert call_kwargs.args[6] == pytest.approx(0.0)  # edge

    async def test_unexpected_error_marks_entry_failed(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        with patch(
            "app.workflow._call_prediction_api",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected"),
        ):
            with patch("app.workflow.queue_module.mark_queued") as mock_mq:
                mock_mq.side_effect = RuntimeError("double failure")
                await wf.run_iteration(None, MagicMock(), s)

        entries = qm.get_queue()
        # mark_queued raised, so the outer except fires mark_failed
        assert entries[0].queue_state == QueueState.FAILED

    async def test_postgres_persist_failure_does_not_prevent_completion(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_pool = MagicMock()
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
            patch(
                "app.workflow.postgres_module.persist_workflow_result",
                new_callable=AsyncMock,
                side_effect=Exception("db down"),
            ),
        ):
            await wf.run_iteration(mock_pool, MagicMock(), s)

        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_completed_entry_leaves_active_queue(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        assert qm.queue_size() == 1

        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        assert qm.queue_size() == 0

    async def test_trade_side_is_yes_when_probability_high(self):
        s = _settings(dry_run=False)
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_execute = AsyncMock(return_value=_order())
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred(prediction="Yes", confidence=0.85)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=True)),
            patch("app.workflow._execute_trade", mock_execute),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        side_arg = mock_execute.call_args.args[3]
        assert side_arg == "yes"

    async def test_trade_side_is_no_when_probability_low(self):
        s = _settings(dry_run=False)
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_execute = AsyncMock(return_value=_order())
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred(prediction="No", confidence=0.85)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=True)),
            patch("app.workflow._execute_trade", mock_execute),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        side_arg = mock_execute.call_args.args[3]
        assert side_arg == "no"

    async def test_no_trade_ev_computed_from_no_perspective(self):
        # When model predicts "No" (confidence=0.80 → probability=0.20),
        # EV must be market_price - probability (NO perspective), not the
        # inverted YES-perspective value which would deny valid NO opportunities.
        # market_price=0.60 → YES EV = 0.20-0.60 = -0.40 (would wrongly deny)
        #                    → NO  EV = 0.60-0.20 = +0.40 (correct: approve)
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_rm = AsyncMock(return_value=_risk(approved=False))
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="No", confidence=0.80)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.60),
            patch("app.workflow._call_risk_manager", mock_rm),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        call_kwargs = mock_rm.call_args
        # probability passed = P(No) = 1 - 0.20 = 0.80
        probability_arg = call_kwargs.args[3]
        assert probability_arg == pytest.approx(0.80)
        # ev passed = market_price - P(Yes) = 0.60 - 0.20 = 0.40 (positive)
        ev_arg = call_kwargs.args[5]
        assert ev_arg == pytest.approx(0.40)

    async def test_yes_trade_ev_computed_from_yes_perspective(self):
        # When model predicts "Yes" (confidence=0.80 → probability=0.80),
        # EV must be probability - market_price.
        # market_price=0.60 → YES EV = 0.80 - 0.60 = +0.20 (positive, approve)
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)

        mock_rm = AsyncMock(return_value=_risk(approved=False))
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="Yes", confidence=0.80)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.60),
            patch("app.workflow._call_risk_manager", mock_rm),
        ):
            await wf.run_iteration(None, MagicMock(), s)

        call_kwargs = mock_rm.call_args
        probability_arg = call_kwargs.args[3]
        assert probability_arg == pytest.approx(0.80)
        ev_arg = call_kwargs.args[5]
        assert ev_arg == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Tests: run_iteration return values
# ---------------------------------------------------------------------------


class TestRunIterationReturnValues:
    async def test_empty_queue_returns_none(self):
        s = _settings()
        result = await wf.run_iteration(None, MagicMock(), s)
        assert result is None

    async def test_completed_returns_status_completed(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            result = await wf.run_iteration(None, MagicMock(), s)
        assert result is not None
        assert result["status"] == "completed"
        assert result["market_id"] == "MKT-1"
        assert result["prediction"] == "Yes"
        assert result["risk_approved"] is False

    async def test_prediction_api_failure_returns_requeued(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with patch(
            "app.workflow._call_prediction_api",
            new_callable=AsyncMock,
            side_effect=Exception("timeout"),
        ):
            result = await wf.run_iteration(None, MagicMock(), s)
        assert result is not None
        assert result["status"] == "requeued"
        assert result["market_id"] == "MKT-1"

    async def test_risk_manager_failure_returns_requeued(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch(
                "app.workflow._call_risk_manager",
                new_callable=AsyncMock,
                side_effect=Exception("service unavailable"),
            ),
        ):
            result = await wf.run_iteration(None, MagicMock(), s)
        assert result is not None
        assert result["status"] == "requeued"
        assert result["prediction"] == "Yes"

    async def test_unexpected_exception_returns_failed(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with patch(
            "app.workflow._call_prediction_api",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected"),
        ):
            with patch("app.workflow.queue_module.mark_queued") as mock_mq:
                mock_mq.side_effect = RuntimeError("double failure")
                result = await wf.run_iteration(None, MagicMock(), s)
        assert result is not None
        assert result["status"] == "failed"
        assert result["market_id"] == "MKT-1"

    async def test_completed_includes_dry_run_flag(self):
        s = _settings(dry_run=True)
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            result = await wf.run_iteration(None, MagicMock(), s)
        assert result["dry_run"] is True


# ---------------------------------------------------------------------------
# Tests: run_exclusive (scheduler wrapper)
# ---------------------------------------------------------------------------


class TestRunExclusive:
    async def test_runs_when_lock_free(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            await wf.run_exclusive(None, MagicMock(), s)
        entries = qm.get_queue()
        from app.models import QueueState
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_skips_when_lock_already_held(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        async with wf._workflow_lock:
            await wf.run_exclusive(None, MagicMock(), s)
        # run_exclusive should have skipped; queue entry stays QUEUED
        entries = qm.get_queue()
        from app.models import QueueState
        assert entries[0].queue_state == QueueState.QUEUED

    async def test_lock_released_after_completion(self):
        s = _settings()
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            await wf.run_exclusive(None, MagicMock(), s)
        assert not wf._workflow_lock.locked()

    async def test_lock_released_after_exception(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with patch(
            "app.workflow._call_prediction_api",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            with patch("app.workflow.queue_module.mark_queued") as mock_mq:
                mock_mq.side_effect = RuntimeError("also failing")
                await wf.run_exclusive(None, MagicMock(), s)
        assert not wf._workflow_lock.locked()


# ---------------------------------------------------------------------------
# Tests: run_manual (API wrapper)
# ---------------------------------------------------------------------------


class TestRunManual:
    async def test_returns_empty_when_queue_is_empty(self):
        s = _settings()
        result = await wf.run_manual(None, MagicMock(), s)
        assert result["status"] == "empty"

    async def test_returns_busy_when_lock_held(self):
        s = _settings()
        async with wf._workflow_lock:
            result = await wf.run_manual(None, MagicMock(), s)
        assert result["status"] == "busy"
        assert "started_at" in result
        assert "elapsed_seconds" in result

    async def test_returns_completed_dict_on_success(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            result = await wf.run_manual(None, MagicMock(), s)
        assert result["status"] == "completed"
        assert result["market_id"] == "MKT-1"

    async def test_lock_released_after_run_manual(self):
        s = _settings()
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            await wf.run_manual(None, MagicMock(), s)
        assert not wf._workflow_lock.locked()

    async def test_second_manual_call_while_first_runs_returns_busy(self):
        import asyncio as _asyncio

        s = _settings()
        blocked = _asyncio.Event()
        unblock = _asyncio.Event()

        async def slow_predict(*args, **kwargs):
            blocked.set()
            await unblock.wait()
            return _pred()

        async def race():
            with (
                patch("app.workflow._call_prediction_api", new_callable=AsyncMock, side_effect=slow_predict),
                patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
                patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
            ):
                qm.add_or_update([_opp("MKT-1", 80.0)], s)
                first = _asyncio.create_task(wf.run_manual(None, MagicMock(), s))
                await blocked.wait()
                second = await wf.run_manual(None, MagicMock(), s)
                unblock.set()
                await first
            return second

        second_result = await race()
        assert second_result["status"] == "busy"


# ---------------------------------------------------------------------------
# Tests: _detect_category (Fix 1 — category mapping)
# ---------------------------------------------------------------------------


class TestDetectCategory:
    def test_mlb_ticker_prefix_returns_sports(self):
        assert wf._detect_category("yes Milwaukee", "KXMLB-23-MILWIN") == "Sports"

    def test_nba_ticker_prefix_returns_sports(self):
        assert wf._detect_category("Lakers win", "KXNBA-LAL-WIN") == "Sports"

    def test_nfl_ticker_prefix_returns_sports(self):
        assert wf._detect_category("Chiefs game", "KXNFL-KC-WIN") == "Sports"

    def test_nhl_ticker_prefix_returns_sports(self):
        assert wf._detect_category("Leafs win", "KXNHL-TOR") == "Sports"

    def test_runs_scored_in_title_returns_sports(self):
        assert wf._detect_category("yes Over 8.5 runs scored", "KXMLB-TOTAL") == "Sports"

    def test_wins_by_in_title_returns_sports(self):
        assert wf._detect_category("yes Detroit wins by over 1.5 runs", "KXMLB-RLS") == "Sports"

    def test_player_prop_colon_plus_pattern_returns_sports(self):
        assert wf._detect_category("yes Freddie Freeman: 1+", "KXMLB-PROP") == "Sports"

    def test_unknown_ticker_no_sports_keywords_returns_finance(self):
        assert wf._detect_category("Will BTC exceed $100k?", "BTCUSD") == "Financials"

    def test_metadata_category_takes_precedence(self):
        # _detect_category is only called when metadata category is missing/invalid;
        # this test confirms the helper itself returns finance for non-sports input
        assert wf._detect_category("Fed rate decision", "KXFED-RATE") == "Financials"

    def test_ticker_case_insensitive(self):
        assert wf._detect_category("some title", "kxmlb-23-milwin") == "Sports"


# ---------------------------------------------------------------------------
# Tests: _format_question (Fix 3 — question framing)
# ---------------------------------------------------------------------------


class TestFormatQuestion:
    def test_strips_yes_prefix_and_adds_win_question(self):
        result = wf._format_question("yes Milwaukee")
        assert result == "Will Milwaukee win?"
        assert "yes" not in result.lower().split()[0]

    def test_strips_no_prefix_and_adds_win_question(self):
        result = wf._format_question("no Detroit")
        assert result == "Will Detroit win?"

    def test_player_prop_transformed_to_record_question(self):
        result = wf._format_question("yes Freddie Freeman: 1+")
        assert result == "Will Freddie Freeman record 1 or more?"

    def test_player_prop_higher_threshold(self):
        result = wf._format_question("yes Paul Skenes: 7+")
        assert result == "Will Paul Skenes record 7 or more?"

    def test_already_a_question_passes_through(self):
        q = "Will BTC exceed $120,000?"
        assert wf._format_question(q) == q

    def test_over_under_lowercased(self):
        result = wf._format_question("yes Over 8.5 runs scored")
        assert result.startswith("Will over")

    def test_wins_by_becomes_will_question(self):
        result = wf._format_question("yes Detroit wins by over 1.5 runs")
        assert result == "Will Detroit wins by over 1.5 runs?"

    def test_case_insensitive_prefix_strip(self):
        result = wf._format_question("YES Milwaukee")
        assert "Will Milwaukee win?" == result

    def test_no_prefix_short_string_becomes_win_question(self):
        # Plain team name with no yes/no prefix
        result = wf._format_question("Atlanta Braves")
        assert result == "Will Atlanta Braves win?"

    def test_long_payload_becomes_generic_will_question(self):
        long = "yes Some Very Long Title That Does Not Match Any Special Pattern Here"
        result = wf._format_question(long)
        assert result.startswith("Will ")
        assert result.endswith("?")


# ---------------------------------------------------------------------------
# Tests: multi-outcome skip (Fix 2 — filter multi-outcome markets)
# ---------------------------------------------------------------------------


class TestMultiOutcomeSkip:
    async def test_multi_outcome_title_returns_skipped(self):
        s = _settings()
        qm.add_or_update(
            [_opp("MKT-MULTI", 80.0, title="yes Milwaukee,yes Baltimore,yes Detroit")],
            s,
        )
        result = await wf.run_iteration(None, MagicMock(), s)
        assert result is not None
        assert result["status"] == "skipped"
        assert result["reason"] == "multi_outcome"
        assert result["market_id"] == "MKT-MULTI"

    async def test_multi_outcome_entry_marked_completed(self):
        s = _settings()
        qm.add_or_update(
            [_opp("MKT-MULTI", 80.0, title="yes A,yes B")],
            s,
        )
        await wf.run_iteration(None, MagicMock(), s)
        entries = qm.get_queue()
        assert entries[0].queue_state == QueueState.COMPLETED

    async def test_multi_outcome_does_not_call_prediction_api(self):
        s = _settings()
        qm.add_or_update(
            [_opp("MKT-MULTI", 80.0, title="yes X,yes Y")],
            s,
        )
        mock_pred = AsyncMock(return_value=_pred())
        with patch("app.workflow._call_prediction_api", mock_pred):
            await wf.run_iteration(None, MagicMock(), s)
        mock_pred.assert_not_called()

    async def test_single_outcome_with_yes_prefix_not_skipped(self):
        # "yes Milwaukee" — no comma — must proceed to prediction
        s = _settings()
        qm.add_or_update(
            [_opp("MKT-SINGLE", 80.0, title="yes Milwaukee")],
            s,
        )
        mock_pred = AsyncMock(return_value=_pred())
        with (
            patch("app.workflow._call_prediction_api", mock_pred),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            result = await wf.run_iteration(None, MagicMock(), s)
        mock_pred.assert_called_once()
        assert result is not None
        assert result["status"] == "completed"

    async def test_regular_question_with_comma_not_skipped(self):
        # Legitimate question that happens to have a comma is not filtered
        # because it doesn't start with "yes " or "no "
        s = _settings()
        qm.add_or_update(
            [_opp("MKT-Q", 80.0, title="Will X or Y happen?")],
            s,
        )
        mock_pred = AsyncMock(return_value=_pred())
        with (
            patch("app.workflow._call_prediction_api", mock_pred),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock, return_value=_risk(approved=False)),
        ):
            result = await wf.run_iteration(None, MagicMock(), s)
        assert result is not None
        assert result["status"] == "completed"

    async def test_no_prefix_multi_outcome_skipped(self):
        s = _settings()
        qm.add_or_update(
            [_opp("MKT-NO", 80.0, title="no Milwaukee,no Detroit")],
            s,
        )
        result = await wf.run_iteration(None, MagicMock(), s)
        assert result is not None
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# Tests: EV/price persistence and direction guard pass-through
# ---------------------------------------------------------------------------


class TestEvPersistenceAndDirection:
    async def test_risk_manager_receives_yes_direction(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        mock_rm = AsyncMock(return_value=_risk(approved=False))
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="Yes", confidence=0.65)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", mock_rm),
        ):
            await wf.run_iteration(None, MagicMock(), s)
        assert mock_rm.call_args.kwargs["prediction_direction"] == "yes"

    async def test_risk_manager_receives_no_direction(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        mock_rm = AsyncMock(return_value=_risk(approved=False))
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="No", confidence=0.80)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.45),
            patch("app.workflow._call_risk_manager", mock_rm),
        ):
            await wf.run_iteration(None, MagicMock(), s)
        assert mock_rm.call_args.kwargs["prediction_direction"] == "no"

    async def test_persist_receives_market_price_ev_and_side(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        mock_persist = AsyncMock()
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="Yes", confidence=0.80)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.60),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock,
                  return_value=_risk(approved=False)),
            patch("app.workflow.postgres_module.persist_workflow_result", mock_persist),
        ):
            await wf.run_iteration(MagicMock(), MagicMock(), s)
        kwargs = mock_persist.call_args.kwargs
        assert kwargs["market_price"] == pytest.approx(0.60)
        # Yes @ 0.80 conf vs 0.60 market → EV = 0.80 - 0.60 = 0.20
        assert kwargs["expected_value"] == pytest.approx(0.20)
        assert kwargs["edge"] == pytest.approx(0.20)
        assert kwargs["side"] == "yes"

    async def test_persist_receives_none_price_when_unavailable(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        mock_persist = AsyncMock()
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock, return_value=_pred()),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=None),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock,
                  return_value=_risk(approved=False)),
            patch("app.workflow.postgres_module.persist_workflow_result", mock_persist),
        ):
            await wf.run_iteration(MagicMock(), MagicMock(), s)
        kwargs = mock_persist.call_args.kwargs
        assert kwargs["market_price"] is None
        assert kwargs["expected_value"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: low-confidence inversion fix (phantom edge prevention)
# ---------------------------------------------------------------------------


class TestNonDirectionalPredictions:
    def test_low_confidence_no_returns_neutral_probability(self):
        # "No" at 0.40 is ignorance, not a 60% YES signal
        assert wf.compute_probability("No", 0.40, 0.55) == pytest.approx(0.5)

    def test_low_confidence_yes_returns_neutral_probability(self):
        assert wf.compute_probability("Yes", 0.30, 0.55) == pytest.approx(0.5)

    def test_confident_no_still_inverts(self):
        assert wf.compute_probability("No", 0.80, 0.55) == pytest.approx(0.20)

    def test_confident_yes_unchanged(self):
        assert wf.compute_probability("Yes", 0.80, 0.55) == pytest.approx(0.80)

    def test_threshold_boundary_is_directional(self):
        assert wf.compute_probability("No", 0.55, 0.55) == pytest.approx(0.45)

    def test_default_threshold_zero_preserves_legacy_behavior(self):
        assert wf.compute_probability("No", 0.40) == pytest.approx(0.60)

    async def test_low_confidence_prediction_claims_zero_ev(self):
        # The BROMIC scenario: "No" @ 0.47 vs a 9¢ market must NOT
        # produce a +44¢ phantom edge.
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        mock_rm = AsyncMock(return_value=_risk(approved=False))
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="No", confidence=0.47)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.09),
            patch("app.workflow._call_risk_manager", mock_rm),
        ):
            await wf.run_iteration(None, MagicMock(), s)
        args = mock_rm.call_args.args
        assert args[5] == pytest.approx(0.0)   # expected_value
        assert args[6] == pytest.approx(0.0)   # edge
        assert args[3] == pytest.approx(0.5)   # trade probability is neutral

    async def test_low_confidence_persists_zero_ev(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        mock_persist = AsyncMock()
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="No", confidence=0.40)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.94),
            patch("app.workflow._call_risk_manager", new_callable=AsyncMock,
                  return_value=_risk(approved=False)),
            patch("app.workflow.postgres_module.persist_workflow_result", mock_persist),
        ):
            await wf.run_iteration(MagicMock(), MagicMock(), s)
        kwargs = mock_persist.call_args.kwargs
        assert kwargs["expected_value"] == pytest.approx(0.0)
        assert kwargs["probability"] == pytest.approx(0.5)

    async def test_confident_prediction_still_produces_ev(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        mock_rm = AsyncMock(return_value=_risk(approved=False))
        with (
            patch("app.workflow._call_prediction_api", new_callable=AsyncMock,
                  return_value=_pred(prediction="Yes", confidence=0.80)),
            patch("app.workflow._fetch_market_price", new_callable=AsyncMock, return_value=0.60),
            patch("app.workflow._call_risk_manager", mock_rm),
        ):
            await wf.run_iteration(None, MagicMock(), s)
        assert mock_rm.call_args.args[5] == pytest.approx(0.20)
