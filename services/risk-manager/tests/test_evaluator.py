import pytest

from app.config import Settings
from app.evaluator import (
    check_direction_bias,
    check_bankroll,
    check_confidence,
    check_consecutive_losses,
    check_daily_loss,
    check_edge,
    check_expected_value,
    check_open_positions,
    run_evaluation,
)
from app.models import EvaluationRequest


def _settings(**overrides) -> Settings:
    defaults = dict(
        min_confidence=0.60,
        min_expected_value=0.01,
        min_edge=0.05,
        max_position_percent=5.0,
        max_open_positions=10,
        max_daily_loss=10_000,
        max_consecutive_losses=5,
        dry_run=False,
        kalshi_connector_url="http://kalshi:8003",
        postgres_url="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _request(**overrides) -> EvaluationRequest:
    defaults = dict(
        prediction_id="pred_test001",
        probability=0.65,
        confidence=0.75,
        expected_value=0.08,
        edge=0.10,
        market_ticker="TEST-TICKER",
        market_category="finance",
    )
    defaults.update(overrides)
    return EvaluationRequest(**defaults)


def _account(balance: int = 100_000) -> dict:
    return {"balance": balance, "portfolio_value": 0}


# ── check_confidence ────────────────────────────────────────────────────────


def test_confidence_passes_above_minimum():
    assert check_confidence(0.75, 0.60) is True


def test_confidence_passes_at_minimum():
    assert check_confidence(0.60, 0.60) is True


def test_confidence_fails_below_minimum():
    assert check_confidence(0.59, 0.60) is False


def test_confidence_fails_zero():
    assert check_confidence(0.0, 0.60) is False


# ── check_expected_value ────────────────────────────────────────────────────


def test_expected_value_passes():
    assert check_expected_value(0.05, 0.01) is True


def test_expected_value_passes_at_threshold():
    assert check_expected_value(0.01, 0.01) is True


def test_expected_value_fails():
    assert check_expected_value(0.005, 0.01) is False


def test_expected_value_fails_negative():
    assert check_expected_value(-0.10, 0.01) is False


# ── check_edge ──────────────────────────────────────────────────────────────


def test_edge_passes():
    assert check_edge(0.10, 0.05) is True


def test_edge_passes_at_minimum():
    assert check_edge(0.05, 0.05) is True


def test_edge_fails():
    assert check_edge(0.04, 0.05) is False


def test_edge_fails_negative():
    assert check_edge(-0.01, 0.05) is False


# ── check_open_positions ────────────────────────────────────────────────────


def test_open_positions_passes_when_below_limit():
    assert check_open_positions(5, 10) is True


def test_open_positions_passes_at_one_below_limit():
    assert check_open_positions(9, 10) is True


def test_open_positions_fails_at_limit():
    assert check_open_positions(10, 10) is False


def test_open_positions_fails_above_limit():
    assert check_open_positions(15, 10) is False


def test_open_positions_passes_with_zero():
    assert check_open_positions(0, 10) is True


# ── check_daily_loss ────────────────────────────────────────────────────────


def test_daily_loss_passes_when_under_limit():
    # today_exposure=5000, new=3*55=165, total=5165 <= 10000
    assert check_daily_loss(5_000, 3, 55, 10_000) is True


def test_daily_loss_passes_when_exactly_at_limit():
    # 3*55=165, today_exposure=9835, total=10000
    assert check_daily_loss(9_835, 3, 55, 10_000) is True


def test_daily_loss_fails_when_over_limit():
    # 3*55=165, today_exposure=9836, total=10001 > 10000
    assert check_daily_loss(9_836, 3, 55, 10_000) is False


def test_daily_loss_passes_with_zero_existing():
    assert check_daily_loss(0, 5, 50, 10_000) is True


def test_daily_loss_fails_single_trade_exceeds_limit():
    # 200 contracts * 55 = 11000 > 10000
    assert check_daily_loss(0, 200, 55, 10_000) is False


# ── check_bankroll ──────────────────────────────────────────────────────────


def test_bankroll_passes():
    # balance=100000, 5% = 5000, 90*55=4950 <= 5000
    assert check_bankroll(100_000, 90, 55, 5.0) is True


def test_bankroll_fails_zero_contracts():
    assert check_bankroll(100_000, 0, 55, 5.0) is False


def test_bankroll_fails_zero_price():
    assert check_bankroll(100_000, 10, 0, 5.0) is False


def test_bankroll_fails_when_cost_exceeds_allocation():
    # balance=100000, 5% = 5000, 100*55=5500 > 5000
    assert check_bankroll(100_000, 100, 55, 5.0) is False


def test_bankroll_passes_at_exact_allocation():
    # balance=100000, 5% = 5000, 10*50=500 <= 5000
    assert check_bankroll(100_000, 10, 50, 5.0) is True


# ── check_consecutive_losses ────────────────────────────────────────────────


def test_consecutive_losses_passes_no_history():
    assert check_consecutive_losses([], 5) is True


def test_consecutive_losses_passes_with_recent_approval():
    decisions = [{"approved": False}, {"approved": False}, {"approved": True}]
    assert check_consecutive_losses(decisions, 5) is True


def test_consecutive_losses_passes_below_limit():
    decisions = [{"approved": False}] * 4 + [{"approved": True}]
    assert check_consecutive_losses(decisions, 5) is True


def test_consecutive_losses_fails_at_limit():
    decisions = [{"approved": False}] * 5
    assert check_consecutive_losses(decisions, 5) is False


def test_consecutive_losses_fails_above_limit():
    decisions = [{"approved": False}] * 8
    assert check_consecutive_losses(decisions, 5) is False


def test_consecutive_losses_all_approved():
    decisions = [{"approved": True}] * 10
    assert check_consecutive_losses(decisions, 5) is True


# ── run_evaluation ──────────────────────────────────────────────────────────


def test_evaluate_approved_when_all_checks_pass():
    response = run_evaluation(
        _request(),
        _account(100_000),
        [],              # no open positions
        0,               # no daily exposure
        [],              # no prior decisions
        _settings(dry_run=False),
    )
    assert response.approved is True
    assert response.recommended_contracts is not None
    assert response.recommended_max_price is not None
    assert response.reason == "All configured risk criteria satisfied."


def test_evaluate_all_risk_checks_true_on_approval():
    response = run_evaluation(
        _request(),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=False),
    )
    assert response.risk_checks.confidence is True
    assert response.risk_checks.edge is True
    assert response.risk_checks.expected_value is True


