from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.client import KalshiClient


class PlaceOrderRequest(BaseModel):
    ticker: str
    side: str    # "yes" or "no"
    action: str  # "buy" or "sell"
    quantity: int
    price: int   # in cents (1–99)
    order_type: str = "limit"

    @field_validator("side")
    @classmethod
    def _validate_side(cls, v: str) -> str:
        if v not in ("yes", "no"):
            raise ValueError("side must be 'yes' or 'no'")
        return v

    @field_validator("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("action must be 'buy' or 'sell'")
        return v


class CancelOrderRequest(BaseModel):
    order_id: str


class Order(BaseModel):
    order_id: str
    ticker: str
    side: str
    action: str
    quantity: int
    price: int  # in cents
    order_type: str
    status: str
    filled_count: int = 0
    remaining_count: int = 0
    created_time: Optional[datetime] = None


def _normalize_order(raw: dict) -> Order:
    order = raw.get("order", raw)
    side = order.get("side", "yes")
    price_key = "yes_price" if side == "yes" else "no_price"
    price = order.get(price_key) or order.get("yes_price") or order.get("no_price") or 0
    created: Optional[datetime] = None
    raw_created = order.get("created_time")
    if raw_created:
        try:
            created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    return Order(
        order_id=order.get("order_id", ""),
        ticker=order.get("ticker", ""),
        side=side,
        action=order.get("action", "buy"),
        quantity=order.get("count", 0),
        price=price,
        order_type=order.get("type", "limit"),
        status=order.get("status", "unknown"),
        filled_count=order.get("filled_count", 0),
        remaining_count=order.get("remaining_count", 0),
        created_time=created,
    )


async def place_order(client: KalshiClient, request: PlaceOrderRequest) -> Order:
    price_key = "yes_price" if request.side == "yes" else "no_price"
    payload = {
        "ticker": request.ticker,
        "action": request.action,
        "type": request.order_type,
        "side": request.side,
        "count": request.quantity,
        price_key: request.price,
    }
    data = await client.post("/portfolio/orders", json=payload)
    return _normalize_order(data)


async def cancel_order(client: KalshiClient, order_id: str) -> Order:
    data = await client.delete(f"/portfolio/orders/{order_id}")
    return _normalize_order(data)
