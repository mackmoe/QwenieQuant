# Prediction Queue Manager

**Port:** 8006  
**Container:** `prediction-queue`  
**Spec:** SPEC-016

## Overview

The Prediction Queue Manager is the traffic controller of the Prediction AI Platform. It receives ranked opportunities from the Opportunity Engine, maintains an ordered queue of markets awaiting prediction, and exposes the next highest-priority candidate for downstream consumption.

The Queue Manager does not call Ollama. It does not execute trades. It does not perform AI reasoning. Its only job is to determine what should be analyzed next.

**Why it exists**: AI compute is a finite resource. Unmanaged, multiple callers would race for the Prediction API and either starve each other or waste cycles on low-value markets. The Queue Manager ensures expensive reasoning is always spent on the highest-value opportunities. Prediction work is always ordered. It never becomes chaotic.

## Architecture

```
Opportunity Engine → POST /queue/add
                             │
                             ▼
                      queue.add_or_update()
                             │
                    ┌────────┴────────┐
                    │  In-memory list │   ← module-level state
                    │  sorted by      │
                    │  effective_     │
                    │  priority desc  │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │   scheduler     │   ← runs every QUEUE_REFRESH_SECONDS
                    │  expire_stale() │
                    │  recalculate_   │
                    │  priorities()   │
                    └────────┬────────┘
                             │
                   postgres (queue.prediction_queue)
                          upserted on each refresh

Future orchestrator → GET /queue/next
```

### Components

| Module | Responsibility |
|---|---|
| `app/config.py` | Settings: capacity, weights, intervals, URLs |
| `app/models.py` | `QueueEntry`, `QueueState`, request/response models |
| `app/queue.py` | In-memory queue: add, expire, recalculate, cancel |
| `app/postgres.py` | Pool init, `upsert_entries`, `is_reachable` |
| `app/scheduler.py` | Background loop + `run_refresh`; module-level `_last_refresh` |
| `app/health.py` | Aggregates postgres status + queue stats |
| `app/routes.py` | FastAPI routes; `set_dependencies()` for testing |
| `app/main.py` | Lifespan: init pool → start scheduler |

## Queue Lifecycle

Every market opportunity moves through exactly one state at a time:

```
DISCOVERED   (future: assigned before QUEUED, not used in SPEC-016)
    ↓
QUEUED       ← default initial state from POST /queue/add
    ↓
IN_PROGRESS  ← future: claimed by an orchestrator
    ↓
COMPLETED    ← future: prediction recorded

Terminal states (from any active state):
  EXPIRED    ← expiration window passed during a refresh
  CANCELLED  ← explicitly removed via DELETE /queue/{market_id}
  FAILED     ← future: prediction attempt failed
```

Active states are `QUEUED` and `IN_PROGRESS`. Terminal states are permanent. A terminated entry stays in the list for the postgres upsert record and does not count toward queue capacity.

## Queue Ordering

Queue ordering is deterministic. No AI, no machine learning, no adaptive weighting.

Each active entry receives an **effective priority** computed from two factors:

```
effective_priority =
    priority_score * QUEUE_PRIORITY_WEIGHT    # Opportunity Engine score (0-100)
  + wait_score     * QUEUE_WAIT_WEIGHT        # Queue age bonus (0-100 over 24h)
```

| Factor | Source | Range | Purpose |
|---|---|---|---|
| `priority_score` | Opportunity Engine (SPEC-015) | 0–100 | Market quality score |
| `wait_score` | `(now - enqueue_time).seconds / 86400 * 100` | 0–100 | Prevents starvation |

**Starvation prevention**: A market that scores 60 today will have a higher effective priority than a new 60-score market tomorrow, because its wait bonus has grown. Markets that never get predicted will eventually reach effective parity with higher-scored newcomers.

The queue is re-sorted on every `add_or_update`, `expire_stale`, and `recalculate_priorities` call.

## Duplicate Protection

A market may exist only once in the active queue. When `POST /queue/add` receives a market already in an active state:

- `priority_score` is updated only if the new value is higher (never lowered)
- `expiration_time` is updated if provided
- `metadata` is merged (new keys win)
- `enqueue_time` is preserved (queue age is not reset)
- No duplicate entry is inserted

The `added`/`updated`/`discarded` fields in the response tell the caller exactly what happened.

## Queue Capacity

`QUEUE_MAX_SIZE` caps the number of active (QUEUED + IN_PROGRESS) entries. When at capacity:

