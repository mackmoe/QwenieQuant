import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    with patch("app.ollama.is_reachable", new=AsyncMock(return_value=True)):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ollama"] is True
    assert "version" in data


def test_health_degraded_when_ollama_unreachable():
    with patch("app.ollama.is_reachable", new=AsyncMock(return_value=False)):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["ollama"] is False