def test_evaluate_denied_low_confidence():
    response = run_evaluation(
        _request(confidence=0.40),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=False, min_confidence=0.60),
    )
    assert response.approved is False
    assert response.risk_checks.confidence is False
    assert "Confidence" in response.reason


def test_evaluate_denied_low_expected_value():
    response = run_evaluation(
        _request(expected_value=-0.05),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=False),
    )
    assert response.approved is False
    assert response.risk_checks.expected_value is False


def test_evaluate_denied_low_edge():
    response = run_evaluation(
        _request(edge=0.01),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=False, min_edge=0.05),
    )
    assert response.approved is False
    assert response.risk_checks.edge is False
    assert "Edge" in response.reason


def test_evaluate_denied_too_many_positions():
    positions = [{"ticker": f"T{i}"} for i in range(10)]
    response = run_evaluation(
        _request(),
        _account(100_000),
        positions,
        0,
        [],
        _settings(dry_run=False, max_open_positions=10),
    )
    assert response.approved is False
    assert response.risk_checks.open_positions is False
    assert "limit" in response.reason.lower()


def test_evaluate_denied_daily_loss_exceeded():
    # today_exposure is already at limit
    response = run_evaluation(
        _request(),
        _account(100_000),
        [],
        10_000,          # already at max_daily_loss
        [],
        _settings(dry_run=False, max_daily_loss=10_000),
    )
    assert response.approved is False
    assert response.risk_checks.daily_loss is False


