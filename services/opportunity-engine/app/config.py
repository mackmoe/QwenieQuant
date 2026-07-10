from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Scheduler
    discovery_interval_seconds: int = 300  # 5 minutes

    # Tier thresholds
    max_tier2_markets: int = 100   # top ~20-40% of discovered markets
    max_tier3_markets: int = 30    # top 10-30 markets for deep reasoning
    min_priority_score: float = 5.0  # markets below this stay at tier 1

    # Ingest gate — markets failing these checks are dropped before scoring,
    # persistence, and snapshots (the bulk of listed markets are inactive).
    ingest_min_volume: int = 1          # drop markets with volume below this
    ingest_require_quote: bool = True   # drop markets without a two-sided book

    # Scoring normalization constants
    volume_normalization: float = 10_000.0     # volume at which volume_score = 1.0
    liquidity_normalization: float = 5_000.0   # open_interest at which score = 1.0
    spread_normalization: float = 30.0         # spread (cents) at which score = 0.0

    # Momentum normalization (deltas measured between consecutive scans)
    volume_momentum_normalization: float = 500.0     # contracts/scan for score 1.0
    price_momentum_normalization: float = 10.0       # mid-price cents/scan for 1.0
    liquidity_momentum_normalization: float = 500.0  # OI change/scan for 1.0

    # Scoring weights (need not sum to 1 — normalized internally)
    weight_time: float = 0.30
    weight_volume: float = 0.25
    weight_spread: float = 0.20
    weight_liquidity: float = 0.15
    weight_activity: float = 0.10
    # Momentum weights (Market Interest Score components; 0 disables momentum)
    weight_volume_momentum: float = 0.20
    weight_price_momentum: float = 0.10
    weight_liquidity_momentum: float = 0.10

    # Series-performance feedback: resolved prediction accuracy per series
    # (trailing window) feeds the score, so series where the model has a
    # proven record rise and proven-bad series sink.  0 disables feedback.
    weight_series_performance: float = 0.40
    series_perf_min_resolved: int = 20   # min resolved outcomes to trust a series
    series_perf_window_days: int = 30    # trailing window for the accuracy stat

    # Snapshot history for momentum (pruned beyond this window)
    snapshot_retention_days: int = 7
    # market_scores rows not refreshed within this window are pruned
    score_retention_days: int = 7

    # Infrastructure
    kalshi_connector_url: str = "http://kalshi-connector:8003"
    kalshi_market_limit: int = 6000  # markets to fetch per scan (paginated; MVE parlays dominate early pages)
    postgres_url: str = ""
    http_timeout: float = 30.0

    # Prediction Queue publishing
    prediction_queue_url: str = "http://prediction-queue:8006"
    publish_to_queue: bool = True
    queue_publish_batch_size: int = 30

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
