from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    with patch("app.postgres.is_reachable", new=AsyncMock(return_value=True)):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["postgres"] is True
    assert "version" in data


def test_health_degraded_when_postgres_unreachable():
    with patch("app.postgres.is_reachable", new=AsyncMock(return_value=False)):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["postgres"] is False
