"""
Tests for SPEC-026: automatic workflow notifications.

All Discord and service dependencies are mocked. No live connections required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.formatter import format_notification
from app.notifier import WorkflowNotifier


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _oe_health(markets_scored=1042, last_scan="2026-07-08T14:00:00+00:00"):
    return {
        "status": "ok",
        "last_scan": last_scan,
        "markets_scored": markets_scored,
        "tier3_candidates": 30,
    }


def _pq_health():
    return {"status": "ok", "active_entries": 0}


def _pq_stats(queued=30, completed=30):
    return {"by_state": {"QUEUED": queued, "IN_PROGRESS": 0, "COMPLETED": completed, "FAILED": 0}}


def _analysis_ok():
    return {
        "analysis_id": "abc-123",
        "accuracy": 0.638,
        "average_confidence": 0.614,
        "predictions_analyzed": 573,
        "outcomes_available": 482,
        "observations": [
            "Sports predictions continue outperforming finance.",
            "Recent calibration reduced average confidence by 6%.",
            "Third observation that should be truncated.",
        ],
    }


def _reflection_ok():
    return {
        "strengths": ["Prediction consistency improved."],
        "weaknesses": ["Finance confidence remains too high."],
        "recommendations": ["Continue monitoring calibration performance."],
    }


def _top_market():
    return {
        "title": "Will BTC exceed $120,000?",
        "ticker": "KXBTC-T120000",
        "priority_score": 94.2,
        "assigned_tier": 3,
        "metadata": {"days_remaining": 0.1},
    }


def _settings():
    s = MagicMock()
    s.confidence_calibration_enabled = True
    return s


def _fn(**overrides):
    """Build format_notification kwargs with sensible defaults."""
    defaults = dict(
        oe_health=_oe_health(),
        pq_health=_pq_health(),
        pq_stats=_pq_stats(),
        analysis=_analysis_ok(),
        pred_health={"status": "ok"},
        rm_health={"status": "ok", "kalshi_connector": True},
        top_opps={"markets": [_top_market()], "total": 1},
        reflection=_reflection_ok(),
        settings=_settings(),
        workflow_num=1,
        trigger="Scheduled",
        completed_at="2026-07-08T14:00:00+00:00",
    )
    defaults.update(overrides)
    return format_notification(**defaults)


def _mk_notifier(**kwargs):
    """Construct a WorkflowNotifier with all-mocked dependencies."""
    bot = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel.return_value = channel

    oe = MagicMock()
    oe.health = AsyncMock(return_value=_oe_health())
    oe.get_opportunities = AsyncMock(
        return_value={"markets": [_top_market()], "total": 1}
    )
    oe.get_best_by_category = AsyncMock(return_value={"error": "unavailable"})

    pq = MagicMock()
    pq.health = AsyncMock(return_value=_pq_health())
    pq.get_stats = AsyncMock(return_value=_pq_stats())
    pq.get_activity_stats = AsyncMock(return_value={"error": "unavailable"})

    le = MagicMock()
    le.analyze = AsyncMock(return_value=_analysis_ok())

    re = MagicMock()
    re.reflect = AsyncMock(return_value=_reflection_ok())

    pred = MagicMock()
    pred.health = AsyncMock(return_value={"status": "ok"})

    rm = MagicMock()
    rm.health = AsyncMock(return_value={"status": "ok", "kalshi_connector": True})

    return WorkflowNotifier(
        channel_id=kwargs.get("channel_id", 999000111),
        bot=kwargs.get("bot", bot),
        opportunity_client=kwargs.get("oe", oe),
        queue_client=kwargs.get("pq", pq),
        learning_client=kwargs.get("le", le),
        reflection_client=kwargs.get("re", re),
        prediction_client=kwargs.get("pred", pred),
        risk_manager_client=kwargs.get("rm", rm),
        settings=kwargs.get("settings", _settings()),
    )


# ---------------------------------------------------------------------------
# format_notification — header
# ---------------------------------------------------------------------------


def test_format_notification_has_heading():
    result = _fn()
    assert "Prediction Platform Update" in result


def test_format_notification_has_workflow_number():
    result = _fn(workflow_num=7)
    assert "#7" in result


def test_format_notification_scheduled_trigger():
    result = _fn(trigger="Scheduled")
    assert "Scheduled" in result


def test_format_notification_manual_trigger():
    result = _fn(trigger="Manual")
    assert "Manual" in result


def test_format_notification_has_timestamp():
    result = _fn(completed_at="2026-07-08T14:00:00+00:00")
    assert "UTC" in result
    assert "2026-07-08" in result


def test_format_notification_unknown_timestamp_fallback():
    result = _fn(completed_at=None)
    assert "Unknown" in result


# ---------------------------------------------------------------------------
# format_notification — Platform section
# ---------------------------------------------------------------------------


def test_format_notification_all_ok_status_healthy():
    result = _fn()
    assert "Healthy" in result


def test_format_notification_degraded_status_red():
    result = _fn(oe_health={"error": "timeout"})
    assert "Degraded" in result or "🔴" in result


def test_format_notification_has_platform_section():
    result = _fn()
    assert "Platform" in result
    assert "Status:" in result


# ---------------------------------------------------------------------------
# format_notification — Activity section
# ---------------------------------------------------------------------------


def test_format_notification_has_activity_section():
    result = _fn()
    assert "📊" in result


def test_format_notification_shows_markets_scanned():
    result = _fn(oe_health=_oe_health(markets_scored=1042))
    assert "1,042" in result


def test_format_notification_shows_queued():
    result = _fn(pq_stats=_pq_stats(queued=28))
    assert "28" in result


def test_format_notification_shows_predictions():
    result = _fn(pq_stats=_pq_stats(completed=30))
    assert "30" in result


def test_format_notification_oe_down_omits_markets_scanned():
    result = _fn(oe_health={"error": "timeout"})
    assert "Markets Scanned" not in result


# ---------------------------------------------------------------------------
# format_notification — Performance section
# ---------------------------------------------------------------------------


def test_format_notification_has_performance_section():
    result = _fn()
    assert "📈" in result


def test_format_notification_shows_accuracy():
    result = _fn()
    assert "63.8%" in result


def test_format_notification_shows_confidence():
    result = _fn()
    assert "61.4%" in result


def test_format_notification_shows_model():
    result = _fn()
    assert "qwen3" in result.lower() or "Model:" in result


def test_format_notification_insufficient_history():
    analysis = {"analysis_id": "x", "outcomes_available": 0, "predictions_analyzed": 5}
    result = _fn(analysis=analysis)
    assert "Insufficient" in result


def test_format_notification_le_unavailable():
    result = _fn(analysis={"error": "timeout"})
    assert "unavailable" in result.lower()


# ---------------------------------------------------------------------------
# format_notification — Best Opportunity section
# ---------------------------------------------------------------------------


def test_format_notification_has_opportunity_section():
    result = _fn()
    assert "⭐" in result


def test_format_notification_shows_opportunity_title():
    result = _fn()
    assert "BTC" in result


def test_format_notification_shows_priority():
    result = _fn()
    assert "94.2" in result


def test_format_notification_no_opportunities_message():
    result = _fn(top_opps={"markets": [], "total": 0})
    assert "No qualifying" in result


def test_format_notification_oe_opps_error_shows_no_opportunities():
    result = _fn(top_opps={"error": "timeout"})
    assert "No qualifying" in result


# ---------------------------------------------------------------------------
# format_notification — Learning section
# ---------------------------------------------------------------------------


def test_format_notification_shows_observations():
    result = _fn()
    assert "Sports predictions" in result


def test_format_notification_max_two_observations():
    result = _fn()
    # Third observation should not appear
    assert "Third observation" not in result


def test_format_notification_no_observations_omits_learning_section():
    analysis = dict(_analysis_ok(), observations=[])
    result = _fn(analysis=analysis)
    assert "🧠" not in result


def test_format_notification_le_unavailable_omits_learning_section():
    result = _fn(analysis={"error": "down"})
    assert "🧠" not in result


# ---------------------------------------------------------------------------
# format_notification — Reflection section
# ---------------------------------------------------------------------------


def test_format_notification_shows_reflection():
    result = _fn()
    assert "💡" in result
    assert "Strength:" in result


def test_format_notification_shows_weakness():
    result = _fn()
    assert "Weakness:" in result


def test_format_notification_shows_recommendation():
    result = _fn()
    assert "Recommendation:" in result


def test_format_notification_reflection_error_omits_section():
    result = _fn(reflection={"error": "no analysis"})
    assert "💡" not in result


def test_format_notification_empty_reflection_omits_section():
    result = _fn(reflection={"strengths": [], "weaknesses": [], "recommendations": []})
    assert "💡" not in result


# ---------------------------------------------------------------------------
# format_notification — Operator Attention section
# ---------------------------------------------------------------------------


def test_format_notification_all_ok_no_attention():
    result = _fn()
    assert "✅ No operator action required." in result


def test_format_notification_pred_api_down_shows_attention():
    result = _fn(pred_health={"error": "down"})
    assert "Prediction API unavailable" in result


def test_format_notification_oe_down_shows_attention():
    result = _fn(oe_health={"error": "down"})
    assert "Opportunity Engine unavailable" in result


def test_format_notification_pq_down_shows_attention():
    result = _fn(pq_health={"error": "down"})
    assert "Prediction Queue unavailable" in result


def test_format_notification_rm_down_shows_attention():
    result = _fn(rm_health={"error": "down"})
    assert "Risk Manager unavailable" in result


def test_format_notification_kalshi_auth_failed():
    result = _fn(rm_health={"status": "ok", "kalshi_connector": False})
    assert "Kalshi authentication failed" in result


# ---------------------------------------------------------------------------
# format_notification — Quick Commands section
# ---------------------------------------------------------------------------


def test_format_notification_has_quick_commands():
    result = _fn()
    assert "Quick Commands" in result
    assert "/brief" in result


# ---------------------------------------------------------------------------
# format_notification — Discord limit
# ---------------------------------------------------------------------------


def test_format_notification_under_discord_limit():
    result = _fn()
    assert len(result) <= 2000


# ---------------------------------------------------------------------------
# WorkflowNotifier — _get_last_scan
# ---------------------------------------------------------------------------


async def test_notifier_get_last_scan_returns_timestamp():
    notifier = _mk_notifier()
    notifier._oe.health = AsyncMock(return_value=_oe_health(last_scan="2026-01-01T00:00:00+00:00"))
    ts = await notifier._get_last_scan()
    assert ts == "2026-01-01T00:00:00+00:00"


async def test_notifier_get_last_scan_returns_none_on_missing_field():
    notifier = _mk_notifier()
    notifier._oe.health = AsyncMock(return_value={"status": "ok"})
    ts = await notifier._get_last_scan()
    assert ts is None


async def test_notifier_get_last_scan_returns_none_on_exception():
    notifier = _mk_notifier()
    notifier._oe.health = AsyncMock(side_effect=Exception("timeout"))
    ts = await notifier._get_last_scan()
    assert ts is None


# ---------------------------------------------------------------------------
# WorkflowNotifier — signal_manual_trigger
# ---------------------------------------------------------------------------


def test_notifier_signal_manual_trigger_sets_pending():
    notifier = _mk_notifier()
    assert notifier._pending_trigger == "Scheduled"
    notifier.signal_manual_trigger()
    assert notifier._pending_trigger == "Manual"


def test_notifier_signal_manual_trigger_resets_after_detection():
    notifier = _mk_notifier()
    notifier.signal_manual_trigger()
    # Simulate the start() loop consuming the trigger
    trigger = notifier._pending_trigger
    notifier._pending_trigger = "Scheduled"
    assert trigger == "Manual"
    assert notifier._pending_trigger == "Scheduled"


# ---------------------------------------------------------------------------
# WorkflowNotifier — _post_notification
# ---------------------------------------------------------------------------


async def test_notifier_post_notification_sends_message():
    notifier = _mk_notifier()
    await notifier._post_notification(1, "Scheduled", "2026-07-08T14:00:00+00:00")
    notifier._bot.get_channel.return_value.send.assert_called_once()
    msg = notifier._bot.get_channel.return_value.send.call_args[0][0]
    assert isinstance(msg, str)
    assert len(msg) > 0


async def test_notifier_post_notification_channel_not_found_no_raise():
    notifier = _mk_notifier()
    notifier._bot.get_channel.return_value = None
    # Should log an error but not raise
    await notifier._post_notification(1, "Scheduled", None)


async def test_notifier_post_notification_discord_failure_no_raise():
    notifier = _mk_notifier()
    notifier._bot.get_channel.return_value.send = AsyncMock(side_effect=Exception("Discord 503"))
    # Should log but not raise — workflow must never depend on Discord
    await notifier._post_notification(1, "Scheduled", None)


async def test_notifier_post_notification_message_under_discord_limit():
    notifier = _mk_notifier()
    await notifier._post_notification(1, "Scheduled", "2026-07-08T14:00:00+00:00")
    msg = notifier._bot.get_channel.return_value.send.call_args[0][0]
    assert len(msg) <= 2000


# ---------------------------------------------------------------------------
# WorkflowNotifier — _build_message
# ---------------------------------------------------------------------------


async def test_notifier_build_message_returns_string():
    notifier = _mk_notifier()
    result = await notifier._build_message(1, "Scheduled", "2026-07-08T14:00:00+00:00")
    assert isinstance(result, str)
    assert "Prediction Platform Update" in result


async def test_notifier_build_message_partial_failure_returns_string():
    notifier = _mk_notifier()
    notifier._oe.health = AsyncMock(return_value={"error": "timeout"})
    notifier._le.analyze = AsyncMock(return_value={"error": "timeout"})
    result = await notifier._build_message(2, "Manual", None)
    assert isinstance(result, str)
    assert len(result) > 0


async def test_notifier_build_message_all_services_down_returns_string():
    notifier = _mk_notifier()
    notifier._oe.health = AsyncMock(return_value={"error": "down"})
    notifier._pq.health = AsyncMock(return_value={"error": "down"})
    notifier._pq.get_stats = AsyncMock(return_value={"error": "down"})
    notifier._le.analyze = AsyncMock(return_value={"error": "down"})
    notifier._pred.health = AsyncMock(return_value={"error": "down"})
    notifier._rm.health = AsyncMock(return_value={"error": "down"})
    notifier._oe.get_opportunities = AsyncMock(return_value={"error": "down"})
    result = await notifier._build_message(3, "Scheduled", None)
    assert isinstance(result, str)
    assert "🚨" in result


# ---------------------------------------------------------------------------
# WorkflowNotifier — start() loop behavior
# ---------------------------------------------------------------------------


async def test_notifier_start_no_notification_when_scan_unchanged():
    """Seeded scan matches poll result — no notification should be sent."""
    notifier = _mk_notifier()
    notifier._post_notification = AsyncMock()
    notifier._get_last_scan = AsyncMock(return_value="ts1")

    sleep_calls = 0
    async def controlled_sleep(n):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", controlled_sleep):
        try:
            await notifier.start()
        except asyncio.CancelledError:
            pass

    notifier._post_notification.assert_not_called()


async def test_notifier_start_notifies_when_scan_changes():
    """When last_scan changes between polls, exactly one notification is posted."""
    notifier = _mk_notifier()
    notifier._post_notification = AsyncMock()

    scan_values = iter(["ts1", "ts2"])
    async def get_scan():
        return next(scan_values, "ts2")

    notifier._get_last_scan = get_scan

    sleep_calls = 0
    async def controlled_sleep(n):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 3:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", controlled_sleep):
        try:
            await notifier.start()
        except asyncio.CancelledError:
            pass

    notifier._post_notification.assert_called_once()
    args = notifier._post_notification.call_args[0]
    assert args[0] == 1           # workflow_num
    assert args[1] == "Scheduled" # trigger
    assert args[2] == "ts2"       # completed_at


async def test_notifier_start_manual_trigger_propagated():
    """signal_manual_trigger() causes next notification to carry 'Manual'."""
    notifier = _mk_notifier()
    notifier._post_notification = AsyncMock()
    notifier.signal_manual_trigger()

    scan_values = iter(["ts1", "ts2"])
    async def get_scan():
        return next(scan_values, "ts2")

    notifier._get_last_scan = get_scan

    sleep_calls = 0
    async def controlled_sleep(n):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 3:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", controlled_sleep):
        try:
            await notifier.start()
        except asyncio.CancelledError:
            pass

    args = notifier._post_notification.call_args[0]
    assert args[1] == "Manual"


async def test_notifier_start_increments_workflow_count():
    notifier = _mk_notifier()
    assert notifier._workflow_count == 0
    notifier._post_notification = AsyncMock()

    scan_values = iter(["ts1", "ts2"])
    async def get_scan():
        return next(scan_values, "ts2")

    notifier._get_last_scan = get_scan

    sleep_calls = 0
    async def controlled_sleep(n):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 3:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", controlled_sleep):
        try:
            await notifier.start()
        except asyncio.CancelledError:
            pass

    assert notifier._workflow_count == 1


async def test_notifier_start_continues_after_unexpected_error():
    """An unexpected exception in the poll body is caught; loop does not crash."""
    notifier = _mk_notifier()
    notifier._post_notification = AsyncMock()

    call_count = 0
    async def get_scan():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "ts1"          # seed
        raise RuntimeError("Unexpected OE error")

    notifier._get_last_scan = get_scan

    sleep_calls = 0
    async def controlled_sleep(n):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", controlled_sleep):
        try:
            await notifier.start()
        except asyncio.CancelledError:
            pass

    notifier._post_notification.assert_not_called()
