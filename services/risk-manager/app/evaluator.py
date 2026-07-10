from app.config import Settings
from app.models import EvaluationRequest, EvaluationResponse, RiskChecks
from app.position_sizing import calculate_contracts, calculate_max_price


# ── Individual rule checks (pure functions, independently testable) ─────────


def check_confidence(confidence: float, min_confidence: float) -> bool:
    return confidence >= min_confidence


def check_expected_value(expected_value: float, min_expected_value: float) -> bool:
    return expected_value >= min_expected_value


def check_edge(edge: float, min_edge: float) -> bool:
    return edge >= min_edge


def check_open_positions(open_count: int, max_open_positions: int) -> bool:
    """Allow the trade only when there is room for at least one more position."""
    return open_count < max_open_positions


def check_daily_loss(
    today_exposure: int,
    new_contracts: int,
    new_price: int,
    max_daily_loss: int,
) -> bool:
    """
    Verify that adding this trade keeps cumulative daily exposure within the
    configured limit.  today_exposure is the sum of already-approved trades
    for today (contracts × price, in cents).
    """
    new_cost = new_contracts * new_price
    return (today_exposure + new_cost) <= max_daily_loss


def check_bankroll(
    balance: int,
    contracts: int,
    price: int,
    max_position_percent: float,
) -> bool:
    """Verify the proposed trade cost doesn't exceed the per-trade bankroll cap."""
    if contracts <= 0 or price <= 0:
        return False
    cost = contracts * price
    allowed = balance * max_position_percent / 100
    return cost <= allowed


def check_direction_bias(
    prediction_direction: str | None,
    confidence: float,
    min_yes_confidence: float,
) -> bool:
    """
    YES predictions must clear a higher confidence bar than NO predictions.

    Resolved history shows mid-confidence YES calls performing far below
    50% while NO calls at the same confidence hold up.  Absent direction
    passes (backward compatibility with older callers).
    """
    if prediction_direction is None:
        return True
    if prediction_direction.strip().lower() != "yes":
        return True
    return confidence >= min_yes_confidence


def check_consecutive_losses(
    recent_decisions: list[dict],
    max_consecutive_losses: int,
) -> bool:
    """
    Count consecutive denied evaluations (newest first) and check against the
    configured limit.  A streak of denials signals the prediction system may
    be producing consistently low-quality predictions.
    """
    consecutive = 0
    for d in recent_decisions:
        if not d.get("approved", True):
            consecutive += 1
        else:
            break
    return consecutive < max_consecutive_losses


# ── Combined evaluation ────────────────────────────────────────────────────


def _denial_reason(
    request: EvaluationRequest,
    checks: RiskChecks,
    settings: Settings,
    open_count: int,
) -> str:
    parts: list[str] = []
    if not checks.confidence:
        parts.append(
            f"Confidence {request.confidence:.2f} below minimum {settings.min_confidence:.2f}"
        )
    if not checks.expected_value:
        parts.append(
            f"Expected value {request.expected_value:.4f} below "
            f"minimum {settings.min_expected_value:.4f}"
        )
    if not checks.edge:
        parts.append(
            f"Edge {request.edge:.4f} below minimum {settings.min_edge:.4f}"
        )
    if not checks.open_positions:
        parts.append(
            f"Open positions at limit ({open_count}/{settings.max_open_positions})"
        )
    if not checks.daily_loss:
        parts.append("Daily exposure limit reached")
    if not checks.bankroll:
        parts.append("Insufficient bankroll for position sizing")
    if not checks.consecutive_losses:
        parts.append(
            f"Consecutive denied evaluations at limit "
            f"({settings.max_consecutive_losses})"
        )
    if not checks.direction_bias:
        parts.append(
            f"YES prediction confidence {request.confidence:.2f} below "
            f"YES-specific minimum {settings.min_yes_confidence:.2f}"
        )
    return "; ".join(parts) if parts else "Risk criteria not satisfied."


def run_evaluation(
    request: EvaluationRequest,
    account: dict,
    positions: list[dict],
    today_exposure: int,
    recent_decisions: list[dict],
    settings: Settings,
) -> EvaluationResponse:
    balance = account.get("balance", 0)
    open_count = len(positions)

    max_price = calculate_max_price(request.probability, request.edge)
    contracts = calculate_contracts(balance, max_price, settings.max_position_percent)

    checks = RiskChecks(
        confidence=check_confidence(request.confidence, settings.min_confidence),
        expected_value=check_expected_value(
            request.expected_value, settings.min_expected_value
        ),
        edge=check_edge(request.edge, settings.min_edge),
        open_positions=check_open_positions(open_count, settings.max_open_positions),
        daily_loss=check_daily_loss(
            today_exposure, contracts, max_price, settings.max_daily_loss
        ),
        bankroll=check_bankroll(
            balance, contracts, max_price, settings.max_position_percent
        ),
        consecutive_losses=check_consecutive_losses(
            recent_decisions, settings.max_consecutive_losses
        ),
        direction_bias=check_direction_bias(
            request.prediction_direction,
            request.confidence,
            settings.min_yes_confidence,
        ),
    )

    all_passed = all([
        checks.confidence,
        checks.expected_value,
        checks.edge,
        checks.open_positions,
        checks.daily_loss,
        checks.bankroll,
        checks.consecutive_losses,
        checks.direction_bias,
    ])

    if settings.dry_run:
        return EvaluationResponse(
            prediction_id=request.prediction_id,
            approved=False,
            reason="Dry-run mode active: evaluation completed but trade not approved.",
            recommended_contracts=contracts if all_passed else None,
            recommended_max_price=max_price if all_passed else None,
            risk_checks=checks,
        )

    if all_passed:
        return EvaluationResponse(
            prediction_id=request.prediction_id,
            approved=True,
            reason="All configured risk criteria satisfied.",
            recommended_contracts=contracts,
            recommended_max_price=max_price,
            risk_checks=checks,
        )

    return EvaluationResponse(
        prediction_id=request.prediction_id,
        approved=False,
        reason=_denial_reason(request, checks, settings, open_count),
        recommended_contracts=None,
        recommended_max_price=None,
        risk_checks=checks,
    )
