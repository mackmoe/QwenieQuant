from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_url: str = "postgresql://localhost/prediction_platform"
    opportunity_engine_url: str = "http://opportunity-engine:8005"

    queue_max_size: int = 100
    queue_refresh_seconds: int = 30
    queue_expiration_buffer_seconds: int = 60
    queue_priority_weight: float = 0.70
    queue_wait_weight: float = 0.30

    workflow_enabled: bool = True
    workflow_interval_seconds: int = 30
    # Below this confidence the model's answer carries no direction:
    # P(Yes) is treated as 0.5 and no edge is claimed against the market.
    min_directional_confidence: float = 0.55
    dry_run: bool = True
    prediction_api_url: str = "http://prediction-api:8000"
    risk_manager_url: str = "http://risk-manager:8004"
    kalshi_connector_url: str = "http://kalshi-connector:8003"

    version: str = "0.1.0"

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
