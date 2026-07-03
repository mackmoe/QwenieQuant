from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.client import KalshiClient


class Market(BaseModel):
    ticker: str
    title: str
    status: str
    yes_bid: Optional[int] = None
    yes_ask: Optional[int] = None
    no_bid: Optional[int] = None
    no_ask: Optional[int] = None
    volume: int = 0
    open_interest: int = 0
    close_time: Optional[datetime] = None
    result: Optional[str] = None


class OrderBookLevel(BaseModel):
    price: int
    quantity: int


class OrderBook(BaseModel):
    ticker: str
    yes: list[OrderBookLevel] = []
    no: list[OrderBookLevel] = []


def _normalize_market(raw: dict) -> Market:
    raw_result = raw.get("result") or None
    close_time: Optional[datetime] = None
    raw_close = raw.get("close_time")
    if raw_close:
        try:
            close_time = datetime.fromisoformat(raw_close.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    return Market(
        ticker=raw.get("ticker", ""),
        title=raw.get("title", raw.get("subtitle", "")),
        status=raw.get("status", "unknown"),
        yes_bid=raw.get("yes_bid"),
        yes_ask=raw.get("yes_ask"),
        no_bid=raw.get("no_bid"),
        no_ask=raw.get("no_ask"),
        volume=raw.get("volume", 0),
        open_interest=raw.get("open_interest", 0),
        close_time=close_time,
        result=raw_result if raw_result else None,
    )


def _normalize_orderbook(ticker: str, raw: dict) -> OrderBook:
    ob = raw.get("orderbook", raw)
    yes_levels = [
        OrderBookLevel(price=level[0], quantity=level[1])
        for level in ob.get("yes", [])
        if len(level) >= 2
    ]
    no_levels = [
        OrderBookLevel(price=level[0], quantity=level[1])
        for level in ob.get("no", [])
        if len(level) >= 2
    ]
    return OrderBook(ticker=ticker, yes=yes_levels, no=no_levels)


async def get_markets(
    client: KalshiClient,
    limit: int = 100,
    status: str = "active",
    series_ticker: Optional[str] = None,
) -> list[Market]:
    params: dict = {"limit": limit, "status": status}
    if series_ticker:
        params["series_ticker"] = series_ticker
    data = await client.get("/markets", params=params)
    return [_normalize_market(m) for m in data.get("markets", [])]


async def get_market(client: KalshiClient, ticker: str) -> Market:
    data = await client.get(f"/markets/{ticker}")
    return _normalize_market(data.get("market", data))


async def get_orderbook(client: KalshiClient, ticker: str) -> OrderBook:
    data = await client.get(f"/markets/{ticker}/orderbook")
    return _normalize_orderbook(ticker, data)
