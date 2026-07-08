"""
Lightweight HTTP clients for the three platform services.

Each client wraps one service's API. Errors are caught and returned as
dicts with an "error" key so callers can format them without exception
handling scattered through the command layer.

check_reachable() is a separate helper for Ollama and SearXNG, which are
not platform services but need reachability probes for /status.
"""

import httpx


class ServiceClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http

    async def _get(self, path: str) -> dict:
        try:
            r = await self.http.get(f"{self.base_url}{path}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            return {"error": str(exc), "reachable": False}

    async def _post(self, path: str, data: dict, timeout: float | None = None) -> dict:
        try:
            kwargs: dict = {"json": data}
            if timeout is not None:
                kwargs["timeout"] = timeout
            r = await self.http.post(f"{self.base_url}{path}", **kwargs)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"HTTP {exc.response.status_code}",
                "status_code": exc.response.status_code,
            }
        except Exception as exc:
            return {"error": str(exc), "reachable": False}


class PredictionClient(ServiceClient):
    async def health(self) -> dict:
        return await self._get("/health")

    async def predict(self, question: str, category: str = "finance") -> dict:
        # Long timeout: qwen3:8b generates a thinking chain before the JSON
        # response and can take up to 5 minutes on CPU.
        return await self._post(
            "/predict",
            {"question": question, "category": category, "options": ["Yes", "No"]},
            timeout=330.0,
        )


class LearningClient(ServiceClient):
    async def health(self) -> dict:
        return await self._get("/health")

    async def analyze(self) -> dict:
        return await self._post("/analyze", {})


class ReflectionClient(ServiceClient):
    async def health(self) -> dict:
        return await self._get("/health")

    async def reflect(self, analysis_id: str) -> dict:
        return await self._post("/reflect", {"analysis_id": analysis_id})


class OpportunityClient(ServiceClient):
    async def health(self) -> dict:
        return await self._get("/health")

    async def get_opportunities(self, limit: int = 10) -> dict:
        return await self._get(f"/opportunities?limit={limit}")

    async def refresh(self) -> dict:
        return await self._post("/refresh", {})


class PredictionQueueClient(ServiceClient):
    async def health(self) -> dict:
        return await self._get("/health")

    async def get_stats(self) -> dict:
        """Return queue stats (by_state counts). Requests limit=1 to avoid large payloads."""
        return await self._get("/queue?limit=1")

    async def get_recent_completed(self, limit: int = 25) -> dict:
        return await self._get(f"/queue?state=COMPLETED&limit={limit}")

    async def run_workflow(self) -> dict:
        return await self._post("/run", {}, timeout=360.0)


class RiskManagerClient(ServiceClient):
    async def health(self) -> dict:
        return await self._get("/health")


async def check_reachable(http: httpx.AsyncClient, url: str) -> bool:
    """Ping a URL and return True when any non-5xx response is received."""
    try:
        r = await http.get(url, timeout=5.0)
        return r.status_code < 500
    except Exception:
        return False
