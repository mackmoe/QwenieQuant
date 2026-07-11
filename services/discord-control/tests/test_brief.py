"""
Tests for SPEC-024: /brief Discord command.

All dependent services are mocked. No live dependencies required.
"""

from unittest.mock import AsyncMock, MagicMock

from app.commands import handle_brief
from app.formatter import _fmt_uptime, format_brief

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_ALLOWED_IDS = [111111111111111111]

_UPTIME_30M = 30 * 60.0


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


def _pq_health(status="ok", active_entries=0):
    return {
        "status": status,
        "postgres": True,
        "queue_size": 30,
        "active_entries": active_entries,
        "last_refresh": "2026-07-07T12:00:00Z",
        "version": "0.1.0",
    }


def _pq_stats(queued=12, in_progress=1, completed=214, failed=0):
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


def _pred_health(status="ok"):
    return {"status": status, "ollama": True, "version": "0.1.0"}


def _rm_health(status="ok", kalshi_connector=True, dry_run=True):
    return {
        "status": status,
        "postgres": True,
        "kalshi_connector": kalshi_connector,
        "dry_run": dry_run,
        "version": "0.1.0",
    }


def _analysis(predictions=573, outcomes=482, accuracy=0.638, conf=0.614):
    return {
        "analysis_id": "analysis_20260707T120000_aabbccdd",
        "predictions_analyzed": predictions,
        "outcomes_available": outcomes,
        "accuracy": accuracy,
        "average_confidence": conf,
        "model_breakdown": {"qwen3:8b": predictions},
        "category_breakdown": {"finance": 200},
        "observations": ["Good accuracy."],
        "time_range": "all time",
    }


def _reflection(strengths=None, weaknesses=None, recommendations=None):
    return {
        "reflection_id": "reflection_20260707T120000_aabbccdd",
        "analysis_id": "analysis_20260707T120000_aabbccdd",
        "strengths": strengths or ["Weather predictions improving."],
        "weaknesses": weaknesses or ["Finance confidence remains too high."],
        "patterns": [],
        "recommendations": recommendations or ["Continue monitoring confidence calibration."],
    }


def _top_opps(title="Will BTC exceed $120,000?", score=94.2, tier=3, days=0.1):
    return {
        "markets": [
            {
                "market_id": "KXBTC-24DEC25-T120000",
                "ticker": "KXBTC-24DEC25-T120000",
                "title": title,
                "priority_score": score,
                "assigned_tier": tier,
                "scoring_timestamp": "2026-07-07T12:00:00Z",
                "metadata": {"days_remaining": days},
            }
        ],
        "total": 1,
        "tier_counts": {"0": 0, "1": 0, "2": 0, "3": 1},
        "scored_at": "2026-07-07T12:00:00Z",
        "version": "0.1.0",
    }


def _mk_oe(health=None, opps=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _oe_health())
    c.get_opportunities = AsyncMock(return_value=opps or _top_opps())
    c.get_best_by_category = AsyncMock(return_value={"error": "unavailable"})
    return c


def _mk_pq(health=None, stats=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _pq_health())
    c.get_stats = AsyncMock(return_value=stats or _pq_stats())
    c.get_activity_stats = AsyncMock(return_value={"error": "unavailable"})
    return c


def _mk_le(analysis=None):
    c = MagicMock()
    c.analyze = AsyncMock(return_value=analysis or _analysis())
    return c


def _mk_re(reflection=None):
    c = MagicMock()
    c.reflect = AsyncMock(return_value=reflection or _reflection())
    return c


def _mk_pred(health=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _pred_health())
    return c


def _mk_rm(health=None):
    c = MagicMock()
    c.health = AsyncMock(return_value=health or _rm_health())
    return c


