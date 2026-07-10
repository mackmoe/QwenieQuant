from app.formatter import (
    UNAUTHORIZED_MESSAGE,
    _format_prediction_bullets,
    _parse_opportunity_title,
    _render_best_opportunity,
    format_activity,
    format_analysis,
    format_brief,
    format_error,
    format_notification,
    format_prediction,
    format_reflection,
    format_run,
    format_status,
)

_HEALTH_ALL_OK = {
    "prediction_api": {"status": "ok"},
    "learning_engine": {"status": "ok", "postgres": True},
    "reflection_engine": {"status": "ok"},
    "ollama": {"reachable": True},
    "searxng": {"reachable": True},
}

_PREDICTION_OK = {
    "prediction": "Yes",
    "confidence": 0.75,
    "reasoning": "Because recent economic data suggests strong growth.",
}

_ANALYSIS_OK = {
    "analysis_id": "analysis_20260101T000000_aabbccdd",
    "predictions_analyzed": 10,
    "outcomes_available": 5,
    "accuracy": 0.80,
    "average_confidence": 0.75,
    "time_range": "2026-01-01 to 2026-07-01",
    "observations": ["10 prediction(s) analyzed.", "Accuracy is 80.0%."],
}

_REFLECTION_OK = {
    "reflection_id": "reflection_20260101T000000_aabbccdd",
    "strengths": ["High accuracy."],
    "weaknesses": ["Low volume."],
    "patterns": ["Single model used."],
    "recommendations": ["Collect more data."],
}


# --- format_status ---


def test_format_status_all_ok_has_checkmarks():
    result = format_status(_HEALTH_ALL_OK)
    assert result.count("✅") == 6


def test_format_status_includes_all_six_services():
    result = format_status(_HEALTH_ALL_OK)
    for service in ("Prediction API", "Learning Engine", "Reflection Engine",
                    "PostgreSQL", "Ollama", "SearXNG"):
        assert service in result, f"Missing: {service}"


def test_format_status_degraded_shows_cross():
    health = {**_HEALTH_ALL_OK, "prediction_api": {"status": "degraded"}}
    result = format_status(health)
    assert "❌" in result


def test_format_status_unreachable_postgres():
    health = {**_HEALTH_ALL_OK, "learning_engine": {"status": "ok", "postgres": False}}
    result = format_status(health)
    assert "❌" in result


def test_format_status_missing_service_shows_unreachable():
    result = format_status({"prediction_api": {}, "learning_engine": {},
                            "reflection_engine": {}, "ollama": {}, "searxng": {}})
    assert "unreachable" in result


# --- format_prediction ---


def test_format_prediction_shows_answer():
    result = format_prediction(_PREDICTION_OK)
    assert "Yes" in result


def test_format_prediction_shows_confidence():
    result = format_prediction(_PREDICTION_OK)
    assert "75%" in result


def test_format_prediction_truncates_long_reasoning():
    long_pred = {**_PREDICTION_OK, "reasoning": "X" * 500}
    result = format_prediction(long_pred)
    assert len(result) < 600


def test_format_prediction_error():
    result = format_prediction({"error": "Service unavailable"})
    assert "❌" in result
    assert "Service unavailable" in result


# --- format_analysis ---


def test_format_analysis_shows_counts():
    result = format_analysis(_ANALYSIS_OK)
    assert "10" in result  # predictions_analyzed


def test_format_analysis_shows_accuracy():
    result = format_analysis(_ANALYSIS_OK)
    assert "80" in result


def test_format_analysis_null_accuracy_shows_na():
    summary = {**_ANALYSIS_OK, "accuracy": None}
    result = format_analysis(summary)
    assert "N/A" in result


def test_format_analysis_shows_observations():
    result = format_analysis(_ANALYSIS_OK)
    assert "Observations" in result


def test_format_analysis_error():
    result = format_analysis({"error": "Engine down"})
    assert "❌" in result


# --- format_reflection ---


def test_format_reflection_has_all_sections():
    result = format_reflection(_REFLECTION_OK)
    for section in ("Strengths", "Weaknesses", "Patterns", "Recommendations"):
        assert section in result, f"Missing section: {section}"


