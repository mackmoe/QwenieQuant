"""
Tests for HTTP routes.

Uses TestClient with lifespan disabled — postgres init and scheduler loop are
mocked out; dependencies are injected manually via set_dependencies().
The autouse fixture resets in-memory queue state before every test.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import queue as qm
from app import routes as routes_module
from app.config import Settings
from app.main import app
from app.models import AddOpportunity, QueueEntry, QueueState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    defaults = dict(
        postgres_url="postgresql://x/x",
        queue_max_size=100,
        queue_priority_weight=0.70,
        queue_wait_weight=0.30,
        queue_refresh_seconds=30,
        queue_expiration_buffer_seconds=60,
        version="0.1.0",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _opp(market_id: str, score: float, expiration_time=None) -> AddOpportunity:
    return AddOpportunity(
        market_id=market_id,
        ticker=market_id,
        priority_score=score,
        expiration_time=expiration_time,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_queue():
    qm._set_state([])
    yield
    qm._set_state([])


@pytest.fixture
def tc():
    with (
        patch(
            "app.main.postgres_module.init_pool",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.main.scheduler_module.scheduler_loop",
            new_callable=AsyncMock,
        ),
        patch(
            "app.main.scheduler_module.workflow_loop",
            new_callable=AsyncMock,
        ),
    ):
        with TestClient(app) as client:
            routes_module.set_dependencies(None, _settings())
            yield client


# ---------------------------------------------------------------------------
# Tests: GET /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_ok_when_postgres_reachable(self, tc):
        # pool=None short-circuits is_reachable; inject a mock pool so the
        # patch actually fires.
        routes_module.set_dependencies(MagicMock(), _settings())
        with patch(
            "app.health.postgres_module.is_reachable",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = tc.get("/health")
        routes_module.set_dependencies(None, _settings())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["postgres"] is True

    def test_health_degraded_when_postgres_unreachable(self, tc):
        with patch(
            "app.health.postgres_module.is_reachable",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = tc.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["postgres"] is False

    def test_health_reflects_queue_size(self, tc):
        qm.add_or_update([_opp("M1", 50.0)], _settings())
        with patch(
            "app.health.postgres_module.is_reachable",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = tc.get("/health")
        data = resp.json()
        assert data["active_entries"] == 1
        assert data["queue_size"] == 1

    def test_health_contains_version(self, tc):
        with patch(
            "app.health.postgres_module.is_reachable",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = tc.get("/health")
        assert resp.json()["version"] == "0.1.0"


# ---------------------------------------------------------------------------
# Tests: GET /queue
# ---------------------------------------------------------------------------


class TestGetQueue:
    def test_empty_queue_returns_zero_totals(self, tc):
        resp = tc.get("/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["total"] == 0
        assert data["active"] == 0

    def test_returns_all_active_entries(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0), _opp("M2", 60.0)], s)
        resp = tc.get("/queue")
        data = resp.json()
        assert data["total"] == 2
        assert data["active"] == 2

    def test_filter_by_queued_state(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0)], s)
        resp = tc.get("/queue?state=QUEUED")
        data = resp.json()
        assert len(data["entries"]) == 1

    def test_filter_by_absent_state_returns_empty(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0)], s)
        resp = tc.get("/queue?state=EXPIRED")
        data = resp.json()
        assert len(data["entries"]) == 0

    def test_limit_parameter_caps_entries(self, tc):
        s = _settings(queue_max_size=10)
        for i in range(6):
            qm.add_or_update([_opp(f"M{i}", float(i * 10 + 10))], s)
        resp = tc.get("/queue?limit=3")
        data = resp.json()
        assert len(data["entries"]) <= 3

    def test_by_state_counts_queued(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0)], s)
        resp = tc.get("/queue")
        data = resp.json()
        assert data["by_state"].get("QUEUED") == 1


# ---------------------------------------------------------------------------
# Tests: GET /queue/next
# ---------------------------------------------------------------------------


class TestGetNext:
    def test_empty_queue_returns_null(self, tc):
        resp = tc.get("/queue/next")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_returns_highest_priority_entry(self, tc):
        s = _settings()
        qm.add_or_update([_opp("LOW", 20.0), _opp("HIGH", 90.0)], s)
        resp = tc.get("/queue/next")
        assert resp.status_code == 200
        assert resp.json()["market_id"] == "HIGH"

    def test_does_not_dequeue_the_entry(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0)], s)
        tc.get("/queue/next")
        assert qm.queue_size() == 1


# ---------------------------------------------------------------------------
# Tests: POST /queue/add
# ---------------------------------------------------------------------------


class TestAddToQueue:
    def test_add_single_opportunity(self, tc):
        resp = tc.post(
            "/queue/add",
            json={"opportunities": [{"market_id": "M1", "ticker": "M1", "priority_score": 80.0}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] == 1
        assert data["updated"] == 0
        assert data["queue_size"] == 1

    def test_add_duplicate_is_counted_as_updated(self, tc):
        tc.post(
            "/queue/add",
            json={"opportunities": [{"market_id": "M1", "ticker": "M1", "priority_score": 80.0}]},
        )
        resp = tc.post(
            "/queue/add",
            json={"opportunities": [{"market_id": "M1", "ticker": "M1", "priority_score": 85.0}]},
        )
        data = resp.json()
        assert data["added"] == 0
        assert data["updated"] == 1
        assert data["queue_size"] == 1

    def test_bulk_add_multiple_opportunities(self, tc):
        resp = tc.post(
            "/queue/add",
            json={
                "opportunities": [
                    {"market_id": "M1", "ticker": "M1", "priority_score": 80.0},
                    {"market_id": "M2", "ticker": "M2", "priority_score": 70.0},
                    {"market_id": "M3", "ticker": "M3", "priority_score": 60.0},
                ]
            },
        )
        data = resp.json()
        assert data["added"] == 3
        assert data["queue_size"] == 3

    def test_add_with_expiration_time(self, tc):
        future = (_now() + timedelta(days=7)).isoformat()
        resp = tc.post(
            "/queue/add",
            json={
                "opportunities": [
                    {
                        "market_id": "M1",
                        "ticker": "M1",
                        "priority_score": 80.0,
                        "expiration_time": future,
                    }
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["added"] == 1


# ---------------------------------------------------------------------------
# Tests: POST /queue/refresh
# ---------------------------------------------------------------------------


class TestRefreshQueue:
    def test_refresh_returns_ok_status(self, tc):
        resp = tc.post("/queue/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_refresh_response_contains_required_fields(self, tc):
        resp = tc.post("/queue/refresh")
        data = resp.json()
        assert "expired_removed" in data
        assert "priorities_updated" in data
        assert "duration_ms" in data
        assert "queue_size" in data

    def test_refresh_expires_stale_entries(self, tc):
        s = _settings(queue_expiration_buffer_seconds=0)
        routes_module.set_dependencies(None, s)
        past = (_now() - timedelta(hours=1)).isoformat()
        tc.post(
            "/queue/add",
            json={
                "opportunities": [
                    {"market_id": "M1", "ticker": "M1", "priority_score": 80.0, "expiration_time": past}
                ]
            },
        )
        resp = tc.post("/queue/refresh")
        assert resp.json()["expired_removed"] >= 1
        assert resp.json()["queue_size"] == 0


# ---------------------------------------------------------------------------
# Tests: DELETE /queue/{market_id}
# ---------------------------------------------------------------------------


class TestCancelEntry:
    def test_cancel_active_entry_returns_204(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0)], s)
        resp = tc.delete("/queue/M1")
        assert resp.status_code == 204

    def test_cancel_removes_entry_from_active_queue(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0)], s)
        tc.delete("/queue/M1")
        assert qm.queue_size() == 0

    def test_cancel_nonexistent_returns_404(self, tc):
        resp = tc.delete("/queue/DOES-NOT-EXIST")
        assert resp.status_code == 404

    def test_cancel_already_cancelled_returns_404(self, tc):
        s = _settings()
        qm.add_or_update([_opp("M1", 80.0)], s)
        tc.delete("/queue/M1")
        resp = tc.delete("/queue/M1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: POST /run
# ---------------------------------------------------------------------------


class TestRunWorkflow:
    def test_run_empty_queue_returns_empty_status(self, tc):
        from app import routes as routes_module
        from unittest.mock import AsyncMock, patch, MagicMock
        mock_http = MagicMock()
        routes_module.set_dependencies(None, _settings(), mock_http)

        with patch(
            "app.routes.workflow_module.run_manual",
            new_callable=AsyncMock,
            return_value={"status": "empty"},
        ):
            resp = tc.post("/run")
        assert resp.status_code == 200
        assert resp.json()["status"] == "empty"

    def test_run_completed_returns_full_result(self, tc):
        from app import routes as routes_module
        from unittest.mock import AsyncMock, patch, MagicMock
        mock_http = MagicMock()
        routes_module.set_dependencies(None, _settings(), mock_http)

        payload = {
            "status": "completed",
            "market_id": "MKT-1",
            "ticker": "MKT-1",
            "title": "Will X happen?",
            "prediction": "Yes",
            "confidence": 0.80,
            "risk_approved": False,
            "risk_reason": "low ev",
            "trade_status": "rejected",
            "duration_ms": 1200,
            "dry_run": True,
        }
        with patch(
            "app.routes.workflow_module.run_manual",
            new_callable=AsyncMock,
            return_value=payload,
        ):
            resp = tc.post("/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["market_id"] == "MKT-1"
        assert data["prediction"] == "Yes"

    def test_run_busy_returns_busy_status(self, tc):
        from app import routes as routes_module
        from unittest.mock import AsyncMock, patch, MagicMock
        mock_http = MagicMock()
        routes_module.set_dependencies(None, _settings(), mock_http)

        with patch(
            "app.routes.workflow_module.run_manual",
            new_callable=AsyncMock,
            return_value={"status": "busy", "started_at": None, "elapsed_seconds": None},
        ):
            resp = tc.post("/run")
        assert resp.status_code == 200
        assert resp.json()["status"] == "busy"

    def test_run_without_http_returns_503(self, tc):
        from app import routes as routes_module
        routes_module.set_dependencies(None, _settings(), None)
        resp = tc.post("/run")
        assert resp.status_code == 503

    def test_run_without_settings_returns_503(self, tc):
        from app import routes as routes_module
        routes_module.set_dependencies(None, None, None)
        try:
            resp = tc.post("/run")
            assert resp.status_code == 503
        finally:
            routes_module.set_dependencies(None, _settings())


# ---------------------------------------------------------------------------
# Tests: GET /stats/activity
# ---------------------------------------------------------------------------


class TestActivityStats:
    def test_returns_zeroes_without_pool(self, tc):
        resp = tc.get("/stats/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 0
        assert data["queued_now"] == 0
        assert data["carried_over"] == 0
        assert data["window_minutes"] == 60

    def test_reports_queue_aging(self, tc):
        from datetime import datetime, timedelta, timezone
        from app import queue as qm
        from app.models import AddOpportunity

        s = _settings()
        qm.add_or_update(
            [AddOpportunity(market_id="OLD-1", ticker="OLD-1", priority_score=50.0),
             AddOpportunity(market_id="NEW-1", ticker="NEW-1", priority_score=60.0)],
            s,
        )
        # age one entry past the window
        for e in qm.get_queue():
            if e.market_id == "OLD-1":
                e.enqueue_time = datetime.now(timezone.utc) - timedelta(minutes=90)

        resp = tc.get("/stats/activity")
        data = resp.json()
        assert data["queued_now"] == 2
        assert data["carried_over"] == 1
        assert data["oldest_queued_minutes"] >= 89

    def test_window_param_respected(self, tc):
        resp = tc.get("/stats/activity?window_minutes=120")
        assert resp.json()["window_minutes"] == 120

    def test_db_stats_flow_through(self, tc):
        mock_pool = MagicMock()
        routes_module.set_dependencies(mock_pool, _settings())
        with patch(
            "app.routes.postgres_module.fetch_activity_stats",
            new_callable=AsyncMock,
            return_value={"processed": 11, "approved": 2, "searched": 9,
                          "avg_duration_seconds": 186.0},
        ):
            resp = tc.get("/stats/activity")
        routes_module.set_dependencies(None, _settings())
        data = resp.json()
        assert data["processed"] == 11
        assert data["approved"] == 2
        assert data["searched"] == 9
        assert data["avg_duration_seconds"] == 186.0