1. Compute the effective priority of the incoming market.
2. Find the lowest-priority active entry.
3. If the incoming market scores higher, displace the lowest entry (transitions it to `CANCELLED`) and insert the new one.
4. Otherwise, discard the newcomer (`discarded` count increments).

The highest-priority work is always retained. Low-value markets are the first to be displaced.

## Expiration

The scheduler calls `expire_stale()` on every refresh pass. A market is expired if:

```
(expiration_time - now).total_seconds() < QUEUE_EXPIRATION_BUFFER_SECONDS
```

The buffer (default 60 seconds) removes a market from the active queue slightly before its actual deadline, giving downstream services a safety margin. Markets with no `expiration_time` never expire automatically.

Expired entries transition to `EXPIRED` state — they stay in the list for the postgres record but are excluded from `queue_size()` and the next candidate.

## Scheduler

The background scheduler runs every `QUEUE_REFRESH_SECONDS` (default 30). Each pass:

1. `expire_stale()` — transition past-deadline markets to `EXPIRED`
2. `recalculate_priorities()` — recompute `effective_priority` for all active entries (wait bonus grows with time)
3. `upsert_entries()` — persist current state to postgres

The scheduler starts with an initial sleep equal to `QUEUE_REFRESH_SECONDS`, so the first pass does not compete with lifespan startup. `POST /queue/refresh` triggers an immediate pass at any time.

## REST API

### `GET /health`

Returns service status.

**Response (200):**
```json
{
  "status": "ok",
  "postgres": true,
  "queue_size": 15,
  "active_entries": 12,
  "last_refresh": "2026-07-06T12:00:00+00:00",
  "version": "0.1.0"
}
```

- `status`: `"ok"` if postgres is reachable; `"degraded"` otherwise
- `queue_size`: total entries in all states
- `active_entries`: entries in QUEUED or IN_PROGRESS

---

### `GET /queue`

Returns entries from the current queue.

**Query params:**
- `state` (optional): filter by state (`QUEUED`, `IN_PROGRESS`, `EXPIRED`, `CANCELLED`, …)
- `limit` (int, 1–1000, default 100): cap the result set

**Response (200):**
```json
{
  "entries": [
    {
      "queue_id": "uuid",
      "market_id": "KXINX-24DEC31-T4800",
      "ticker": "KXINX-24DEC31-T4800",
      "priority_score": 72.4,
      "effective_priority": 74.1,
      "queue_state": "QUEUED",
      "enqueue_time": "2026-07-06T11:45:00+00:00",
      "expiration_time": "2026-07-10T00:00:00+00:00",
      "last_updated": "2026-07-06T12:00:00+00:00",
      "metadata": {}
    }
  ],
  "total": 42,
  "active": 38,
  "by_state": {"QUEUED": 36, "IN_PROGRESS": 2, "EXPIRED": 3, "CANCELLED": 1},
  "version": "0.1.0"
}
```

---

### `GET /queue/next`

Returns the highest-priority `QUEUED` entry without dequeuing it. Returns `null` if the queue is empty.

This endpoint is designed for future orchestrators: peek at what should be analyzed next, then use the market_id to lock it (IN_PROGRESS transitions are out of scope for SPEC-016).

**Response (200):**
```json
{
  "queue_id": "uuid",
  "market_id": "KXINX-24DEC31-T4800",
  "ticker": "KXINX-24DEC31-T4800",
  "priority_score": 72.4,
  "effective_priority": 74.1,
  "queue_state": "QUEUED",
  ...
}
```

---

### `POST /queue/add`

Adds or updates opportunities. Duplicate-safe: existing active entries are refreshed, not duplicated.

**Request:**
```json
{
  "opportunities": [
    {
      "market_id": "KXINX-24DEC31-T4800",
      "ticker": "KXINX-24DEC31-T4800",
      "priority_score": 72.4,
      "expiration_time": "2026-07-10T00:00:00+00:00",
      "metadata": {}
    }
  ]
}
```

**Response (200):**
```json
{
  "added": 5,
  "updated": 2,
  "discarded": 1,
  "queue_size": 42
}
```

`discarded` is non-zero when the queue is at capacity and the newcomer did not beat the lowest-priority active entry.

---

### `POST /queue/refresh`

Triggers an immediate priority-refresh pass (expire stale entries, recalculate priorities). Useful after a bulk add to immediately re-sort.

