from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.client import KalshiClient


class Market(BaseModel):
    ticker: str
    event_ticker: Optional[str] = None
    # Set on multivariate (MVE/parlay) markets — Kalshi's auto-generated
    # combination contracts.  Downstream consumers exclude these.
    mve_collection_ticker: Optional[str] = None
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
    count: int


class OrderBook(BaseModel):
    ticker: str
    yes: list[OrderBookLevel] = []
    no: list[OrderBookLevel] = []


def _dollars_to_cents(value) -> Optional[int]:
    """Convert a Kalshi dollars string/float (e.g. '0.6100') to integer cents."""
    if value in (None, ""):
        return None
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return None


def _price_cents(raw: dict, cent_key: str, dollar_key: str) -> Optional[int]:
    """
    Read a price in cents, accepting both API formats.

    The legacy trade-api returned integer cent fields (yes_bid); the current
    api.elections.kalshi.com returns dollar-string fields (yes_bid_dollars)
    and omits the cent fields entirely.
    """
    if raw.get(cent_key) is not None:
        return raw[cent_key]
    return _dollars_to_cents(raw.get(dollar_key))


def _int_fp(raw: dict, int_key: str, fp_key: str) -> int:
    """Read an integer count, accepting legacy int or current '_fp' string fields."""
    if raw.get(int_key) is not None:
        return raw[int_key]
    try:
        return int(float(raw.get(fp_key) or 0))
    except (TypeError, ValueError):
        return 0


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
        event_ticker=raw.get("event_ticker"),
        mve_collection_ticker=raw.get("mve_collection_ticker") or None,
        title=raw.get("title", raw.get("subtitle", "")),
        status=raw.get("status", "unknown"),
        yes_bid=_price_cents(raw, "yes_bid", "yes_bid_dollars"),
        yes_ask=_price_cents(raw, "yes_ask", "yes_ask_dollars"),
        no_bid=_price_cents(raw, "no_bid", "no_bid_dollars"),
        no_ask=_price_cents(raw, "no_ask", "no_ask_dollars"),
        volume=_int_fp(raw, "volume", "volume_fp"),
        open_interest=_int_fp(raw, "open_interest", "open_interest_fp"),
        close_time=close_time,
        result=raw_result if raw_result else None,
    )


def _normalize_levels(levels: list, dollars: bool) -> list[OrderBookLevel]:
    out: list[OrderBookLevel] = []
    for level in levels or []:
        if len(level) < 2:
            continue
        if dollars:
            price = _dollars_to_cents(level[0])
            if price is None:
                continue
            try:
                count = int(float(level[1]))
            except (TypeError, ValueError):
                continue
        else:
            price, count = level[0], level[1]
        out.append(OrderBookLevel(price=price, count=count))
    return out


def _normalize_orderbook(ticker: str, raw: dict) -> OrderBook:
    # Current API: {"orderbook_fp": {"yes_dollars": [["0.6100","136.00"],...]}}
    # Legacy API:  {"orderbook": {"yes": [[61, 136], ...], "no": [...]}}
    ob_fp = raw.get("orderbook_fp")
    if ob_fp is not None:
        return OrderBook(
            ticker=ticker,
            yes=_normalize_levels(ob_fp.get("yes_dollars"), dollars=True),
            no=_normalize_levels(ob_fp.get("no_dollars"), dollars=True),
        )
    ob = raw.get("orderbook", raw)
    return OrderBook(
        ticker=ticker,
        yes=_normalize_levels(ob.get("yes"), dollars=False),
        no=_normalize_levels(ob.get("no"), dollars=False),
    )


async def get_markets(
    client: KalshiClient,
    limit: int = 100,
    status: str = "active",
    series_ticker: Optional[str] = None,
    mve_filter: str = "exclude",
) -> list[Market]:
    # Kalshi API migration (trading-api → api.elections.kalshi.com) renamed
    # the status value "active" to "open".  Accept either for compatibility.
    api_status = "open" if status == "active" else status
    markets: list[Market] = []
    cursor: Optional[str] = None
    # Kalshi caps page size at 1000; follow the cursor until `limit` reached.
    while len(markets) < limit:
        page_size = min(1000, limit - len(markets))
        params: dict = {"limit": page_size, "status": api_status}
        # mve_filter is Kalshi's own param: "exclude" drops the tens of
        # thousands of auto-generated multivariate (parlay) markets that
        # otherwise dominate the listing.
        if mve_filter:
            params["mve_filter"] = mve_filter
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        data = await client.get("/markets", params=params)
        page = data.get("markets", [])
        markets.extend(_normalize_market(m) for m in page)
        cursor = data.get("cursor")
        if not cursor or not page:
            break
    return markets


async def get_market(client: KalshiClient, ticker: str) -> Market:
    data = await client.get(f"/markets/{ticker}")
    return _normalize_market(data.get("market", data))


async def get_orderbook(client: KalshiClient, ticker: str) -> OrderBook:
    data = await client.get(f"/markets/{ticker}/orderbook")
    return _normalize_orderbook(ticker, data)
