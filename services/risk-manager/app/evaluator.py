from app.config import Settings
from app.models import EvaluationRequest, EvaluationResponse, RiskChecks
from app.position_sizing import calculate_contracts, calculate_max_price, estimate_taker_fee_cents


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
    fee_cents: int = 0,
) -> bool:
    """
    Verify that adding this trade keeps cumulative daily exposure within the
    configured limit.  today_exposure is the sum of already-approved trades
    for today (contracts × price, in cents).
    """
    new_cost = new_contracts * (new_price + max(0, fee_cents))
    return (today_exposure + new_cost) <= max_daily_loss


def check_bankroll(
    balance: int,
    contracts: int,
    price: int,
    max_position_percent: float,
    fee_cents: int = 0,
) -> bool:
    """Verify the proposed trade cost doesn't exceed the per-trade bankroll cap."""
    if contracts <= 0 or price <= 0:
        return False
    cost = contracts * (price + max(0, fee_cents))
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
    """Count consecutive *settled trading* losses, newest first.

    A rejected or dry-run evaluation is not an executed trade. Ignore those
    records entirely. Only settlement rows with a genuine integer realized
    P&L in cents can advance or reset the loss streak.

    The existing risk.trade_decisions table contains approvals/denials, not
    settlement P&L, so its rows cannot establish a loss. A verified settlement
    feed must be integrated before relying on this guard for live trading.
    """
    consecutive = 0
    for decision in recent_decisions:
        if decision.get("settled") is not True:
            continue
        pnl = decision.get("realized_pnl_cents")
        if type(pnl) is not int:
            continue
        if pnl < 0:
            consecutive += 1
            if consecutive >= max_consecutive_losses:
                return False
        else:
            # A settled winning or breakeven trade ends the loss streak.
            break
    return True


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
            f"Consecutive settled trading losses at limit "
            f"({settings.max_consecutive_losses})"
        )
    if not checks.executable_quote:
        parts.append("Executable ask quote unavailable or above safe limit")
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

    # Price must never exceed an actual executable quote. Missing quotes fail closed.
    theoretical_limit = calculate_max_price(request.probability, request.edge)
    quote = request.quoted_ask_cents
    quote_ok = quote is not None and quote <= theoretical_limit
    max_price = quote if quote_ok else 0
    fee_cents = estimate_taker_fee_cents(max_price, settings.taker_fee_rate) if quote_ok else 0
    contracts = calculate_contracts(
        balance, max_price, settings.max_position_percent, fee_cents=fee_cents
    )
    # Independently verify claimed expected value against fillable ask and fees.
    net_ev = request.probability - (max_price + fee_cents) / 100.0 if quote_ok else 0.0
    effective_ev = min(request.expected_value, net_ev)

    checks = RiskChecks(
        confidence=check_confidence(request.confidence, settings.min_confidence),
        expected_value=check_expected_value(
            effective_ev, settings.min_expected_value
        ),
        edge=check_edge(request.edge, settings.min_edge),
        open_positions=check_open_positions(open_count, settings.max_open_positions),
        daily_loss=check_daily_loss(
            today_exposure, contracts, max_price, settings.max_daily_loss, fee_cents
        ),
        bankroll=check_bankroll(
            balance, contracts, max_price, settings.max_position_percent, fee_cents
        ),
        consecutive_losses=check_consecutive_losses(
            recent_decisions, settings.max_consecutive_losses
        ),
        executable_quote=quote_ok,
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
        checks.executable_quote,
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
