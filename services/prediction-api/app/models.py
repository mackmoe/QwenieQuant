from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional
import uuid

from pydantic import BaseModel, Field


def _make_prediction_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"pred_{ts}_{suffix}"


class PredictionCategory(str, Enum):
    weather = "weather"
    sports = "sports"
    politics = "politics"
    finance = "finance"


class PredictionRequest(BaseModel):
    question: str = Field(..., min_length=10, max_length=500)
    category: PredictionCategory
    options: list[str] = Field(default=["Yes", "No"], min_length=2, max_length=10)
    context: dict = Field(default_factory=dict)
    resolution_date: Optional[date] = None
    market_id: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "Will the S&P 500 close above 5000 by end of Q1 2025?",
                    "category": "finance",
                    "options": ["Yes", "No"],
                    "context": {"current_value": 4900},
                    "resolution_date": "2025-03-31",
                }
            ]
        }
    }


class LLMPrediction(BaseModel):
    """Structured output expected from the model."""

    prediction: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    key_factors: list[str] = Field(default_factory=list)


class PredictionResponse(BaseModel):
    prediction_id: str = Field(default_factory=_make_prediction_id)
    question: str
    prediction: str
    confidence: float
    reasoning: str
    key_factors: list[str]
    model: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    search_context_used: bool = False
    sources: list[str] = Field(default_factory=list)


class HealthStatus(BaseModel):
    status: str
    ollama: bool
    version: str = "0.1.0"
