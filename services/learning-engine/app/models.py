from datetime import datetime, timezone
from typing import Optional
import uuid

from pydantic import BaseModel, Field, computed_field


def _make_analysis_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"analysis_{ts}_{suffix}"


# ---------------------------------------------------------------------------
# Diagnostic sub-models (SPEC-030)
# ---------------------------------------------------------------------------


class CategoryStat(BaseModel):
    category: str
    count: int
    resolved: int
    accuracy: Optional[float] = None
    average_confidence: Optional[float] = None


class DirectionStat(BaseModel):
    count: int
    resolved: int
    accuracy: Optional[float] = None
    average_confidence: Optional[float] = None


class YesNoAnalysis(BaseModel):
    yes: DirectionStat
    no: DirectionStat


class ConfidenceBucket(BaseModel):
    label: str
    range_low: float
    range_high: float
    count: int
    resolved: int
    accuracy: Optional[float] = None


class SearchEffectiveness(BaseModel):
    with_search_count: int
    without_search_count: int
    with_search_accuracy: Optional[float] = None
    without_search_accuracy: Optional[float] = None
    with_search_confidence: Optional[float] = None
    without_search_confidence: Optional[float] = None
    accuracy_delta: Optional[float] = None


class RankingTier(BaseModel):
    label: str
    min_score: float
    max_score: float
    count: int
    resolved: int
    accuracy: Optional[float] = None
    average_confidence: Optional[float] = None


class RiskEffectiveness(BaseModel):
    approved_count: int
    approved_resolved: int
    approved_accuracy: Optional[float] = None
    rejected_count: int
    rejected_resolved: int
    rejected_accuracy: Optional[float] = None


class WeeklyDriftPoint(BaseModel):
    week: str
    count: int
    resolved: int
    accuracy: Optional[float] = None
    average_confidence: Optional[float] = None


class ModelStat(BaseModel):
    model: str
    count: int
    resolved: int
    accuracy: Optional[float] = None
    average_confidence: Optional[float] = None
    average_execution_ms: Optional[float] = None


class Diagnostics(BaseModel):
    category_performance: list[CategoryStat] = Field(default_factory=list)
    yes_no_analysis: Optional[YesNoAnalysis] = None
    confidence_buckets: list[ConfidenceBucket] = Field(default_factory=list)
    search_effectiveness: Optional[SearchEffectiveness] = None
    ranking_tiers: list[RankingTier] = Field(default_factory=list)
    risk_effectiveness: Optional[RiskEffectiveness] = None
    weekly_drift: list[WeeklyDriftPoint] = Field(default_factory=list)
    model_performance: list[ModelStat] = Field(default_factory=list)
    top_failures: list[str] = Field(default_factory=list)
    top_successes: list[str] = Field(default_factory=list)


class AnalysisRequest(BaseModel):
    limit: int = Field(default=250, ge=1, le=10000)
    since: Optional[datetime] = None
    until: Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"limit": 100},
                {"since": "2025-01-01T00:00:00Z", "until": "2025-12-31T23:59:59Z"},
            ]
        }
    }


class AnalysisSummary(BaseModel):
    analysis_id: str = Field(default_factory=_make_analysis_id)
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    time_range_start: Optional[datetime] = None
    time_range_end: Optional[datetime] = None
    predictions_analyzed: int
    outcomes_available: int
    accuracy: Optional[float] = None
    average_confidence: Optional[float] = None
    average_execution_ms: Optional[float] = None
    model_breakdown: dict[str, int] = Field(default_factory=dict)
    category_breakdown: dict[str, int] = Field(default_factory=dict)
    observations: list[str] = Field(default_factory=list)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)

    @computed_field
    @property
    def time_range(self) -> str:
        if self.time_range_start and self.time_range_end:
            return (
                f"{self.time_range_start.date()} to {self.time_range_end.date()}"
            )
        if self.time_range_start:
            return f"since {self.time_range_start.date()}"
        if self.time_range_end:
            return f"until {self.time_range_end.date()}"
        return "all time"


class HealthStatus(BaseModel):
    status: str
    postgres: bool
    version: str = "0.1.0"