**Response (200):**
```json
{
  "status": "ok",
  "queue_size": 42,
  "expired_removed": 2,
  "priorities_updated": 40,
  "duration_ms": 3
}
```

---

### `DELETE /queue/{market_id}`

Cancels a queued opportunity. Returns 404 if the market is not in an active state (already expired, cancelled, or completed).

**Response:** `204 No Content`

## PostgreSQL Schema

```sql
CREATE SCHEMA IF NOT EXISTS queue;

CREATE TABLE IF NOT EXISTS queue.prediction_queue (
    queue_id           TEXT PRIMARY KEY,
    market_id          TEXT NOT NULL,
    ticker             TEXT NOT NULL,
    priority_score     DOUBLE PRECISION NOT NULL,
    effective_priority DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    queue_state        TEXT NOT NULL,
    enqueue_time       TIMESTAMPTZ NOT NULL,
    expiration_time    TIMESTAMPTZ,
    last_updated       TIMESTAMPTZ NOT NULL,
    metadata           JSONB NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS prediction_queue_market_id_idx
    ON queue.prediction_queue (market_id);
```

The table is upserted on every scheduler refresh and after every `POST /queue/add`. The in-memory list is the live feed; the postgres table is the durable record.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_URL` | _(required)_ | PostgreSQL connection string |
| `OPPORTUNITY_ENGINE_URL` | `http://opportunity-engine:8005` | Opportunity Engine base URL |
| `QUEUE_MAX_SIZE` | `100` | Maximum active entries in the queue |
| `QUEUE_REFRESH_SECONDS` | `30` | Seconds between scheduler passes |
| `QUEUE_EXPIRATION_BUFFER_SECONDS` | `60` | Seconds before deadline to mark entry EXPIRED |
| `QUEUE_PRIORITY_WEIGHT` | `0.70` | Weight applied to the Opportunity Engine score |
| `QUEUE_WAIT_WEIGHT` | `0.30` | Weight applied to queue-age wait bonus |

## Future Integration Points

The Queue Manager is designed for loose coupling. Future services interact with it through the REST API only — no direct database access.

**Orchestrator** (future spec): calls `GET /queue/next` to discover what to analyze, then transitions the entry to IN_PROGRESS via a future endpoint, submits to the Prediction API, and marks it COMPLETED.

**Opportunity Engine** (current): calls `POST /queue/add` after each market scan to replenish the queue with freshly scored markets.

## Implementation Notes

- **Module-level state**: `queue._queue` is process-local. It resets on container restart. PostgreSQL is the durable record.
- **`_set_state()` for tests**: tests inject queue contents directly without running a live scan. Same pattern as risk-manager and opportunity-engine.
- **Graceful degradation**: if postgres is unreachable, the scheduler logs a warning and continues. The in-memory queue keeps operating; the postgres record lags until connectivity resumes.
- **No AI anywhere**: scoring is entirely deterministic. The same market with the same data always gets the same effective priority.
- **`GET /queue/next` is read-only**: it peeks at the front of the queue without dequeuing. An orchestrator can call it repeatedly without side effects.

## Implementation Observations

These are observations for future phases, not changes to this implementation.

**1. No IN_PROGRESS transition endpoint.** SPEC-016 does not implement the QUEUED → IN_PROGRESS transition. A future spec should add `POST /queue/{market_id}/claim` or similar to let an orchestrator atomically claim the next item and prevent double-prediction.

**2. In-memory state is not distributed.** Running multiple prediction-queue replicas would result in independent queues. A future phase could use Redis or postgres-backed locking for distributed coordination.

**3. No partial expiration recovery.** If the service restarts mid-refresh, entries that were expired in memory but not yet written to postgres will reappear as QUEUED on the next startup. A future phase could reload queue state from postgres on startup.

**4. Wait weight can cause score inflation.** Over long periods, the wait bonus can make a low-quality market appear competitive with new high-quality markets. A future phase might cap the wait bonus at a configurable ceiling.

**5. Adaptive queue sizing.** The fixed `QUEUE_MAX_SIZE` does not account for variance in prediction throughput. A future phase could monitor prediction rate and dynamically grow or shrink the queue target.

**6. Category-specific queues.** A single ordered queue treats all prediction markets identically. A future phase might maintain separate queues per category (weather, sports, politics) to ensure balanced coverage.

**7. No priority override.** The spec mentions "Optional priority override" in the ordering section. A future phase could add an explicit priority field to `AddOpportunity` that takes precedence over the computed effective score.
