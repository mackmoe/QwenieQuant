"""
Kalshi Events — the discovery layer between Series and Markets.

Kalshi's hierarchy: Category → Series → Event → Market.
Event objects carry both `category` and `series_ticker`, making them the
cheapest way to resolve a market's category (markets only carry event_ticker).
"""

from typing import Optional

from pydantic import BaseModel

from app.client import KalshiClient


class Event(BaseModel):
    event_ticker: str
    series_ticker: Optional[str] = None
    category: Optional[str] = None
    title: Optional[str] = None


def _normalize_event(raw: dict) -> Event:
    return Event(
        event_ticker=raw.get("event_ticker", ""),
        series_ticker=raw.get("series_ticker"),
        category=raw.get("category"),
        title=raw.get("title"),
    )


async def get_events(
    client: KalshiClient,
    status: str = "open",
    max_pages: int = 40,
) -> list[Event]:
    """
    Fetch all events for the given status, following cursor pagination.

    max_pages caps the walk (40 pages × 200 = 8000 events) so a runaway
    cursor can never loop forever.
    """
    events: list[Event] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        params: dict = {"limit": 200, "status": status}
        if cursor:
            params["cursor"] = cursor
        data = await client.get("/events", params=params)
        page = data.get("events", [])
        events.extend(_normalize_event(e) for e in page)
        cursor = data.get("cursor")
        if not cursor or not page:
            break
    return events


async def get_event(client: KalshiClient, event_ticker: str) -> Event:
    data = await client.get(f"/events/{event_ticker}")
    return _normalize_event(data.get("event", data))
