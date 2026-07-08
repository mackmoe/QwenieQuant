"""
Tests for SPEC-023: /workflow, /performance, /activity Discord commands.

All dependent services are mocked. No live dependencies required.
"""

from unittest.mock import AsyncMock, MagicMock

from app.commands import handle_activity, handle_performance, handle_workflow
from app.formatter import (
    _fmt_hhmm,
    _time_ago,
    format_activity,
    format_performance,
    format_workflow,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_ALLOWED_IDS = [111111111111111111]


def _settings(calibration_enabled: bool = True):
    s = MagicMock()
    s.allowed_user_ids = list(_ALLOWED_IDS)
    s.confidence_calibration_enabled = calibration_enabled
    return s


def _oe_health(status="ok", markets_scored=1084, tier3=28, last_scan="2026-07-07T12:00:00Z"):
    return {
        "status": status,
        "kalshi_connector": True,
        "postgres": True,
        "last_scan": last_scan,
        "markets_scored": markets_scored,
        "tier3_candidates": tier3,
        "dry_run_safe": True,
        "version": "0.1.0",
    }


def _pq_health(active_entries=0, queue_size=30):
    return {
        "status": "ok",
        "postgres": True,
        "queue_size": queue_size,
        "active_entries": active_entries,
        "last_refresh": "2026-07-07T12:00:00Z",
        "version": "0.1.0",
    }


def _pq_stats(queued=12, in_progress=1, completed=187, failed=0):
    return {
        "entries": [],
        "total": queued + in_progress + completed + failed,
        "active": queued + in_progress,
        "by_state": {
            "QUEUED": queued,
            "IN_PROGRESS": in_progress,
            "COMPLETED": completed,
            "FAILED": failed,
        },
        "version": "0.1.0",
    }


def _le_health(status="ok"):
    return {"status": status, "postgres": True}


def _re_health(status="ok"):
    return {"status": status, "postgres": True}


def _pred_health(status="ok"):
    return {"status": status, "ollama": True, "version": "0.1.0"}


def _analysis(predictions=573, outcomes=482, accuracy=0.638, conf=0.614):
    return {
        "analysis_id": "analysis_20260707T120000_aabbccdd",
        "predictions_analyzed": predictions,
        "outcomes_available": outcomes,
        "accuracy": accuracy,
        "average_confidence": conf,
        "model_breakdown": {"qwen3:8b": predictions},
        "category_breakdown": {"finance": 200, "sports": 250, "weather": 123},
        "observations": ["Good accuracy."],
        "time_range": "all time",
    }


def _queue_entry(ticker="KXBTC-24DEC25-T120000", title="Will BTC exceed $120k?",
                 last_updated="2026-07-07T22:14:00Z"):
    return {
        "queue_id": "abc-123",
        "market_id": ticker,
        "ticker": ticker,
        "priority_score": 91.0,
        "effective_priority": 91.0,
        "queue_state": "COMPLETED",
        "enqueue_time": "2026-07-07T22:00:00Z",
        "expiration_time": None,
        "last_updated": last_updated,
        "metadata": {"title": title, "assigned_tier": 3},
    }


def _completed_response(entries=None):
    if entries is None:
        entries = [_queue_entry()]
    return {
        "entries": entries,
        "total": len(entries),
        "active": 0,
        "by_state": {"COMPLETED": len(entries)},
        "version": "0.1.0",
    }


def _mk_oe(health=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _oe_health())
    c.get_opportunities = AsyncMock(return_value={"markets": [], "total": 0})
    return c


def _mk_pq(health=None, stats=None, completed=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _pq_health())
    c.get_stats = AsyncMock(return_value=stats or _pq_stats())
    c.get_recent_completed = AsyncMock(return_value=completed or _completed_response())
    return c


def _mk_le(health=None, analysis=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _le_health())
    c.analyze = AsyncMock(return_value=analysis or _analysis())
    return c


def _mk_re(health=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _re_health())
    return c


def _mk_pred(health=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _pred_health())
    return c


# ---------------------------------------------------------------------------
# _time_ago
# ---------------------------------------------------------------------------


def test_time_ago_none_returns_unknown():
    assert _time_ago(None) == "Unknown"


def test_time_ago_invalid_string_returns_unknown():
    assert _time_ago("not-a-date") == "Unknown"


def test_time_ago_recent_shows_seconds():
    from datetime import datetime, timezone, timedelta
    dt = datetime.now(timezone.utc) - timedelta(seconds=30)
    result = _time_ago(dt.isoformat())
    assert "s ago" in result or "Just now" in result


def test_time_ago_minutes():
    from datetime import datetime, timezone, timedelta
    dt = datetime.now(timezone.utc) - timedelta(minutes=5)
    result = _time_ago(dt.isoformat())
    assert "m ago" in result


def test_time_ago_hours():
    from datetime import datetime, timezone, timedelta
    dt = datetime.now(timezone.utc) - timedelta(hours=3)
    result = _time_ago(dt.isoformat())
    assert "h ago" in result


def test_time_ago_days():
    from datetime import datetime, timezone, timedelta
    dt = datetime.now(timezone.utc) - timedelta(days=2)
    result = _time_ago(dt.isoformat())
    assert "d ago" in result


# ---------------------------------------------------------------------------
# _fmt_hhmm
# ---------------------------------------------------------------------------


def test_fmt_hhmm_none_returns_placeholder():
    assert _fmt_hhmm(None) == "??:??"


def test_fmt_hhmm_iso_returns_time():
    result = _fmt_hhmm("2026-07-07T22:14:00Z")
    assert result == "22:14"


def test_fmt_hhmm_invalid_returns_placeholder():
    assert _fmt_hhmm("not-a-date") == "??:??"


# ---------------------------------------------------------------------------
# format_workflow
# ---------------------------------------------------------------------------


def test_format_workflow_all_ok_shows_running():
    result = format_workflow(_oe_health(), _pq_health(), _pq_stats(), _le_health(), _re_health(), _pred_health())
    assert "Running" in result
    assert "✅" in result


def test_format_workflow_degraded_service_shows_degraded():
    result = format_workflow(
        {"error": "Connection refused"},
        _pq_health(), _pq_stats(), _le_health(), _re_health(), _pred_health()
    )
    assert "Degraded" in result or "⚠️" in result


def test_format_workflow_shows_markets_scanned():
    result = format_workflow(_oe_health(markets_scored=1084), _pq_health(), _pq_stats(), _le_health(), _re_health(), _pred_health())
    assert "1,084" in result


def test_format_workflow_shows_queued_count():
    result = format_workflow(_oe_health(), _pq_health(), _pq_stats(queued=15), _le_health(), _re_health(), _pred_health())
    assert "15" in result


def test_format_workflow_shows_completed_count():
    result = format_workflow(_oe_health(), _pq_health(), _pq_stats(completed=187), _le_health(), _re_health(), _pred_health())
    assert "187" in result


def test_format_workflow_shows_in_progress_yes():
    result = format_workflow(_oe_health(), _pq_health(active_entries=1), _pq_stats(in_progress=1), _le_health(), _re_health(), _pred_health())
    assert "Yes" in result


def test_format_workflow_shows_in_progress_no():
    result = format_workflow(_oe_health(), _pq_health(active_entries=0), _pq_stats(in_progress=0), _le_health(), _re_health(), _pred_health())
    assert "No" in result


def test_format_workflow_oe_unavailable_shows_unavailable():
    result = format_workflow({"error": "Connection refused"}, _pq_health(), _pq_stats(), _le_health(), _re_health(), _pred_health())
    assert "Unavailable" in result


def test_format_workflow_learning_down_shows_cross():
    result = format_workflow(_oe_health(), _pq_health(), _pq_stats(), {"error": "Down"}, _re_health(), _pred_health())
    assert "❌" in result


def test_format_workflow_shows_last_scan():
    result = format_workflow(_oe_health(), _pq_health(), _pq_stats(), _le_health(), _re_health(), _pred_health())
    assert "Last Scan" in result


def test_format_workflow_tier3_candidates_shown():
    result = format_workflow(_oe_health(tier3=28), _pq_health(), _pq_stats(), _le_health(), _re_health(), _pred_health())
    assert "28" in result


def test_format_workflow_under_discord_limit():
    result = format_workflow(_oe_health(), _pq_health(), _pq_stats(), _le_health(), _re_health(), _pred_health())
    assert len(result) <= 2000


# ---------------------------------------------------------------------------
# format_performance
# ---------------------------------------------------------------------------


def test_format_performance_shows_heading():
    result = format_performance(_analysis(), _settings())
    assert "Platform Performance" in result


def test_format_performance_shows_accuracy():
    result = format_performance(_analysis(accuracy=0.638), _settings())
    assert "63.8%" in result


def test_format_performance_shows_confidence():
    result = format_performance(_analysis(conf=0.614), _settings())
    assert "61.4%" in result


def test_format_performance_shows_calibration_active():
    result = format_performance(_analysis(), _settings(calibration_enabled=True))
    assert "Active" in result


def test_format_performance_shows_calibration_disabled():
    result = format_performance(_analysis(), _settings(calibration_enabled=False))
    assert "Disabled" in result


def test_format_performance_shows_resolved_count():
    result = format_performance(_analysis(outcomes=482), _settings())
    assert "482" in result


def test_format_performance_insufficient_history():
    result = format_performance(_analysis(predictions=5, outcomes=0, accuracy=None, conf=None), _settings())
    assert "Insufficient" in result or "insufficient" in result.lower()


def test_format_performance_shows_model():
    result = format_performance(_analysis(), _settings())
    assert "qwen3:8b" in result


def test_format_performance_error_shows_unavailable():
    result = format_performance({"error": "Connection refused"}, _settings())
    assert "❌" in result
    assert "unavailable" in result.lower()


def test_format_performance_null_accuracy_shows_na():
    a = _analysis()
    a["accuracy"] = None
    a["outcomes_available"] = 10  # has outcomes but no accuracy computed yet
    result = format_performance(a, _settings())
    assert "N/A" in result


# ---------------------------------------------------------------------------
# format_activity
# ---------------------------------------------------------------------------


def test_format_activity_shows_heading():
    result = format_activity(_completed_response(), _oe_health())
    assert "Recent Activity" in result


def test_format_activity_shows_ticker_or_title():
    result = format_activity(_completed_response([_queue_entry(title="Will BTC exceed $120k?")]), _oe_health())
    assert "BTC" in result or "120k" in result


def test_format_activity_shows_oe_scan():
    result = format_activity(_completed_response(), _oe_health(markets_scored=1084))
    assert "Opportunity Scan" in result
    assert "1,084" in result


def test_format_activity_empty_queue_shows_no_activity():
    result = format_activity(_completed_response([]), {"error": "unavailable"})
    assert "No recent activity" in result or "unavailable" in result.lower()


def test_format_activity_pq_unavailable_oe_still_shows():
    # When PQ fails but OE has data, the OE scan entry still appears.
    result = format_activity({"error": "Connection refused"}, _oe_health())
    assert isinstance(result, str)
    assert "Opportunity Scan" in result


def test_format_activity_pq_and_oe_unavailable():
    result = format_activity({"error": "Down"}, {"error": "Down"})
    assert isinstance(result, str)
    assert len(result) > 0


def test_format_activity_multiple_entries_newest_first():
    entries = [
        _queue_entry(ticker="AAA", title="AAA Market Question", last_updated="2026-07-07T22:00:00Z"),
        _queue_entry(ticker="BBB", title="BBB Market Question", last_updated="2026-07-07T23:00:00Z"),
    ]
    result = format_activity(_completed_response(entries), {"error": "skip"})
    idx_aaa = result.find("AAA")
    idx_bbb = result.find("BBB")
    assert idx_bbb < idx_aaa, "Newer entry (BBB at 23:00) should appear before older one (AAA at 22:00)"


def test_format_activity_under_discord_limit():
    entries = [_queue_entry(ticker=f"TICK{i}", last_updated=f"2026-07-07T{20 + i // 60:02d}:{i % 60:02d}:00Z") for i in range(30)]
    result = format_activity(_completed_response(entries), _oe_health())
    assert len(result) <= 2000


def test_format_activity_shows_hhmm_timestamp():
    result = format_activity(
        _completed_response([_queue_entry(last_updated="2026-07-07T22:14:00Z")]),
        {"error": "skip"},
    )
    assert "22:14" in result


# ---------------------------------------------------------------------------
# handle_workflow (async integration)
# ---------------------------------------------------------------------------


async def test_handle_workflow_returns_string():
    result = await handle_workflow(
        _ALLOWED_IDS[0], _mk_oe(), _mk_pq(), _mk_le(), _mk_re(), _mk_pred()
    )
    assert isinstance(result, str)


async def test_handle_workflow_contains_platform_heading():
    result = await handle_workflow(
        _ALLOWED_IDS[0], _mk_oe(), _mk_pq(), _mk_le(), _mk_re(), _mk_pred()
    )
    assert "Prediction AI Platform" in result


async def test_handle_workflow_oe_unavailable_partial_failure():
    oe = _mk_oe(health={"error": "Down"})
    result = await handle_workflow(
        _ALLOWED_IDS[0], oe, _mk_pq(), _mk_le(), _mk_re(), _mk_pred()
    )
    assert isinstance(result, str)
    assert "Unavailable" in result or "Degraded" in result


async def test_handle_workflow_pq_exception_partial_failure():
    pq = _mk_pq()
    pq.health = AsyncMock(side_effect=Exception("Connection refused"))
    pq.get_stats = AsyncMock(side_effect=Exception("Connection refused"))
    result = await handle_workflow(
        _ALLOWED_IDS[0], _mk_oe(), pq, _mk_le(), _mk_re(), _mk_pred()
    )
    assert isinstance(result, str)
    assert "Degraded" in result or "⚠️" in result


async def test_handle_workflow_all_services_down_still_returns():
    oe = _mk_oe(health={"error": "down"})
    pq = _mk_pq(health={"error": "down"}, stats={"error": "down"})
    le = _mk_le(health={"error": "down"})
    re = _mk_re(health={"error": "down"})
    pred = _mk_pred(health={"error": "down"})
    result = await handle_workflow(
        _ALLOWED_IDS[0], oe, pq, le, re, pred
    )
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# handle_performance (async integration)
# ---------------------------------------------------------------------------


async def test_handle_performance_returns_string():
    result = await handle_performance(_ALLOWED_IDS[0], _mk_le(), _settings())
    assert isinstance(result, str)


async def test_handle_performance_with_history_shows_accuracy():
    result = await handle_performance(_ALLOWED_IDS[0], _mk_le(analysis=_analysis(accuracy=0.70)), _settings())
    assert "70.0%" in result


async def test_handle_performance_no_history_shows_insufficient():
    a = _analysis(predictions=5, outcomes=0, accuracy=None, conf=None)
    result = await handle_performance(_ALLOWED_IDS[0], _mk_le(analysis=a), _settings())
    assert "Insufficient" in result or "insufficient" in result.lower()


async def test_handle_performance_learning_unavailable():
    le = _mk_le(analysis={"error": "Service down"})
    result = await handle_performance(_ALLOWED_IDS[0], le, _settings())
    assert "❌" in result or "unavailable" in result.lower()


# ---------------------------------------------------------------------------
# handle_activity (async integration)
# ---------------------------------------------------------------------------


async def test_handle_activity_returns_string():
    result = await handle_activity(_ALLOWED_IDS[0], _mk_pq(), _mk_oe())
    assert isinstance(result, str)


async def test_handle_activity_shows_recent_activity_heading():
    result = await handle_activity(_ALLOWED_IDS[0], _mk_pq(), _mk_oe())
    assert "Recent Activity" in result


async def test_handle_activity_empty_completed_queue():
    pq = _mk_pq(completed=_completed_response([]))
    result = await handle_activity(_ALLOWED_IDS[0], pq, _mk_oe())
    assert isinstance(result, str)
    assert "Opportunity Scan" in result  # OE scan still shows


async def test_handle_activity_pq_unavailable_partial_failure():
    pq = _mk_pq()
    pq.get_recent_completed = AsyncMock(side_effect=Exception("Connection refused"))
    result = await handle_activity(_ALLOWED_IDS[0], pq, _mk_oe())
    assert isinstance(result, str)
    assert "Opportunity Scan" in result  # OE scan still shows when PQ fails


async def test_handle_activity_calls_get_recent_completed():
    pq = _mk_pq()
    await handle_activity(_ALLOWED_IDS[0], pq, _mk_oe(), limit=25)
    pq.get_recent_completed.assert_called_once_with(limit=25)