def _brief(**kwargs):
    """Call format_brief with sensible defaults; override via kwargs."""
    return format_brief(
        oe_health=kwargs.get("oe_health", _oe_health()),
        pq_health=kwargs.get("pq_health", _pq_health()),
        pq_stats=kwargs.get("pq_stats", _pq_stats()),
        analysis=kwargs.get("analysis", _analysis()),
        pred_health=kwargs.get("pred_health", _pred_health()),
        rm_health=kwargs.get("rm_health", _rm_health()),
        top_opps=kwargs.get("top_opps", _top_opps()),
        reflection=kwargs.get("reflection", _reflection()),
        settings=kwargs.get("settings", _settings()),
        uptime_seconds=kwargs.get("uptime_seconds", _UPTIME_30M),
    )


# ---------------------------------------------------------------------------
# _fmt_uptime
# ---------------------------------------------------------------------------


def test_fmt_uptime_seconds():
    assert _fmt_uptime(45) == "45s"


def test_fmt_uptime_zero():
    assert _fmt_uptime(0) == "0s"


def test_fmt_uptime_negative_clamps():
    assert _fmt_uptime(-10) == "0s"


def test_fmt_uptime_minutes():
    assert _fmt_uptime(125) == "2m 5s"


def test_fmt_uptime_hours():
    assert _fmt_uptime(3 * 3600 + 15 * 60) == "3h 15m"


def test_fmt_uptime_days():
    assert _fmt_uptime(25 * 3600) == "1d 1h"


def test_fmt_uptime_exact_hour():
    assert _fmt_uptime(3600) == "1h 0m"


# ---------------------------------------------------------------------------
# format_brief — heading and structure
# ---------------------------------------------------------------------------


def test_brief_heading():
    result = _brief()
    assert "Platform Brief" in result


def test_brief_has_platform_section():
    result = _brief()
    assert "Platform" in result


def test_brief_has_activity_section():
    result = _brief()
    assert "Activity" in result


def test_brief_has_performance_section():
    result = _brief()
    assert "Performance" in result


def test_brief_has_opportunity_section():
    result = _brief()
    assert "Best Opportunity" in result


def test_brief_has_reflection_section():
    result = _brief()
    assert "Reflection" in result


def test_brief_under_discord_limit():
    result = _brief()
    assert len(result) <= 2000


# ---------------------------------------------------------------------------
# format_brief — Section 1: Platform
# ---------------------------------------------------------------------------


def test_brief_all_ok_shows_running():
    result = _brief()
    assert "Running" in result
    assert "🟢" in result


def test_brief_degraded_shows_red():
    result = _brief(pred_health={"error": "down"})
    assert "Degraded" in result or "🔴" in result


def test_brief_shows_uptime():
    result = _brief(uptime_seconds=30 * 60)
    assert "30m" in result


def test_brief_shows_last_activity():
    result = _brief()
    assert "Last Activity" in result


# ---------------------------------------------------------------------------
# format_brief — Section 2: Activity Summary
# ---------------------------------------------------------------------------


def test_brief_shows_markets_scanned():
    result = _brief(oe_health=_oe_health(markets_scored=1084))
    assert "1,084" in result


def test_brief_shows_predictions_completed():
    result = _brief(pq_stats=_pq_stats(completed=214))
    assert "214" in result


def test_brief_oe_down_omits_markets_scanned():
    result = _brief(oe_health={"error": "Connection refused"})
    assert "Markets Scanned" not in result


# ---------------------------------------------------------------------------
# format_brief — Section 3: Performance Snapshot
# ---------------------------------------------------------------------------


def test_brief_shows_accuracy():
    result = _brief(analysis=_analysis(accuracy=0.638))
    assert "63.8%" in result


def test_brief_shows_confidence():
    result = _brief(analysis=_analysis(conf=0.614))
    assert "61.4%" in result


def test_brief_shows_calibration_active():
    result = _brief(settings=_settings(calibration_enabled=True))
    assert "Active" in result


def test_brief_shows_calibration_disabled():
    result = _brief(settings=_settings(calibration_enabled=False))
    assert "Disabled" in result


