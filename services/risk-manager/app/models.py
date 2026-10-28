from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EvaluationRequest(BaseModel):
    prediction_id: str
    probability: float
    confidence: float
    expected_value: float
    edge: float
    market_ticker: str
    market_category: str = "Financials"
    # Model's predicted direction ("yes"/"no").  Optional for backward
    # compatibility; when omitted the direction-bias check passes.
    prediction_direction: Optional[str] = None
    # Executable quote for the direction being purchased, in cents.
    # None is treated as unavailable and cannot authorize a trade.
    quoted_ask_cents: Optional[int] = Field(default=None, ge=1, le=99)

    @field_validator("probability", "confidence")
    @classmethod
    def _must_be_probability(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Must be between 0.0 and 1.0")
        return v


class RiskChecks(BaseModel):
    confidence: bool = True
    expected_value: bool = True
    edge: bool = True
    open_positions: bool = True
    daily_loss: bool = True
    bankroll: bool = True
    consecutive_losses: bool = True
    direction_bias: bool = True
    executable_quote: bool = True


class EvaluationResponse(BaseModel):
    prediction_id: str
    approved: bool
    reason: str
    recommended_contracts: Optional[int] = None
    recommended_max_price: Optional[int] = None
    risk_checks: RiskChecks
