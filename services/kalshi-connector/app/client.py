import asyncio
import logging
import time
from urllib.parse import urlparse

import httpx

from app.authentication import build_auth_headers

logger = logging.getLogger(__name__)


class KalshiError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(KalshiError):
    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message, 401)


class RateLimitError(KalshiError):
    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, 429)


class MarketNotFoundError(KalshiError):
    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(f"{resource} not found", 404)


class InvalidOrderError(KalshiError):
    def __init__(self, message: str = "Invalid order") -> None:
        super().__init__(message, 400)


class ServiceUnavailableError(KalshiError):
    def __init__(self, message: str = "Kalshi service unavailable") -> None:
        super().__init__(message, 503)


class KalshiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        private_key_pem: str,
        http: httpx.AsyncClient,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._private_key_pem = private_key_pem
        self._http = http
        self._max_retries = max_retries
        self._path_prefix = urlparse(base_url).path.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self._api_key and self._private_key_pem)

    async def probe_reachable(self) -> bool:
        try:
            await self._http.get(self._base_url + "/markets?limit=1", timeout=5.0)
            return True
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> dict:
        return await self._request("POST", path, json=json)

    async def delete(self, path: str) -> dict:
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict:
        signed_path = self._path_prefix + path
        url = self._base_url + path

        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                headers = build_auth_headers(
                    method, signed_path, self._api_key, self._private_key_pem
                )
                response = await self._http.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "%s %s status=%d elapsed=%dms attempt=%d",
                    method,
                    path,
                    response.status_code,
                    elapsed_ms,
                    attempt,
                )

                status = response.status_code

                if status in (200, 201):
                    return response.json()

                if status == 401:
                    raise AuthenticationError()

                if status == 404:
                    raise MarketNotFoundError(path)

                if status == 400:
                    body = _safe_json(response)
                    detail = body.get("error", body.get("message", "Invalid request"))
                    raise InvalidOrderError(str(detail))

                if status == 429:
                    retry_after = float(
                        response.headers.get("Retry-After", 2**attempt)
                    )
                    if attempt < self._max_retries:
                        logger.warning(
                            "Rate limited on %s, retrying after %.1fs", path, retry_after
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError()

                if status >= 500:
                    if attempt < self._max_retries:
                        backoff = float(2**attempt)
                        logger.warning(
                            "Server error %d on %s, retry in %.0fs", status, path, backoff
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise ServiceUnavailableError(f"Kalshi returned {status}")

                raise KalshiError(f"Unexpected response {status}", status)

            except (AuthenticationError, MarketNotFoundError, InvalidOrderError):
                raise

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.warning(
                    "%s %s network error=%s elapsed=%dms attempt=%d",
                    method,
                    path,
                    exc,
                    elapsed_ms,
                    attempt,
                )
                if attempt < self._max_retries:
                    backoff = float(2**attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise ServiceUnavailableError(f"Network failure: {exc}")

        raise ServiceUnavailableError("All retries exhausted")


def _safe_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except Exception:
        return {}
