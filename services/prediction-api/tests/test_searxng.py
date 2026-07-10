"""
Tests for SearXNG search decision logic and retrieval.

All HTTP calls are mocked — no real SearXNG server required.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.searxng import SearchResult, needs_search, search


# ── needs_search: questions that SHOULD trigger search ───────────────────────


def test_weather_category_triggers_search():
    assert needs_search("Will it be cloudy this weekend?", "weather") is True


def test_sports_category_triggers_search():
    assert needs_search("Which team will finish first in the standings?", "sports") is True


def test_politics_category_triggers_search():
    assert needs_search("Which party will gain seats in parliament?", "politics") is True


def test_finance_category_triggers_search():
    assert needs_search("Will the index recover by year end?", "finance") is True


def test_today_keyword_triggers_search():
    assert needs_search("Will it rain in Dallas today?", "weather") is True


def test_tonight_keyword_triggers_search():
    assert needs_search("Will the Yankees win tonight?", "sports") is True


def test_tomorrow_keyword_triggers_search():
    assert needs_search("Will Dallas reach 100°F tomorrow?", "weather") is True


def test_this_week_keyword_triggers_search():
    assert needs_search("Will the market recover this week?", "finance") is True


def test_this_month_keyword_triggers_search():
    assert needs_search("Will Bitcoin close above $120,000 this month?", "finance") is True


def test_latest_keyword_triggers_search():
    assert needs_search("What is the latest update on interest rates?", "finance") is True


def test_current_keyword_triggers_search():
    assert needs_search("What is the current status of the trade deal?", "politics") is True


def test_bitcoin_keyword_triggers_search():
    assert needs_search("Will bitcoin reach $200k?", "finance") is True


def test_crypto_keyword_triggers_search():
    assert needs_search("Will crypto markets rally this quarter?", "finance") is True


# ── needs_search: questions that SHOULD NOT trigger search ───────────────────


def test_sunrise_exempt_from_search():
    assert needs_search("Will the sun rise tomorrow?", "weather") is False


def test_sunrise_single_word_exempt():
    assert needs_search("What time is sunrise in New York?", "weather") is False


def test_gravity_exempt_from_search():
    assert needs_search("Is gravity real?", "finance") is False


def test_arithmetic_exempt_from_search():
    assert needs_search("What is 7 × 9?", "finance") is False


def test_arithmetic_division_exempt():
    assert needs_search("What is 100 / 4?", "finance") is False


def test_arithmetic_addition_exempt():
    assert needs_search("What is 2 + 2?", "finance") is False


def test_arithmetic_multiplication_exempt():
    assert needs_search("Is 6 * 7 equal to 42?", "finance") is False


# ── search: successful response ───────────────────────────────────────────────


@pytest.fixture
def searxng_response():
    return {
        "results": [
            {
                "title": "Bitcoin price update",
                "content": "Bitcoin is trading near $118,000 as of today.",
                "url": "https://example.com/btc",
            },
            {
                "title": "Crypto market weekly recap",
                "content": "The crypto market has been volatile this week.",
                "url": "https://example.com/crypto-recap",
            },
        ]
    }


async def test_search_returns_results(searxng_response):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = searxng_response

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        results = await search("bitcoin price")

    assert len(results) == 2
    assert results[0].snippet == "Bitcoin is trading near $118,000 as of today."
    assert results[0].url == "https://example.com/btc"


async def test_search_returns_list_of_search_results(searxng_response):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = searxng_response

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        results = await search("bitcoin")

    assert all(isinstance(r, SearchResult) for r in results)


# ── search: timeout handling ──────────────────────────────────────────────────


async def test_search_returns_empty_on_timeout():
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        results = await search("bitcoin price")

    assert results == []


# ── search: unavailability handling ──────────────────────────────────────────


async def test_search_returns_empty_on_connection_error():
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        results = await search("bitcoin price")

    assert results == []


async def test_search_returns_empty_on_http_error():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=mock_response
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        results = await search("bitcoin price")

    assert results == []


# ── search: empty results ─────────────────────────────────────────────────────


async def test_search_returns_empty_list_when_no_results():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": []}

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        results = await search("very obscure topic with no results")

    assert results == []


async def test_search_skips_results_with_no_snippet():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "results": [
            {"title": "Empty result", "content": "", "url": "https://example.com/1"},
            {"title": "Good result", "content": "This has content.", "url": "https://example.com/2"},
            {"title": "No content key", "url": "https://example.com/3"},
        ]
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        results = await search("test query")

    assert len(results) == 1
    assert results[0].snippet == "This has content."


# --- needs_search: Kalshi taxonomy (category-agnostic default) ---


def test_needs_search_true_for_kalshi_sports():
    assert needs_search("Will Milwaukee win?", "Sports") is True


def test_needs_search_true_for_climate_and_weather():
    assert needs_search("Will it rain in NYC on Friday?", "Climate and Weather") is True


def test_needs_search_true_for_unknown_category():
    assert needs_search("Will Sebastiano Cocola win the match?", "Exotics") is True


def test_needs_search_stable_facts_still_excluded():
    assert needs_search("Will the sun rise tomorrow?", "Sports") is False


def test_needs_search_arithmetic_still_excluded():
    assert needs_search("Is 7 x 9 more than 60?", "Financials") is False


# --- build_search_query ---

from app.searxng import build_search_query


def test_query_player_prop_becomes_stats_search():
    q = build_search_query("Will Freddie Freeman record 1 or more?", "Sports")
    assert q == "Freddie Freeman stats today"


def test_query_win_question_becomes_game_search():
    q = build_search_query("Will Milwaukee win?", "Sports")
    assert q == "Milwaukee game today"


def test_query_crypto_gets_price_context():
    q = build_search_query("Will BTC exceed $120,000 by Friday?", "Crypto")
    assert "price today" in q
    assert q.startswith("BTC exceed")


def test_query_generic_gets_news_context():
    q = build_search_query("Will the next pope be Italian?", "World")
    assert q == "the next pope be Italian latest news"


def test_query_strips_will_prefix_and_question_mark():
    q = build_search_query("Will over 8.5 runs be scored?", "Sports")
    assert not q.lower().startswith("will ")
    assert "?" not in q