def test_brief_shows_resolved_count():
    result = _brief(analysis=_analysis(outcomes=482))
    assert "482" in result


def test_brief_insufficient_history_no_error():
    result = _brief(analysis=_analysis(predictions=3, outcomes=0, accuracy=None, conf=None))
    assert "Insufficient" in result
    assert "❌" not in result.split("Performance")[1].split("Best Opportunity")[0]


def test_brief_le_unavailable_shows_unavailable():
    result = _brief(analysis={"error": "Service down"})
    assert "unavailable" in result.lower()


def test_brief_null_accuracy_shows_na():
    a = _analysis()
    a["accuracy"] = None
    result = _brief(analysis=a)
    assert "N/A" in result


# ---------------------------------------------------------------------------
# format_brief — Section 4: Best Opportunity
# ---------------------------------------------------------------------------


def test_brief_shows_opportunity_title():
    result = _brief(top_opps=_top_opps(title="Will BTC exceed $120,000?"))
    assert "BTC" in result


def test_brief_shows_priority_score():
    result = _brief(top_opps=_top_opps(score=94.2))
    assert "94.2" in result


def test_brief_shows_prediction_label():
    result = _brief(top_opps=_top_opps(tier=3))
    assert "Prediction:" in result


def test_brief_shows_expiry():
    result = _brief(top_opps=_top_opps(days=0.1))
    assert "Expires" in result


def test_brief_no_opportunities_shows_message():
    result = _brief(top_opps={"markets": [], "total": 0})
    assert "No qualifying" in result or "No active" in result


def test_brief_oe_opps_error_shows_no_opportunities():
    result = _brief(top_opps={"error": "Connection refused"})
    assert "No qualifying" in result or "No active" in result


# ---------------------------------------------------------------------------
# format_brief — Section 5: Latest Reflection
# ---------------------------------------------------------------------------


def test_brief_shows_strength():
    result = _brief(reflection=_reflection(strengths=["Weather predictions improving."]))
    assert "Weather predictions improving" in result


def test_brief_shows_weakness():
    result = _brief(reflection=_reflection(weaknesses=["Finance confidence too high."]))
    assert "Finance confidence too high" in result


def test_brief_shows_recommendation():
    result = _brief(reflection=_reflection(recommendations=["Monitor calibration closely."]))
    assert "Monitor calibration closely" in result


def test_brief_max_two_strengths():
    result = _brief(reflection=_reflection(strengths=["S1.", "S2.", "S3."]))
    assert result.count("Strength:") == 2


def test_brief_max_two_weaknesses():
    result = _brief(reflection=_reflection(weaknesses=["W1.", "W2.", "W3."]))
    assert result.count("Weakness:") == 2


def test_brief_reflection_error_shows_no_reflections():
    result = _brief(reflection={"error": "no analysis available"})
    assert "No reflections available" in result


def test_brief_empty_reflection_shows_no_reflections():
    result = _brief(reflection={"strengths": [], "weaknesses": [], "recommendations": []})
    assert "No reflections available" in result


# ---------------------------------------------------------------------------
# format_brief — Section 6: Operator Attention
# ---------------------------------------------------------------------------


def test_brief_all_ok_no_attention_needed():
    result = _brief()
    assert "No operator action required" in result


def test_brief_pred_api_down_shows_attention():
    result = _brief(pred_health={"error": "down"})
    assert "Prediction API unavailable" in result


def test_brief_oe_down_shows_attention():
    result = _brief(oe_health={"error": "down"})
    assert "Opportunity Engine unavailable" in result


def test_brief_pq_down_shows_attention():
    result = _brief(pq_health={"error": "down"})
    assert "Prediction Queue unavailable" in result


def test_brief_rm_down_shows_attention():
    result = _brief(rm_health={"error": "down"})
    assert "Risk Manager unavailable" in result


