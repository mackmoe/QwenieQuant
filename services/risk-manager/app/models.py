from typing import Optional

from pydantic import BaseModel, field_validator


class EvaluationRequest(BaseModel):
    prediction_id: str
    probability: float
    confidence: float
    expected_value: float
    edge: float
    market_ticker: str
    market_category: str = "finance"

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


class EvaluationResponse(BaseModel):
    prediction_id: str
    approved: bool
    reason: str
    recommended_contracts: Optional[int] = None
    recommended_max_price: Optional[int] = None
    risk_checks: RiskChecks