def test_format_reflection_empty_sections_omitted():
    reflection = {**_REFLECTION_OK, "patterns": [], "weaknesses": []}
    result = format_reflection(reflection)
    assert "Patterns" not in result
    assert "Weaknesses" not in result
    assert "Strengths" in result


def test_format_reflection_error():
    result = format_reflection({"error": "Not found"})
    assert "❌" in result


# --- format_error ---


def test_format_error_has_cross():
    assert "❌" in format_error("Something failed")


def test_format_error_includes_message():
    assert "Something failed" in format_error("Something failed")


# --- UNAUTHORIZED_MESSAGE ---


def test_unauthorized_message_has_cross():
    assert "❌" in UNAUTHORIZED_MESSAGE


# --- _format_prediction_bullets ---

_ENTRY = lambda title, ts="2026-07-07T23:38:00Z": {
    "last_updated": ts,
    "ticker": "MKT-TEST",
    "metadata": {"title": title},
}
_NO_OE = {"error": "unavailable"}


def test_single_yes_prediction_renders_as_bullet():
    result = format_activity({"entries": [_ENTRY("yes Baltimore Orioles")]}, _NO_OE)
    assert "• YES — Baltimore Orioles" in result


def test_multiple_yes_predictions_each_on_own_line():
    title = "yes Baltimore,yes Detroit,yes Pittsburgh"
    result = format_activity({"entries": [_ENTRY(title)]}, _NO_OE)
    assert "• YES — Baltimore" in result
    assert "• YES — Detroit" in result
    assert "• YES — Pittsburgh" in result
    # Must not be concatenated — each bullet on its own line
    assert "Baltimore,yes" not in result


def test_mixed_yes_no_predictions_capitalize_correctly():
    title = "yes Baltimore,no Detroit,yes Pittsburgh"
    result = format_activity({"entries": [_ENTRY(title)]}, _NO_OE)
    assert "• YES — Baltimore" in result
    assert "• NO — Detroit" in result
    assert "• YES — Pittsburgh" in result


def test_long_prediction_list_not_truncated_prematurely():
    teams = [f"yes Team{i}" for i in range(8)]
    title = ",".join(teams)
    result = format_activity({"entries": [_ENTRY(title)]}, _NO_OE)
    for i in range(8):
        assert f"• YES — Team{i}" in result


def test_opportunity_scan_line_unchanged():
    oe = {"last_scan": "2026-07-07T23:38:00Z", "markets_scored": 1234}
    result = format_activity({"entries": []}, oe)
    assert "Opportunity Scan · 1,234 markets" in result


def test_format_prediction_bullets_plain_title_passthrough():
    # Title with no yes/no prefix — passed through as plain bullet
    bullets = _format_prediction_bullets("Some plain market title")
    assert bullets == ["• Some plain market title"]


# --- _parse_opportunity_title (HOTFIX-004) ---


def test_parse_opportunity_title_yes_prefix():
    name, pred = _parse_opportunity_title("yes Gabriel Moreno: 1+")
    assert name == "Gabriel Moreno: 1+"
    assert pred == "YES"


def test_parse_opportunity_title_no_prefix():
    name, pred = _parse_opportunity_title("no Detroit Tigers")
    assert name == "Detroit Tigers"
    assert pred == "NO"


def test_parse_opportunity_title_comma_separated_takes_first():
    name, pred = _parse_opportunity_title("yes Gabriel Moreno: 1+,yes Geraldo Perdom,yes Pittsburgh")
    assert name == "Gabriel Moreno: 1+"
    assert pred == "YES"


def test_parse_opportunity_title_plain_title_no_prefix():
    name, pred = _parse_opportunity_title("Will the Fed raise rates?")
    assert name == "Will the Fed raise rates?"
    assert pred == "Unknown"


def test_parse_opportunity_title_case_insensitive():
    name, pred = _parse_opportunity_title("YES Baltimore Orioles")
    assert name == "Baltimore Orioles"
    assert pred == "YES"


# --- _render_best_opportunity (HOTFIX-004) ---

_TOP_OPPS_MULTI = {
    "markets": [
        {
            "title": "yes Gabriel Moreno: 1+,yes Geraldo Perdom,yes Pittsburgh",
            "priority_score": 30.0,
            "assigned_tier": 3,
            "metadata": {"days_remaining": 2.96, "spread": 11},
        }
    ]
}

