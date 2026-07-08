from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.client import KalshiClient, KalshiError
from app.events import Event, get_event, get_events
from app.health import HealthStatus, get_health
from app.markets import get_market, get_markets, get_orderbook
from app.orders import CancelOrderRequest, Order, PlaceOrderRequest, cancel_order, place_order
from app.positions import Account, Position, get_account, get_positions

router = APIRouter()

_client: Optional[KalshiClient] = None
_environment: str = "demo"


def set_client(client: KalshiClient, environment: str) -> None:
    global _client, _environment
    _client = client
    _environment = environment


def _require_client() -> KalshiClient:
    if _client is None:
        raise HTTPException(status_code=503, detail="Kalshi client not initialized")
    return _client


def _kalshi_exc(exc: KalshiError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    if _client is None:
        return HealthStatus(
            status="starting",
            credentials_configured=False,
            kalshi_reachable=False,
            environment=_environment,
        )
    return await get_health(_client, _environment)


@router.get("/account", response_model=Account)
async def account() -> Account:
    try:
        return await get_account(_require_client())
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.get("/markets")
async def markets(
    limit: int = Query(default=100, ge=1, le=20000),
    status: str = Query(default="active"),
    series_ticker: Optional[str] = Query(default=None),
    mve_filter: str = Query(default="exclude"),
) -> list:
    try:
        return await get_markets(
            _require_client(),
            limit=limit,
            status=status,
            series_ticker=series_ticker,
            mve_filter=mve_filter,
        )
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.get("/events", response_model=list[Event])
async def events(
    status: str = Query(default="open"),
) -> list[Event]:
    try:
        return await get_events(_require_client(), status=status)
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.get("/event/{event_ticker}", response_model=Event)
async def event(event_ticker: str) -> Event:
    try:
        return await get_event(_require_client(), event_ticker)
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.get("/market/{ticker}")
async def market(ticker: str):
    try:
        return await get_market(_require_client(), ticker)
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.get("/orderbook/{ticker}")
async def orderbook(ticker: str):
    try:
        return await get_orderbook(_require_client(), ticker)
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.get("/positions", response_model=list[Position])
async def positions() -> list[Position]:
    try:
        return await get_positions(_require_client())
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.post("/order", response_model=Order)
async def order(request: PlaceOrderRequest) -> Order:
    try:
        return await place_order(_require_client(), request)
    except KalshiError as exc:
        raise _kalshi_exc(exc)


@router.post("/cancel", response_model=Order)
async def cancel(request: CancelOrderRequest) -> Order:
    try:
        return await cancel_order(_require_client(), request.order_id)
    except KalshiError as exc:
        raise _kalshi_exc(exc)
