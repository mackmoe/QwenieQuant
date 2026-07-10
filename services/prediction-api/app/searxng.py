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

    # Default: search.  Every prediction concerns a real-world future
    # outcome, which is time-sensitive by nature.  Category-agnostic on
    # purpose — Kalshi's taxonomy is open ("Sports", "Climate and Weather",
    # "Science and Technology", ...) and a hardcoded category list here
    # silently disabled search when the platform adopted Kalshi's names.
    return True


# ---------------------------------------------------------------------------
# Search query construction
# ---------------------------------------------------------------------------

# "Will Freddie Freeman record 1 or more?" → player prop
_PROP_RE = re.compile(r"^(?:will\s+)?(.+?)\s+record\s+[\d.]+\s+or more", re.IGNORECASE)
# "Will Milwaukee win?" / "Will X win the Y?" → competition outcome
_WIN_RE = re.compile(r"^(?:will\s+)?(.+?)\s+win\b", re.IGNORECASE)

_MARKET_CATEGORIES = ("crypto", "financ", "commodit", "econom")


def build_search_query(question: str, category: str) -> str:
    """
    Turn a prediction question into an effective web-search query.

    Raw questions make poor queries ("Will Milwaukee win?" retrieves
    nothing useful); the query needs the entity plus recency context.
    """
    q = question.strip().rstrip("?").strip()
    cat = (category or "").lower()

    m = _PROP_RE.match(q)
    if m:
        return f"{m.group(1)} stats today"

    m = _WIN_RE.match(q)
    if m:
        return f"{m.group(1)} game today"

    if q.lower().startswith("will "):
        q = q[5:]

    if any(term in cat for term in _MARKET_CATEGORIES):
        return f"{q} price today"
    if "sport" in cat:
        return f"{q} today"
    return f"{q} latest news"


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
