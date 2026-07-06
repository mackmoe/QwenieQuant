import logging
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class KalshiConnectorClient:
    """
    Thin wrapper around the kalshi-connector HTTP service.

    Returns plain dicts so the opportunity engine stays decoupled from
    the connector's model classes.
    """

    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = http

    async def get_markets(self, limit: int = 1000) -> list[dict]:
        """
        Fetch active markets from the kalshi-connector.
        Returns [] on any failure so callers degrade gracefully.
        """
        try:
            resp = await self._http.get(
                f"{self._base}/markets",
                params={"limit": limit, "status": "active"},
            )
            resp.raise_for_status()
            data = resp.json()
            markets = data if isinstance(data, list) else []
            logger.info("Fetched %d markets from kalshi-connector", len(markets))
            return markets
        except Exception as exc:
            logger.warning("kalshi-connector unavailable: %s", exc)
            return []

    async def is_reachable(self) -> bool:
        try:
            resp = await self._http.get(f"{self._base}/health")
            return resp.status_code < 500
        except Exception:
            return False
