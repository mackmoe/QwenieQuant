"""
In-memory priority queue for prediction work.

Module-level state is the authoritative runtime list; postgres is the
durable record written on each refresh.  Tests inject state via _set_state().
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.models import ACTIVE_STATES, AddOpportunity, QueueEntry, QueueState

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_queue: list[QueueEntry] = []


def _set_state(entries: list[QueueEntry]) -> None:
    """For testing only — replace queue contents directly."""
    global _queue
    _queue = list(entries)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Priority computation
# ---------------------------------------------------------------------------

# Wait score normalizes over this many seconds to reach 100.
_WAIT_NORMALIZATION_SECONDS = 86_400.0  # 24 hours


def compute_effective_priority(
    priority_score: float,
    enqueue_time: datetime,
    settings: Settings,
    now: datetime | None = None,
) -> float:
    """
    Deterministic weighted score combining opportunity value and queue age.

    priority_score: 0-100 from Opportunity Engine (scored market quality).
    wait_score:     0-100 normalized over 24 hours (prevents starvation).

    effective = priority_score * QUEUE_PRIORITY_WEIGHT
              + wait_score     * QUEUE_WAIT_WEIGHT
    """
    if now is None:
        now = _now()
    wait_seconds = max(0.0, (now - enqueue_time).total_seconds())
    wait_score = min(100.0, wait_seconds / _WAIT_NORMALIZATION_SECONDS * 100.0)
    return (
        priority_score * settings.queue_priority_weight
        + wait_score * settings.queue_wait_weight
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sort() -> None:
    _queue.sort(key=lambda e: e.effective_priority, reverse=True)


def _active_entries() -> list[QueueEntry]:
    return [e for e in _queue if e.queue_state in ACTIVE_STATES]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def queue_size() -> int:
    """Count of entries in ACTIVE_STATES."""
    return len(_active_entries())


def get_queue(
    state: QueueState | None = None,
    limit: int = 1000,
) -> list[QueueEntry]:
    if state is not None:
        return [e for e in _queue if e.queue_state == state][:limit]
    return _queue[:limit]


def get_next() -> QueueEntry | None:
    """Peek at the highest-priority QUEUED entry without dequeuing it."""
    for entry in _queue:
        if entry.queue_state == QueueState.QUEUED:
            return entry
    return None


def get_stats() -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in _queue:
        key = entry.queue_state.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def add_or_update(
    opportunities: list[AddOpportunity],
    settings: Settings,
) -> tuple[int, int, int]:
    """
    Insert new opportunities or refresh existing ones.

    Duplicate-safe: a market already in ACTIVE_STATES is updated in-place;
    its enqueue_time is preserved (queue-age fairness is kept).

    At capacity: incoming entries compete against the current lowest-priority
    active entry.  Lower-priority newcomers are discarded.

    Returns (added, updated, discarded).
    """
    now = _now()
    added = 0
    updated = 0
    discarded = 0

    active_index: dict[str, QueueEntry] = {
        e.market_id: e for e in _active_entries()
    }

    for opp in opportunities:
        if opp.market_id in active_index:
            entry = active_index[opp.market_id]
            if opp.priority_score > entry.priority_score:
                entry.priority_score = opp.priority_score
            if opp.expiration_time is not None:
                entry.expiration_time = opp.expiration_time
            if opp.metadata:
                entry.metadata.update(opp.metadata)
            entry.last_updated = now
            entry.effective_priority = compute_effective_priority(
                entry.priority_score, entry.enqueue_time, settings, now
            )
            updated += 1
        else:
            effective = compute_effective_priority(opp.priority_score, now, settings, now)
            current_active = _active_entries()

            if len(current_active) >= settings.queue_max_size:
                lowest = min(current_active, key=lambda e: e.effective_priority)
                if effective > lowest.effective_priority:
                    lowest.queue_state = QueueState.CANCELLED
                    lowest.last_updated = now
                    new_entry = _make_entry(opp, effective, now)
                    _queue.append(new_entry)
                    active_index[opp.market_id] = new_entry
                    added += 1
                else:
                    discarded += 1
            else:
                new_entry = _make_entry(opp, effective, now)
                _queue.append(new_entry)
                active_index[opp.market_id] = new_entry
                added += 1

    _sort()
    return added, updated, discarded


def _make_entry(opp: AddOpportunity, effective: float, now: datetime) -> QueueEntry:
    return QueueEntry(
        market_id=opp.market_id,
        ticker=opp.ticker,
        priority_score=opp.priority_score,
        effective_priority=effective,
        queue_state=QueueState.QUEUED,
        enqueue_time=now,
        expiration_time=opp.expiration_time,
        last_updated=now,
        metadata=dict(opp.metadata),
    )


def expire_stale(settings: Settings) -> int:
    """
    Transition QUEUED entries past their expiration window to EXPIRED.

    Only QUEUED entries are eligible — IN_PROGRESS entries are mid-prediction
    and must not be expired; doing so corrupts queue state because the
    workflow's subsequent mark_completed() silently fails on the changed state,
    leaving the entry stuck as EXPIRED and potentially re-queued by the next
    OE scan, causing a duplicate prediction cycle.
    """
    now = _now()
    buffer = settings.queue_expiration_buffer_seconds
    removed = 0
    for entry in _queue:
        if entry.queue_state != QueueState.QUEUED:
            continue
        if entry.expiration_time is None:
            continue
        if (entry.expiration_time - now).total_seconds() < buffer:
            entry.queue_state = QueueState.EXPIRED
            entry.last_updated = now
            removed += 1
    return removed


def recalculate_priorities(settings: Settings) -> int:
    """Recompute effective_priority for all active entries and re-sort."""
    now = _now()
    count = 0
    for entry in _queue:
        if entry.queue_state in ACTIVE_STATES:
            entry.effective_priority = compute_effective_priority(
                entry.priority_score, entry.enqueue_time, settings, now
            )
            count += 1
    _sort()
    return count


def cancel(market_id: str) -> bool:
    """Transition an active entry to CANCELLED.  Returns False if not found."""
    now = _now()
    for entry in _queue:
        if entry.market_id == market_id and entry.queue_state in ACTIVE_STATES:
            entry.queue_state = QueueState.CANCELLED
            entry.last_updated = now
            return True
    return False


def _transition(market_id: str, from_states: set, to_state: QueueState) -> bool:
    now = _now()
    for entry in _queue:
        if entry.market_id == market_id and entry.queue_state in from_states:
            entry.queue_state = to_state
            entry.last_updated = now
            return True
    return False


def mark_in_progress(market_id: str) -> bool:
    """QUEUED → IN_PROGRESS."""
    return _transition(market_id, {QueueState.QUEUED}, QueueState.IN_PROGRESS)


def mark_completed(market_id: str) -> bool:
    """IN_PROGRESS → COMPLETED."""
    return _transition(market_id, {QueueState.IN_PROGRESS}, QueueState.COMPLETED)


def mark_failed(market_id: str) -> bool:
    """IN_PROGRESS → FAILED."""
    return _transition(market_id, {QueueState.IN_PROGRESS}, QueueState.FAILED)


def mark_queued(market_id: str) -> bool:
    """IN_PROGRESS → QUEUED (retry on next cycle)."""
    return _transition(market_id, {QueueState.IN_PROGRESS}, QueueState.QUEUED)
