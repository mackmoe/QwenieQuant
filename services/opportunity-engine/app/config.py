from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Scheduler
    discovery_interval_seconds: int = 300  # 5 minutes

    # Tier thresholds
    max_tier2_markets: int = 100   # top ~20-40% of discovered markets
    max_tier3_markets: int = 30    # top 10-30 markets for deep reasoning
    min_priority_score: float = 5.0  # markets below this stay at tier 1

    # Category filter (future use — connector doesn't expose category yet)
    supported_categories: str = "weather,sports,politics,finance"

    # Scoring normalization constants
    volume_normalization: float = 10_000.0     # volume at which volume_score = 1.0
    liquidity_normalization: float = 5_000.0   # open_interest at which score = 1.0
    spread_normalization: float = 30.0         # spread (cents) at which score = 0.0

    # Scoring weights (need not sum to 1 — normalized internally)
    weight_time: float = 0.30
    weight_volume: float = 0.25
    weight_spread: float = 0.20
    weight_liquidity: float = 0.15
    weight_activity: float = 0.10

    # Infrastructure
    kalshi_connector_url: str = "http://kalshi-connector:8003"
    kalshi_market_limit: int = 6000  # markets to fetch per scan (paginated; MVE parlays dominate early pages)
    postgres_url: str = ""
    http_timeout: float = 30.0

    # Prediction Queue publishing
    prediction_queue_url: str = "http://prediction-queue:8006"
    publish_to_queue: bool = True
    queue_publish_batch_size: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def supported_categories_list(self) -> list[str]:
        return [c.strip() for c in self.supported_categories.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
