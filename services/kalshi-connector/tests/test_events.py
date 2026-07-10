"""Tests for app/events.py — Kalshi event fetching and normalization."""

from unittest.mock import AsyncMock, MagicMock

from app.events import Event, _normalize_event, get_event, get_events


def _raw_event(**kwargs) -> dict:
    d = {
        "event_ticker": "KXMLB-26JUL08MIL",
        "series_ticker": "KXMLB",
        "category": "Sports",
        "title": "Brewers vs Cubs",
    }
    d.update(kwargs)
    return d


def test_normalize_event_maps_all_fields():
    e = _normalize_event(_raw_event())
    assert e.event_ticker == "KXMLB-26JUL08MIL"
    assert e.series_ticker == "KXMLB"
    assert e.category == "Sports"
    assert e.title == "Brewers vs Cubs"


def test_normalize_event_missing_fields_default_none():
    e = _normalize_event({"event_ticker": "X"})
    assert e.series_ticker is None
    assert e.category is None


async def test_get_events_single_page():
    client = MagicMock()
    client.get = AsyncMock(return_value={"events": [_raw_event()], "cursor": None})
    events = await get_events(client)
    assert len(events) == 1
    assert isinstance(events[0], Event)
    assert events[0].category == "Sports"


async def test_get_events_follows_cursor():
    client = MagicMock()
    client.get = AsyncMock(side_effect=[
        {"events": [_raw_event(event_ticker="E1")], "cursor": "abc"},
        {"events": [_raw_event(event_ticker="E2")], "cursor": None},
    ])
    events = await get_events(client)
    assert [e.event_ticker for e in events] == ["E1", "E2"]
    assert client.get.call_count == 2
    # second call passes the cursor
    assert client.get.call_args_list[1][1]["params"]["cursor"] == "abc"


async def test_get_events_stops_on_empty_page():
    client = MagicMock()
    client.get = AsyncMock(return_value={"events": [], "cursor": "keeps-going"})
    events = await get_events(client)
    assert events == []
    assert client.get.call_count == 1


async def test_get_events_respects_max_pages():
    client = MagicMock()
    client.get = AsyncMock(
        return_value={"events": [_raw_event()], "cursor": "never-ends"}
    )
    events = await get_events(client, max_pages=3)
    assert client.get.call_count == 3
    assert len(events) == 3


async def test_get_events_passes_status():
    client = MagicMock()
    client.get = AsyncMock(return_value={"events": [], "cursor": None})
    await get_events(client, status="closed")
    assert client.get.call_args[1]["params"]["status"] == "closed"


async def test_get_event_unwraps_envelope():
    client = MagicMock()
    client.get = AsyncMock(return_value={"event": _raw_event()})
    e = await get_event(client, "KXMLB-26JUL08MIL")
    client.get.assert_called_once_with("/events/KXMLB-26JUL08MIL")
    assert e.category == "Sports"


def test_normalize_event_captures_mutually_exclusive():
    e = _normalize_event(_raw_event(mutually_exclusive=True))
    assert e.mutually_exclusive is True


def test_normalize_event_mutually_exclusive_defaults_none():
    e = _normalize_event({"event_ticker": "X"})
    assert e.mutually_exclusive is None
