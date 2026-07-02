from datetime import datetime, timezone
from typing import Optional
import uuid

from pydantic import BaseModel, Field, computed_field


def _make_analysis_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"analysis_{ts}_{suffix}"


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
