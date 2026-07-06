from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kalshi_api_key: str = ""
    kalshi_private_key: str = ""       # PEM content; use \n in env var for line breaks
    kalshi_private_key_path: str = ""  # alternative: filesystem path to PEM file
    kalshi_environment: str = "demo"   # "demo" or "production"
    http_timeout: float = 30.0
    max_retries: int = 3

    postgres_url: str = ""
    outcome_collection_enabled: bool = True
    outcome_poll_seconds: int = 300
    learning_engine_url: str = "http://learning-engine:8001"

    @field_validator("kalshi_private_key", mode="before")
    @classmethod
    def _unescape_newlines(cls, v: object) -> object:
        if isinstance(v, str):
            return v.replace("\\n", "\n")
        return v

    @property
    def base_url(self) -> str:
        if self.kalshi_environment == "production":
            return "https://trading-api.kalshi.com/trade-api/v2"
        return "https://demo-api.kalshi.co/trade-api/v2"

    def load_private_key_pem(self) -> str:
        if self.kalshi_private_key:
            return self.kalshi_private_key
        if self.kalshi_private_key_path:
            with open(self.kalshi_private_key_path) as fh:
                return fh.read()
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
