"""
Unit tests for app/queue.py.

All functions are pure in-memory operations; no mocks needed.
The autouse fixture resets module-level state before and after every test.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import queue as qm
from app.config import Settings
from app.models import AddOpportunity, QueueEntry, QueueState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    defaults = dict(
        postgres_url="postgresql://x/x",
        queue_max_size=5,
        queue_priority_weight=0.70,
        queue_wait_weight=0.30,
        queue_refresh_seconds=30,
        queue_expiration_buffer_seconds=60,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _opp(
    market_id: str,
    score: float,
    expiration_time: datetime | None = None,
    **kwargs,
) -> AddOpportunity:
    return AddOpportunity(
        market_id=market_id,
        ticker=market_id,
        priority_score=score,
        expiration_time=expiration_time,
        **kwargs,
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


# ---------------------------------------------------------------------------
# Tests: add_or_update – basic insertion
# ---------------------------------------------------------------------------


class TestAddOrUpdate:
    def test_add_single_entry(self):
        added, updated, discarded = qm.add_or_update([_opp("MKT-1", 80.0)], _settings())
        assert added == 1
        assert updated == 0
        assert discarded == 0
        assert qm.queue_size() == 1

    def test_add_duplicate_does_not_insert_second(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        added, updated, discarded = qm.add_or_update([_opp("MKT-1", 85.0)], s)
        assert added == 0
        assert updated == 1
        assert discarded == 0
        assert qm.queue_size() == 1

    def test_duplicate_updates_priority_if_higher(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 60.0)], s)
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        assert qm.get_next().priority_score == 80.0

    def test_duplicate_does_not_lower_priority(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        qm.add_or_update([_opp("MKT-1", 60.0)], s)
        assert qm.get_next().priority_score == 80.0

    def test_duplicate_preserves_enqueue_time(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        original_time = qm.get_next().enqueue_time
        qm.add_or_update([_opp("MKT-1", 85.0)], s)
        assert qm.get_next().enqueue_time == original_time

    def test_queue_ordered_descending_by_effective_priority(self):
        s = _settings()
        qm.add_or_update(
            [_opp("MKT-C", 30.0), _opp("MKT-A", 50.0), _opp("MKT-B", 80.0)], s
        )
        entries = qm.get_queue(state=QueueState.QUEUED)
        scores = [e.priority_score for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_bulk_add_multiple_entries(self):
        s = _settings()
        opps = [_opp(f"MKT-{i}", float(i * 10 + 10)) for i in range(3)]
        added, updated, discarded = qm.add_or_update(opps, s)
        assert added == 3
        assert updated == 0
        assert qm.queue_size() == 3


# ---------------------------------------------------------------------------
# Tests: capacity management
# ---------------------------------------------------------------------------


class TestCapacity:
    def test_active_count_does_not_exceed_max(self):
        s = _settings(queue_max_size=3)
        for i in range(6):
            qm.add_or_update([_opp(f"MKT-{i}", float(i * 10 + 10))], s)
        assert qm.queue_size() == 3

    def test_capacity_retains_highest_priority_entries(self):
        s = _settings(queue_max_size=2)
        qm.add_or_update([_opp("LOW", 10.0), _opp("HIGH", 90.0)], s)
        qm.add_or_update([_opp("MED", 50.0)], s)
        active_ids = {
            e.market_id for e in qm.get_queue(state=QueueState.QUEUED)
        }
        assert "HIGH" in active_ids
        assert "MED" in active_ids
        assert "LOW" not in active_ids

    def test_low_priority_newcomer_is_discarded_when_full(self):
        s = _settings(queue_max_size=2)
        qm.add_or_update([_opp("HIGH", 90.0), _opp("MED", 50.0)], s)
        _, _, discarded = qm.add_or_update([_opp("LOW", 5.0)], s)
        assert discarded == 1
        assert qm.queue_size() == 2

    def test_displaced_entry_transitions_to_cancelled(self):
        s = _settings(queue_max_size=1)
        qm.add_or_update([_opp("LOW", 10.0)], s)
        qm.add_or_update([_opp("HIGH", 90.0)], s)
        cancelled = [e for e in qm.get_queue() if e.queue_state == QueueState.CANCELLED]
        assert len(cancelled) == 1
        assert cancelled[0].market_id == "LOW"


# ---------------------------------------------------------------------------
# Tests: expiration
# ---------------------------------------------------------------------------


class TestExpiration:
    def test_past_expiration_entry_is_expired(self):
        s = _settings(queue_expiration_buffer_seconds=0)
        past = _now() - timedelta(hours=1)
        qm.add_or_update([_opp("MKT-1", 80.0, expiration_time=past)], s)
        removed = qm.expire_stale(s)
        assert removed == 1
        assert qm.queue_size() == 0

    def test_future_expiration_entry_survives(self):
        s = _settings(queue_expiration_buffer_seconds=0)
        future = _now() + timedelta(days=10)
        qm.add_or_update([_opp("MKT-1", 80.0, expiration_time=future)], s)
        removed = qm.expire_stale(s)
        assert removed == 0
        assert qm.queue_size() == 1

    def test_no_expiration_time_entry_never_expires(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        removed = qm.expire_stale(s)
        assert removed == 0

    def test_expired_entry_has_expired_state(self):
        s = _settings(queue_expiration_buffer_seconds=0)
        past = _now() - timedelta(hours=1)
        qm.add_or_update([_opp("MKT-1", 80.0, expiration_time=past)], s)
        qm.expire_stale(s)
        entry = qm.get_queue()[0]
        assert entry.queue_state == QueueState.EXPIRED

    def test_expiration_buffer_catches_near_deadline(self):
        # Buffer = 120 s; entry expires in 60 s → should be removed now.
        s = _settings(queue_expiration_buffer_seconds=120)
        near = _now() + timedelta(seconds=60)
        qm.add_or_update([_opp("MKT-1", 80.0, expiration_time=near)], s)
        removed = qm.expire_stale(s)
        assert removed == 1


# ---------------------------------------------------------------------------
# Tests: get_next
# ---------------------------------------------------------------------------


class TestGetNext:
    def test_empty_queue_returns_none(self):
        assert qm.get_next() is None

    def test_returns_highest_priority_queued_entry(self):
        s = _settings()
        qm.add_or_update([_opp("LOW", 20.0), _opp("HIGH", 90.0)], s)
        assert qm.get_next().market_id == "HIGH"

    def test_does_not_remove_entry(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        qm.get_next()
        assert qm.queue_size() == 1


# ---------------------------------------------------------------------------
# Tests: cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_active_entry_returns_true(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        assert qm.cancel("MKT-1") is True

    def test_cancelled_entry_leaves_active_queue(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        qm.cancel("MKT-1")
        assert qm.queue_size() == 0

    def test_cancelled_entry_has_cancelled_state(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0)], s)
        qm.cancel("MKT-1")
        entry = qm.get_queue()[0]
        assert entry.queue_state == QueueState.CANCELLED

    def test_cancel_nonexistent_returns_false(self):
        assert qm.cancel("DOES-NOT-EXIST") is False

    def test_cancel_already_expired_returns_false(self):
        s = _settings(queue_expiration_buffer_seconds=0)
        past = _now() - timedelta(hours=1)
        qm.add_or_update([_opp("MKT-1", 80.0, expiration_time=past)], s)
        qm.expire_stale(s)
        assert qm.cancel("MKT-1") is False


# ---------------------------------------------------------------------------
# Tests: recalculate_priorities
# ---------------------------------------------------------------------------


class TestRecalculate:
    def test_returns_count_of_active_entries(self):
        s = _settings()
        qm.add_or_update([_opp("MKT-1", 80.0), _opp("MKT-2", 60.0)], s)
        assert qm.recalculate_priorities(s) == 2

    def test_wait_component_increases_effective_priority_over_time(self):
        # Inject an entry with an old enqueue_time and zero priority weight,
        # so the effective priority is entirely from the wait component.
        s = _settings(queue_priority_weight=0.0, queue_wait_weight=1.0)
        old_time = _now() - timedelta(hours=12)
        entry = QueueEntry(
            market_id="MKT-1",
            ticker="MKT-1",
            priority_score=50.0,
            effective_priority=0.0,
            queue_state=QueueState.QUEUED,
            enqueue_time=old_time,
        )
        qm._set_state([entry])
        qm.recalculate_priorities(s)
        assert qm.get_next().effective_priority > 0.0

    def test_recalculate_does_not_touch_terminal_entries(self):
        s = _settings(queue_expiration_buffer_seconds=0)
        past = _now() - timedelta(hours=1)
        qm.add_or_update([_opp("MKT-1", 80.0, expiration_time=past)], s)
        qm.expire_stale(s)
        count = qm.recalculate_priorities(s)
        assert count == 0
