from pydantic import BaseModel

from app.client import KalshiClient


class Account(BaseModel):
    balance: int          # available cash in cents
    portfolio_value: int  # estimated open position value in cents (0 when unavailable)


class Position(BaseModel):
    ticker: str
    side: str     # "yes" or "no"
    quantity: int
    realized_pnl: int    # in cents
    unrealized_pnl: int  # in cents
    market_exposure: int  # in cents


def _normalize_position(raw: dict) -> Position:
    raw_qty = raw.get("position", 0)
    side = "no" if raw_qty < 0 else "yes"
    return Position(
        ticker=raw.get("ticker", ""),
        side=side,
        quantity=abs(raw_qty),
        realized_pnl=raw.get("realized_pnl", 0),
        unrealized_pnl=raw.get("unrealized_pnl", 0),
        market_exposure=raw.get("market_exposure", 0),
    )


async def get_account(client: KalshiClient) -> Account:
    data = await client.get("/portfolio/balance")
    return Account(
        balance=data.get("balance", 0),
        portfolio_value=data.get("portfolio_value", 0),
    )


async def get_positions(client: KalshiClient) -> list[Position]:
    data = await client.get("/portfolio/positions")
    return [
        _normalize_position(p)
        for p in data.get("market_positions", [])
    ]
