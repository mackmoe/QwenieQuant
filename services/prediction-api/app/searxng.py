"""
SearXNG integration — search decision and retrieval.

Search policy is deterministic: the Prediction API decides whether current
information is needed based on the question text and category.  The model
is never asked whether it wants to search.
"""

import logging
import re
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stable-fact exemptions — checked before any keyword/category logic.
# Questions matching these patterns never trigger search even when the
# category or keywords would otherwise suggest it.
# ---------------------------------------------------------------------------
_STABLE_PATTERNS: list[str] = [
    "sun rise",
    "sunrise",
    "sunset",
    "moon rise",
    "moonrise",
    "moonset",
    "is gravity",
    "is the earth",
    "speed of light",
    "is water wet",
    "is blood",
    "will the sun",
    "will the moon",
    "will the earth",
    "history of",
    "who invented",
    "when was",
    "who discovered",
]

# Matches bare arithmetic: "7 × 9", "2 + 2", "100 / 5", etc.
_ARITHMETIC_RE = re.compile(r"\d\s*[+\-×x\*÷/]\s*\d")

# ---------------------------------------------------------------------------
# Time-sensitive keyword triggers.
# ---------------------------------------------------------------------------
_TIME_KEYWORDS: list[str] = [
    "today",
    "tonight",
    "tomorrow",
    "this week",
    "this month",
    "this year",
    "latest",
    "current",
    "recent",
    "right now",
    "upcoming",
    "breaking",
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "crypto",
    "cryptocurrency",
    "stock price",
    "stock market",
    "s&p 500",
    "s&p500",
    "nasdaq",
    "dow jones",
    "oil price",
    "gold price",
    "interest rate",
    "inflation",
    "gdp",
]


def needs_search(question: str, category: str) -> bool:
    """
    Return True if the question requires current information from SearXNG.

    Decision is deterministic — based on question text and category only.
    The model is never consulted.
    """
    q = question.lower()

    # Stable scientific/astronomical facts are never searchable.
    for pattern in _STABLE_PATTERNS:
        if pattern in q:
            return False

    # Arithmetic operations never need current data.
    if _ARITHMETIC_RE.search(q):
        return False

    # Explicit time-sensitivity keywords always trigger search.
    for kw in _TIME_KEYWORDS:
        if kw in q:
            return True

    # Category defaults: all four platform categories concern time-sensitive outcomes.
    # weather → forecast, not historical; sports → game outcomes; politics → elections;
    # finance → market prices.
    if category in ("weather", "sports", "politics", "finance"):
        return True

    return False


# ---------------------------------------------------------------------------
# Search result
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str


# ---------------------------------------------------------------------------
# SearXNG query
# ---------------------------------------------------------------------------


async def search(query: str) -> list[SearchResult]:
    """
    Query SearXNG and return up to searxng_max_results results.

    Returns an empty list if SearXNG is unreachable, times out, or returns
    no usable results.  Callers must not treat an empty list as an error.
    """
    settings = get_settings()
    params = {
        "q": query,
        "format": "json",
        "language": "en",
        "categories": "general",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.searxng_timeout) as client:
            response = await client.get(
                f"{settings.searxng_url}/search", params=params
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("SearXNG query timed out after %.1fs — skipping search", settings.searxng_timeout)
        return []
    except Exception as exc:
        logger.warning("SearXNG unavailable: %s — skipping search", exc)
        return []

    results: list[SearchResult] = []
    for item in data.get("results", [])[: settings.searxng_max_results]:
        title = (item.get("title") or "").strip()
        snippet = (item.get("content") or "").strip()
        url = (item.get("url") or "").strip()
        if snippet:
            results.append(SearchResult(title=title, snippet=snippet, url=url))

    if not results:
        logger.debug("SearXNG returned no usable results for query: %r", query)

    return results