def test_brief_kalshi_auth_failed_shows_attention():
    result = _brief(rm_health=_rm_health(kalshi_connector=False))
    assert "Kalshi authentication failed" in result


def test_brief_no_markets_scanned_shows_attention():
    result = _brief(oe_health=_oe_health(markets_scored=0))
    assert "No market scans completed" in result


def test_brief_attention_section_header_shows():
    result = _brief(pred_health={"error": "down"})
    assert "Operator Attention" in result


def test_brief_no_attention_section_hidden_when_all_ok():
    result = _brief()
    assert "Operator Attention" not in result


# ---------------------------------------------------------------------------
# handle_brief (async integration)
# ---------------------------------------------------------------------------


async def test_handle_brief_returns_string():
    result = await handle_brief(
        _ALLOWED_IDS[0], _mk_oe(), _mk_pq(), _mk_le(), _mk_re(),
        _mk_pred(), _mk_rm(), _settings(), _UPTIME_30M,
    )
    assert isinstance(result, str)


async def test_handle_brief_contains_heading():
    result = await handle_brief(
        _ALLOWED_IDS[0], _mk_oe(), _mk_pq(), _mk_le(), _mk_re(),
        _mk_pred(), _mk_rm(), _settings(), _UPTIME_30M,
    )
    assert "Platform Brief" in result


async def test_handle_brief_calls_reflect_with_analysis_id():
    re = _mk_re()
    await handle_brief(
        _ALLOWED_IDS[0], _mk_oe(), _mk_pq(), _mk_le(), re,
        _mk_pred(), _mk_rm(), _settings(), _UPTIME_30M,
    )
    re.reflect.assert_called_once_with("analysis_20260707T120000_aabbccdd")


async def test_handle_brief_reflect_skipped_when_analyze_fails():
    le = _mk_le(analysis={"error": "Service down"})
    re = _mk_re()
    result = await handle_brief(
        _ALLOWED_IDS[0], _mk_oe(), _mk_pq(), le, re,
        _mk_pred(), _mk_rm(), _settings(), _UPTIME_30M,
    )
    re.reflect.assert_not_called()
    assert isinstance(result, str)


async def test_handle_brief_partial_failure_still_returns():
    oe = _mk_oe(health={"error": "down"})
    pq = _mk_pq(health={"error": "down"})
    result = await handle_brief(
        _ALLOWED_IDS[0], oe, pq, _mk_le(), _mk_re(),
        _mk_pred(), _mk_rm(), _settings(), _UPTIME_30M,
    )
    assert isinstance(result, str)


async def test_handle_brief_all_services_down():
    oe = _mk_oe(health={"error": "down"})
    oe.get_opportunities = AsyncMock(return_value={"error": "down"})
    pq = _mk_pq(health={"error": "down"}, stats={"error": "down"})
    le = _mk_le(analysis={"error": "down"})
    pred = _mk_pred(health={"error": "down"})
    rm = _mk_rm(health={"error": "down"})
    result = await handle_brief(
        _ALLOWED_IDS[0], oe, pq, le, _mk_re(), pred, rm, _settings(), _UPTIME_30M,
    )
    assert isinstance(result, str)
    assert "Degraded" in result or "🔴" in result


async def test_handle_brief_service_exceptions_handled():
    oe = _mk_oe()
    oe.health = AsyncMock(side_effect=Exception("Connection refused"))
    result = await handle_brief(
        _ALLOWED_IDS[0], oe, _mk_pq(), _mk_le(), _mk_re(),
        _mk_pred(), _mk_rm(), _settings(), _UPTIME_30M,
    )
    assert isinstance(result, str)


async def test_handle_brief_under_discord_limit():
    result = await handle_brief(
        _ALLOWED_IDS[0], _mk_oe(), _mk_pq(), _mk_le(), _mk_re(),
        _mk_pred(), _mk_rm(), _settings(), _UPTIME_30M,
    )
    assert len(result) <= 2000