_TOP_OPPS_PLAIN = {
    "markets": [
        {
            "title": "Will the Fed raise rates in July?",
            "priority_score": 72.5,
            "assigned_tier": 3,
            "metadata": {"days_remaining": 5.0, "spread": None},
        }
    ]
}

_TOP_OPPS_EMPTY = {"markets": [], "error": "unavailable"}


def test_render_best_opportunity_strips_comma_list():
    lines = _render_best_opportunity(_TOP_OPPS_MULTI)
    full = "\n".join(lines)
    # The aggregated string must not appear
    assert "yes Gabriel Moreno: 1+,yes Geraldo Perdom" not in full
    # Only the first element should be shown (clean)
    assert "Gabriel Moreno: 1+" in full


def test_render_best_opportunity_extracts_prediction():
    lines = _render_best_opportunity(_TOP_OPPS_MULTI)
    full = "\n".join(lines)
    assert "Prediction: YES" in full


def test_render_best_opportunity_shows_priority():
    lines = _render_best_opportunity(_TOP_OPPS_MULTI)
    full = "\n".join(lines)
    assert "30.0" in full


def test_render_best_opportunity_shows_edge_when_available():
    lines = _render_best_opportunity(_TOP_OPPS_MULTI)
    full = "\n".join(lines)
    assert "11¢" in full


def test_render_best_opportunity_shows_na_edge_when_missing():
    lines = _render_best_opportunity(_TOP_OPPS_PLAIN)
    full = "\n".join(lines)
    assert "Expected Edge: N/A" in full


def test_render_best_opportunity_plain_title_passthrough():
    lines = _render_best_opportunity(_TOP_OPPS_PLAIN)
    full = "\n".join(lines)
    assert "Will the Fed raise rates in July?" in full
    assert "Prediction: Unknown" in full


def test_render_best_opportunity_no_markets_shows_fallback():
    lines = _render_best_opportunity(_TOP_OPPS_EMPTY)
    full = "\n".join(lines)
    assert "No qualifying" in full


def test_format_brief_best_opportunity_no_aggregated_string():
    health_ok = {
        "prediction_api": {"status": "ok"},
        "learning_engine": {"status": "ok", "postgres": True},
        "reflection_engine": {"status": "ok"},
        "ollama": {"reachable": True},
        "searxng": {"reachable": True},
    }
    settings = type("S", (), {"confidence_calibration_enabled": True})()
    result = format_brief(
        oe_health={"status": "ok", "markets_scored": 100, "last_scan": "2026-07-07T12:00:00Z", "tier3_candidates": 5},
        pq_health={"active_entries": 0},
        pq_stats={"by_state": {"QUEUED": 0, "COMPLETED": 10}},
        analysis={"error": "no data"},
        pred_health={"status": "ok"},
        rm_health={"status": "ok"},
        top_opps=_TOP_OPPS_MULTI,
        reflection={"error": "no data"},
        settings=settings,
        uptime_seconds=3600,
    )
    assert "yes Gabriel Moreno: 1+,yes Geraldo Perdom" not in result
    assert "Gabriel Moreno: 1+" in result
    assert "Prediction: YES" in result


def test_format_notification_best_opportunity_no_aggregated_string():
    settings = type("S", (), {"confidence_calibration_enabled": True})()
    result = format_notification(
        oe_health={"status": "ok", "markets_scored": 100, "last_scan": "2026-07-07T12:00:00Z"},
        pq_health={"active_entries": 0},
        pq_stats={"by_state": {"QUEUED": 0, "COMPLETED": 10}},
        analysis={"error": "no data"},
        pred_health={"status": "ok"},
        rm_health={"status": "ok"},
        top_opps=_TOP_OPPS_MULTI,
        reflection={"error": "no data"},
        settings=settings,
        workflow_num=42,
        trigger="Scheduled",
    )
    assert "yes Gabriel Moreno: 1+,yes Geraldo Perdom" not in result
    assert "Gabriel Moreno: 1+" in result


# --- format_analysis diagnostics (SPEC-030) ---


