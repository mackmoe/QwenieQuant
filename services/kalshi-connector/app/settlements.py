from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.client import KalshiClient


class Settlement(BaseModel):
    ticker: str
    revenue: int  # in cents
    settled_time: Optional[datetime] = None
    yes_count: int = 0
    no_count: int = 0


def _normalize_settlement(raw: dict) -> Settlement:
    settled: Optional[datetime] = None
    raw_settled = raw.get("settled_time")
    if raw_settled:
        try:
            settled = datetime.fromisoformat(raw_settled.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    return Settlement(
        ticker=raw.get("ticker", ""),
        revenue=raw.get("revenue", 0),
        settled_time=settled,
        yes_count=raw.get("yes_count", 0),
        no_count=raw.get("no_count", 0),
    )


async def get_settlements(client: KalshiClient) -> list[Settlement]:
    data = await client.get("/portfolio/settlements")
    return [_normalize_settlement(s) for s in data.get("settlements", [])]
