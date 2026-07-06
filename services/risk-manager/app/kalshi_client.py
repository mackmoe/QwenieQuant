import logging

import httpx

logger = logging.getLogger(__name__)


class KalshiConnectorClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    async def get_account(self) -> dict:
        try:
            response = await self._http.get(f"{self._base_url}/account")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("Failed to get account from Kalshi Connector: %s", exc)
            return {"balance": 0, "portfolio_value": 0, "error": str(exc)}

    async def get_positions(self) -> list[dict]:
        try:
            response = await self._http.get(f"{self._base_url}/positions")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("Failed to get positions from Kalshi Connector: %s", exc)
            return []

    async def is_reachable(self) -> bool:
        try:
            response = await self._http.get(
                f"{self._base_url}/health",
                timeout=5.0,
            )
            return response.status_code < 500
        except Exception:
            return False