_DIAG_FULL = {
    "category_performance": [
        {"category": "finance", "count": 10, "resolved": 5, "accuracy": 0.40},
        {"category": "sports", "count": 10, "resolved": 5, "accuracy": 0.90},
    ],
    "yes_no_analysis": {
        "yes": {"count": 8, "resolved": 6, "accuracy": 0.83},
        "no": {"count": 8, "resolved": 6, "accuracy": 0.33},
    },
    "search_effectiveness": {
        "with_search_count": 10,
        "without_search_count": 10,
        "with_search_accuracy": 0.80,
        "without_search_accuracy": 0.50,
        "accuracy_delta": 0.30,
    },
}

_ANALYSIS_WITH_DIAG = {**_ANALYSIS_OK, "diagnostics": _DIAG_FULL}
_ANALYSIS_NO_DIAG = {**_ANALYSIS_OK}


def test_format_analysis_diagnostics_section_present_when_data_available():
    result = format_analysis(_ANALYSIS_WITH_DIAG)
    assert "Diagnostics" in result


def test_format_analysis_diagnostics_shows_best_category():
    result = format_analysis(_ANALYSIS_WITH_DIAG)
    assert "sports" in result


def test_format_analysis_diagnostics_shows_worst_category():
    result = format_analysis(_ANALYSIS_WITH_DIAG)
    assert "finance" in result


def test_format_analysis_diagnostics_shows_yes_no():
    result = format_analysis(_ANALYSIS_WITH_DIAG)
    assert "YES" in result
    assert "NO" in result


def test_format_analysis_diagnostics_shows_search_delta():
    result = format_analysis(_ANALYSIS_WITH_DIAG)
    assert "SearXNG" in result


def test_format_analysis_diagnostics_section_absent_without_data():
    result = format_analysis(_ANALYSIS_NO_DIAG)
    assert "Diagnostics" not in result


def test_format_analysis_diagnostics_absent_when_empty_diag():
    result = format_analysis({**_ANALYSIS_OK, "diagnostics": {}})
    assert "Diagnostics" not in result


def test_format_analysis_diagnostics_absent_when_diag_is_none():
    result = format_analysis({**_ANALYSIS_OK, "diagnostics": None})
    assert "Diagnostics" not in result


# --- format_run (SPEC-029) ---


def test_format_run_empty_status():
    result = format_run({"status": "empty"})
    assert "empty" in result.lower() or "queue" in result.lower()


def test_format_run_busy_shows_elapsed():
    result = format_run({
        "status": "busy",
        "started_at": "2026-07-07T23:00:00+00:00",
        "elapsed_seconds": 42,
    })
    assert "42s" in result
    assert "2026-07-07T23:00:00" in result


def test_format_run_busy_null_elapsed():
    result = format_run({"status": "busy", "started_at": None, "elapsed_seconds": None})
    assert "busy" in result.lower() or "Running" in result


def test_format_run_completed_shows_prediction():
    result = format_run({
        "status": "completed",
        "market_id": "MKT-1",
        "ticker": "MKT-1",
        "title": "Will X happen?",
        "prediction": "Yes",
        "confidence": 0.75,
        "risk_approved": True,
        "risk_reason": "ok",
        "trade_status": "dry_run",
        "duration_ms": 3200,
        "dry_run": True,
    })
    assert "Yes" in result
    assert "75%" in result
    assert "Approved" in result
    assert "dry_run" in result or "dry" in result.lower()


def test_format_run_completed_risk_rejected():
    result = format_run({
        "status": "completed",
        "market_id": "MKT-1",
        "ticker": "MKT-1",
        "prediction": "No",
        "confidence": 0.80,
        "risk_approved": False,
        "risk_reason": "low ev",
        "trade_status": "rejected",
        "duration_ms": 1000,
        "dry_run": True,
    })
    assert "Rejected" in result


def test_format_run_requeued_shows_market():
    result = format_run({
        "status": "requeued",
        "market_id": "MKT-1",
        "ticker": "MKT-1",
        "title": "Test market",
        "dry_run": True,
    })
    assert "requeued" in result.lower() or "Requeued" in result
    assert "Test market" in result


def test_format_run_failed_shows_error():
    result = format_run({
        "status": "failed",
        "market_id": "MKT-1",
        "ticker": "MKT-1",
        "dry_run": True,
    })
    assert "Failed" in result or "failed" in result
    assert "MKT-1" in result


def test_format_run_unknown_status():
    result = format_run({"status": "bogus"})
    assert "bogus" in result


