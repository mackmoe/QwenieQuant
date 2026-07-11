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


def _view_entry(m: ScoredMarket) -> dict:
    meta = m.metadata
    return {
        "ticker": m.ticker,
        "title": m.title,
        "priority_score": m.priority_score,
        "assigned_tier": m.assigned_tier,
        "category": meta.get("category"),
        "volume": meta.get("volume"),
        "volume_delta": meta.get("volume_delta"),
        "price_delta": meta.get("price_delta"),
        "open_interest": meta.get("open_interest"),
        "spread": meta.get("spread"),
        "rank": meta.get("rank"),
        "rank_delta": meta.get("rank_delta"),
    }


@router.get("/opportunities/by-category")
async def get_best_by_category() -> dict:
    """
    The single highest-priority market in every Kalshi category.

    Markets are already sorted by Market Interest Score; the first market
    seen per category is that category's best.  Markets whose event could
    not be resolved to a category are grouped under "Other".
    """
    last_scan, markets = scheduler.get_state()

    best: dict[str, ScoredMarket] = {}
    for m in markets:
        category = m.metadata.get("category") or "Other"
        if category not in best:
            best[category] = m

    entries = [
        {
            **_view_entry(m),
            "category": category,  # after spread: keeps "Other" for uncategorized
            "days_remaining": m.metadata.get("days_remaining"),
        }
        for category, m in best.items()
    ]
    # Strongest categories first
    entries.sort(key=lambda e: e["priority_score"], reverse=True)

    return {
        "categories": entries,
        "scored_at": last_scan.isoformat() if last_scan else None,
    }


@router.get("/views")
async def get_views(
    limit: int = Query(default=5, ge=1, le=25),
) -> dict:
    """
    Market Interest views computed from the latest scan:

      most_active         largest volume gain since the previous scan
      fastest_rising      largest mid-price climb since the previous scan
      highest_liquidity   deepest open interest (tight spread as tiebreaker)
      highest_opportunity top Market Interest Score (priority_score)
    """
    last_scan, markets = scheduler.get_state()

    def _meta(m: ScoredMarket, key: str, default=0):
        v = m.metadata.get(key)
        return v if v is not None else default

    most_active = sorted(
        (m for m in markets if _meta(m, "volume_delta") > 0),
        key=lambda m: _meta(m, "volume_delta"),
        reverse=True,
    )[:limit]

    fastest_rising = sorted(
        (m for m in markets if _meta(m, "price_delta", 0.0) > 0),
        key=lambda m: _meta(m, "price_delta", 0.0),
        reverse=True,
    )[:limit]

    highest_liquidity = sorted(
        markets,
        key=lambda m: (_meta(m, "open_interest"), -_meta(m, "spread", 99)),
        reverse=True,
    )[:limit]

    highest_opportunity = markets[:limit]  # already sorted by priority_score

    return {
        "most_active": [_view_entry(m) for m in most_active],
        "fastest_rising": [_view_entry(m) for m in fastest_rising],
        "highest_liquidity": [_view_entry(m) for m in highest_liquidity],
        "highest_opportunity": [_view_entry(m) for m in highest_opportunity],
        "scored_at": last_scan.isoformat() if last_scan else None,
    }


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
