from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Risk thresholds — all configurable via env vars
    min_confidence: float = 0.60
    min_expected_value: float = 0.01
    min_edge: float = 0.05
    max_position_percent: float = 5.0   # percent of account balance per trade
    max_open_positions: int = 10
    max_daily_loss: int = 10_000        # cents ($100.00)
    max_consecutive_losses: int = 5

    # Safe default: never approve a trade unless explicitly enabled
    dry_run: bool = True

    # Service connections
    kalshi_connector_url: str = "http://kalshi-connector:8003"
    postgres_url: str = ""
    http_timeout: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
