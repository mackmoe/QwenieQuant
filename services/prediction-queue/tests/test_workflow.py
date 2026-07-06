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
        quantity=5,
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