def test_evaluate_denied_zero_balance_fails_bankroll():
    response = run_evaluation(
        _request(),
        _account(0),     # no money
        [],
        0,
        [],
        _settings(dry_run=False),
    )
    assert response.approved is False
    assert response.risk_checks.bankroll is False


def test_evaluate_denied_consecutive_losses():
    decisions = [{"approved": False}] * 5
    response = run_evaluation(
        _request(),
        _account(100_000),
        [],
        0,
        decisions,
        _settings(dry_run=False, max_consecutive_losses=5),
    )
    assert response.approved is False
    assert response.risk_checks.consecutive_losses is False


def test_evaluate_dry_run_never_approves():
    response = run_evaluation(
        _request(),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=True),
    )
    assert response.approved is False
    assert "Dry-run" in response.reason


def test_evaluate_dry_run_includes_sizing_when_all_checks_pass():
    response = run_evaluation(
        _request(),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=True),
    )
    # All risk checks pass, so sizing should be populated
    assert response.recommended_contracts is not None
    assert response.recommended_max_price is not None


def test_evaluate_dry_run_no_sizing_when_checks_fail():
    response = run_evaluation(
        _request(confidence=0.10),  # fails confidence
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=True),
    )
    assert response.recommended_contracts is None
    assert response.recommended_max_price is None


def test_evaluate_all_checks_run_even_when_first_fails():
    # confidence fails, but all other checks should still be evaluated
    response = run_evaluation(
        _request(confidence=0.10, edge=0.01),  # both fail
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=False),
    )
    assert response.risk_checks.confidence is False
    assert response.risk_checks.edge is False


def test_evaluate_multiple_failures_reason_contains_multiple():
    response = run_evaluation(
        _request(confidence=0.10, edge=0.01),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=False),
    )
    assert "Confidence" in response.reason
    assert "Edge" in response.reason


def test_evaluate_no_contracts_when_denied():
    response = run_evaluation(
        _request(confidence=0.10),
        _account(100_000),
        [],
        0,
        [],
        _settings(dry_run=False),
    )
    assert response.recommended_contracts is None
    assert response.recommended_max_price is None


# ── check_direction_bias (YES-bias guard) ───────────────────────────────────


def test_direction_bias_yes_below_threshold_fails():
    assert check_direction_bias("yes", 0.65, 0.70) is False


def test_direction_bias_yes_at_threshold_passes():
    assert check_direction_bias("yes", 0.70, 0.70) is True


def test_direction_bias_no_prediction_always_passes():
    assert check_direction_bias("no", 0.10, 0.70) is True


def test_direction_bias_absent_direction_passes():
    assert check_direction_bias(None, 0.10, 0.70) is True


def test_direction_bias_case_insensitive():
    assert check_direction_bias("YES", 0.50, 0.70) is False
    assert check_direction_bias("  Yes ", 0.50, 0.70) is False


def test_run_evaluation_denies_low_confidence_yes():
    request = _request(prediction_direction="yes", confidence=0.65)
    result = run_evaluation(
        request, _account(), [], 0, [], _settings()
    )
    assert result.approved is False
    assert result.risk_checks.direction_bias is False
    assert "YES prediction confidence" in result.reason


def test_run_evaluation_approves_no_at_same_confidence():
    request = _request(prediction_direction="no", confidence=0.65)
    result = run_evaluation(
        request, _account(), [], 0, [], _settings()
    )
    assert result.risk_checks.direction_bias is True


def test_run_evaluation_approves_high_confidence_yes():
    request = _request(prediction_direction="yes", confidence=0.80)
    result = run_evaluation(
        request, _account(), [], 0, [], _settings()
    )
    assert result.risk_checks.direction_bias is True


def test_run_evaluation_backward_compatible_without_direction():
    result = run_evaluation(
        _request(), _account(), [], 0, [], _settings()
    )
    assert result.risk_checks.direction_bias is True
