from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel


class ScoredMarket(BaseModel):
    market_id: str          # = ticker (unique per market)
    ticker: str
    title: str
    priority_score: float   # 0.0 – 100.0; higher is better
    assigned_tier: int      # 0, 1, 2, or 3
    scoring_timestamp: datetime
    metadata: dict = {}     # per-factor breakdown for inspection


class OpportunitiesResponse(BaseModel):
    markets: list[ScoredMarket]
    total: int
    tier_counts: dict[str, int]
    scored_at: Optional[datetime]
    version: str = "0.1.0"


class RefreshResponse(BaseModel):
    status: str
    markets_scored: int
    tier_counts: dict[str, int]
    duration_ms: int


class HealthStatus(BaseModel):
    status: str             # "ok" | "degraded" | "starting"
    kalshi_connector: bool
    postgres: bool
    last_scan: Optional[datetime]
    markets_scored: int
    tier3_candidates: int
    dry_run_safe: bool = True   # this service never places trades
    version: str = "0.1.0"