def test_format_run_skipped_shows_status():
    result = format_run({
        "status": "skipped",
        "reason": "multi_outcome",
        "market_id": "MKT-MULTI",
        "ticker": "KXMLB-MULTI",
        "title": "yes Milwaukee,yes Baltimore,yes Detroit",
        "dry_run": True,
    })
    assert "Skipped" in result or "skipped" in result.lower()


def test_format_run_skipped_shows_reason():
    result = format_run({
        "status": "skipped",
        "reason": "multi_outcome",
        "market_id": "MKT-MULTI",
        "ticker": "KXMLB-MULTI",
        "title": "yes Milwaukee,yes Baltimore",
        "dry_run": True,
    })
    assert "multi_outcome" in result


def test_format_run_skipped_shows_market_title():
    result = format_run({
        "status": "skipped",
        "reason": "multi_outcome",
        "market_id": "MKT-MULTI",
        "ticker": "KXMLB-MULTI",
        "title": "yes Milwaukee,yes Baltimore",
        "dry_run": True,
    })
    assert "Milwaukee" in result or "KXMLB-MULTI" in result


def test_format_run_skipped_mentions_no_retry():
    result = format_run({
        "status": "skipped",
        "reason": "multi_outcome",
        "ticker": "KXMLB-MULTI",
        "dry_run": True,
    })
    assert "not be retried" in result or "skipped" in result.lower()


# --- format_hot (Market Interest views) ---

from app.formatter import format_hot

_VIEWS_FULL = {
    "most_active": [
        {"ticker": "KXMLB-A", "title": "Brewers win", "category": "Sports",
         "priority_score": 62.0, "volume_delta": 1200, "price_delta": 2.0,
         "open_interest": 5000, "spread": 2, "rank": 1, "rank_delta": 4},
    ],
    "fastest_rising": [
        {"ticker": "KXBTC-B", "title": "BTC above 120k", "category": "Crypto",
         "priority_score": 55.0, "volume_delta": 300, "price_delta": 7.5,
         "open_interest": 900, "spread": 3, "rank": 5, "rank_delta": -1},
    ],
    "highest_liquidity": [
        {"ticker": "KXFED-C", "title": "Fed cuts rates", "category": "Economics",
         "priority_score": 48.0, "volume_delta": 10, "price_delta": 0.5,
         "open_interest": 22000, "spread": 1, "rank": 9, "rank_delta": None},
    ],
    "highest_opportunity": [
        {"ticker": "KXMLB-A", "title": "Brewers win", "category": "Sports",
         "priority_score": 62.0, "volume_delta": 1200, "price_delta": 2.0,
         "open_interest": 5000, "spread": 2, "rank": 1, "rank_delta": 4},
    ],
    "scored_at": "2026-07-08T18:00:00+00:00",
}


def test_format_hot_shows_all_four_sections():
    result = format_hot(_VIEWS_FULL)
    for header in ("Most Active", "Fastest Rising", "Highest Liquidity", "Highest Opportunity"):
        assert header in result, f"Missing: {header}"


def test_format_hot_shows_volume_delta():
    result = format_hot(_VIEWS_FULL)
    assert "+1,200 contracts" in result


def test_format_hot_shows_price_delta():
    result = format_hot(_VIEWS_FULL)
    assert "+7.5¢" in result


def test_format_hot_shows_open_interest_and_spread():
    result = format_hot(_VIEWS_FULL)
    assert "22,000 open interest" in result
    assert "1¢ spread" in result


def test_format_hot_shows_rank_climb():
    result = format_hot(_VIEWS_FULL)
    assert "▲4 rank" in result


def test_format_hot_shows_category():
    result = format_hot(_VIEWS_FULL)
    assert "Sports" in result
    assert "Crypto" in result


def test_format_hot_empty_views_explains_need_for_scans():
    result = format_hot({"most_active": [], "fastest_rising": [],
                         "highest_liquidity": [], "highest_opportunity": [],
                         "scored_at": None})
    assert "two scans" in result


def test_format_hot_error():
    result = format_hot({"error": "connection refused"})
    assert "❌" in result


def test_format_hot_within_discord_limit():
    big = {k: v * 25 for k, v in _VIEWS_FULL.items() if isinstance(v, list)}
    big["scored_at"] = None
    result = format_hot(big)
    assert len(result) <= 2000
