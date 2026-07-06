from unittest.mock import AsyncMock, MagicMock, patch

import app.routes as routes_module
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.routes import set_dependencies


def _test_settings(**overrides) -> Settings:
    defaults = dict(
        min_confidence=0.60,
        min_expected_value=0.01,
        min_edge=0.05,
        max_position_percent=5.0,
        max_open_positions=10,
        max_daily_loss=10_000,
        max_consecutive_losses=5,
        dry_run=False,
        kalshi_connector_url="http://mock-kalshi:8003",
        postgres_url="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _good_prediction() -> dict:
    return {
        "prediction_id": "pred_test001",
        "probability": 0.65,
        "confidence": 0.75,
        "expected_value": 0.08,
        "edge": 0.10,
        "market_ticker": "TEST-TICKER",
        "market_category": "finance",
    }


def _mock_http(
    account: dict | None = None,
    positions: list | None = None,
    kalshi_reachable: bool = True,
) -> MagicMock:
    acct = account if account is not None else {"balance": 100_000, "portfolio_value": 0}
    pos = positions if positions is not None else []

    health_response = MagicMock()
    health_response.status_code = 200 if kalshi_reachable else 503

    account_response = MagicMock()
    account_response.status_code = 200
    account_response.raise_for_status.return_value = None
    account_response.json.return_value = acct

    positions_response = MagicMock()
    positions_response.status_code = 200
    positions_response.raise_for_status.return_value = None
    positions_response.json.return_value = pos

    http = MagicMock()

    async def get_side_effect(url, **kwargs):
        if url.endswith("/health"):
            return health_response
        elif url.endswith("/account"):
            return account_response
        elif url.endswith("/positions"):
            return positions_response
        return MagicMock(status_code=404)

    http.get = AsyncMock(side_effect=get_side_effect)
    return http


@pytest.fixture
def tc():
    """TestClient with lifespan, then injects mock dependencies."""
    with TestClient(app) as client:
        http = _mock_http()
        settings = _test_settings()
        set_dependencies(None, http, settings)
        yield client, http, settings
    set_dependencies(None, None, None)


# ── GET /health ──────────────────────────────────────────────────────────────


def test_health_returns_200(tc):
    client, _, _ = tc
    r = client.get("/health")
    assert r.status_code == 200


def test_health_includes_required_fields(tc):
    client, _, _ = tc
    r = client.get("/health")
    body = r.json()
    for field in ("status", "postgres", "kalshi_connector", "dry_run"):
        assert field in body, f"Missing field: {field}"


def test_health_dry_run_reflects_settings(tc):
    client, http, _ = tc
    set_dependencies(None, http, _test_settings(dry_run=True))
    r = client.get("/health")
    assert r.json()["dry_run"] is True


def test_health_starting_when_no_settings():
    with TestClient(app) as client:
        routes_module._http = None
        routes_module._settings = None
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "starting"


# ── POST /evaluate ───────────────────────────────────────────────────────────


def test_evaluate_returns_200(tc):
    client, _, _ = tc
    r = client.post("/evaluate", json=_good_prediction())
    assert r.status_code == 200


def test_evaluate_approved_when_all_checks_pass(tc):
    client, _, _ = tc
    r = client.post("/evaluate", json=_good_prediction())
    body = r.json()
    assert body["approved"] is True
    assert body["recommended_contracts"] is not None
    assert body["recommended_max_price"] is not None


def test_evaluate_includes_risk_checks(tc):
    client, _, _ = tc
    r = client.post("/evaluate", json=_good_prediction())
    body = r.json()
    checks = body["risk_checks"]
    for key in ("confidence", "expected_value", "edge", "open_positions",
                "daily_loss", "bankroll", "consecutive_losses"):
        assert key in checks


def test_evaluate_denied_low_confidence(tc):
    client, _, _ = tc
    pred = {**_good_prediction(), "confidence": 0.10}
    r = client.post("/evaluate", json=pred)
    body = r.json()
    assert body["approved"] is False
    assert body["risk_checks"]["confidence"] is False


def test_evaluate_denied_low_edge(tc):
    client, _, _ = tc
    pred = {**_good_prediction(), "edge": 0.001}
    r = client.post("/evaluate", json=pred)
    body = r.json()
    assert body["approved"] is False
    assert body["risk_checks"]["edge"] is False


def test_evaluate_dry_run_never_approves(tc):
    client, http, _ = tc
    set_dependencies(None, http, _test_settings(dry_run=True))
    r = client.post("/evaluate", json=_good_prediction())
    body = r.json()
    assert body["approved"] is False
    assert "Dry-run" in body["reason"]


def test_evaluate_returns_422_on_missing_required_field(tc):
    client, _, _ = tc
    r = client.post("/evaluate", json={"prediction_id": "x"})
    assert r.status_code == 422


def test_evaluate_returns_422_on_invalid_probability(tc):
    client, _, _ = tc
    pred = {**_good_prediction(), "probability": 1.5}
    r = client.post("/evaluate", json=pred)
    assert r.status_code == 422


def test_evaluate_kalshi_unavailable_still_returns_response(tc):
    client, _, settings = tc
    http = _mock_http(account=None, kalshi_reachable=False)
    # Simulate Kalshi returning an error: get_account raises
    import httpx as httpx_lib
    http.get = AsyncMock(side_effect=httpx_lib.ConnectError("refused"))
    set_dependencies(None, http, settings)
    r = client.post("/evaluate", json=_good_prediction())
    # Should still return a response (denied due to zero balance)
    assert r.status_code == 200
    body = r.json()
    assert body["approved"] is False


def test_evaluate_returns_prediction_id(tc):
    client, _, _ = tc
    r = client.post("/evaluate", json=_good_prediction())
    assert r.json()["prediction_id"] == "pred_test001"


def test_evaluate_denied_when_at_position_limit(tc):
    client, _, settings = tc
    positions = [{"ticker": f"T{i}"} for i in range(10)]
    http = _mock_http(positions=positions)
    set_dependencies(None, http, settings)
    r = client.post("/evaluate", json=_good_prediction())
    body = r.json()
    assert body["approved"] is False
    assert body["risk_checks"]["open_positions"] is False
