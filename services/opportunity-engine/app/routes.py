import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from app import scheduler
from app.health import get_health
from app.kalshi_client import KalshiConnectorClient
from app.models import HealthStatus, OpportunitiesResponse, RefreshResponse, ScoredMarket

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level dependencies (injected at startup, overridden in tests)
# ---------------------------------------------------------------------------

_pool = None
_http: Optional[httpx.AsyncClient] = None
_settings = None


def set_dependencies(pool, http, settings) -> None:
    global _pool, _http, _settings
    _pool = pool
    _http = http
    _settings = settings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    if _http is None or _settings is None:
        return HealthStatus(
            status="starting",
            kalshi_connector=False,
            postgres=False,
            last_scan=None,
            markets_scored=0,
            tier3_candidates=0,
        )
    kalshi = KalshiConnectorClient(_settings.kalshi_connector_url, _http)
    return await get_health(_pool, kalshi)


@router.get("/opportunities", response_model=OpportunitiesResponse)
async def get_opportunities(
    tier: Optional[int] = Query(None, ge=0, le=3, description="Filter by tier (0–3)"),
    limit: Optional[int] = Query(None, ge=1, le=1000),
) -> OpportunitiesResponse:
    """
    Return all currently ranked markets, sorted by priority_score descending.
    Optional ?tier= filter and ?limit= cap.
    """
    last_scan, markets = scheduler.get_state()

    if tier is not None:
        markets = [m for m in markets if m.assigned_tier == tier]
    if limit is not None:
        markets = markets[:limit]

    _, all_markets = scheduler.get_state()
    tier_counts = scheduler._tier_counts(all_markets)

    return OpportunitiesResponse(
        markets=markets,
        total=len(markets),
        tier_counts=tier_counts,
        scored_at=last_scan,
    )


@router.get("/opportunities/top", response_model=OpportunitiesResponse)
async def get_top_opportunities(
    limit: Optional[int] = Query(None, ge=1, le=200),
) -> OpportunitiesResponse:
    """Return only Tier 3 markets — the deep-reasoning candidates."""
    last_scan, markets = scheduler.get_state()

    top = [m for m in markets if m.assigned_tier == 3]
    if limit is not None:
        top = top[:limit]

    _, all_markets = scheduler.get_state()
    tier_counts = scheduler._tier_counts(all_markets)

    return OpportunitiesResponse(
        markets=top,
        total=len(top),
        tier_counts=tier_counts,
        scored_at=last_scan,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh() -> RefreshResponse:
    """Trigger an immediate scoring pass outside the scheduled interval."""
    if _http is None or _settings is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    tiered, duration_ms = await scheduler.run_scan(_http, _settings, _pool)
    tier_counts = scheduler._tier_counts(tiered)

    return RefreshResponse(
        status="ok",
        markets_scored=len(tiered),
        tier_counts=tier_counts,
        duration_ms=duration_ms,
    )
