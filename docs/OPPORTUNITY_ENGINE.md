# Opportunity Engine

**Port:** 8005  
**Container:** `opportunity-engine`  
**Spec:** SPEC-015, SPEC-020

## Overview

The Opportunity Engine is a read-only analysis service that discovers active Kalshi markets and ranks them by how much analytical attention they deserve. It produces no trades and makes no AI calls — its only job is to tell downstream services which markets are worth investigating.

Markets are ranked on a 0–100 priority score derived from five deterministic factors and assigned to one of four tiers.

## Architecture

```
Kalshi Connector (http://kalshi-connector:8003)
        │
        ▼
  KalshiConnectorClient.get_markets()
        │
        ▼
   scorer.run_scoring()          ← deterministic, pure functions
        │
        ▼
   assign_tiers()                ← Tier 0 / 1 / 2 / 3
        │
        ├── scheduler state (in-memory list[ScoredMarket])
        │
        ├── postgres (opportunity.market_scores)
        │               ↑
        │      upserted on each scan
        │
        └── Prediction Queue (http://prediction-queue:8006)
                        ↑
               Tier 3 markets published via POST /queue/add
               after each successful scan (SPEC-020)
```

### Components

| Module | Responsibility |
|---|---|
| `app/config.py` | Settings with tier caps, scoring weights, infra URLs, publish config |
| `app/models.py` | `ScoredMarket`, `OpportunitiesResponse`, `RefreshResponse`, `HealthStatus` |
| `app/kalshi_client.py` | Thin HTTP wrapper around kalshi-connector `/markets` |
| `app/scorer.py` | Deterministic scoring: `score_market`, `assign_tiers`, `run_scoring` |
| `app/postgres.py` | Pool init, `upsert_scores` (ON CONFLICT DO UPDATE), `is_reachable` |
| `app/queue_publisher.py` | `publish_opportunities` — POSTs Tier 3 markets to Prediction Queue |
| `app/scheduler.py` | Background loop + `run_scan`; module-level state cache |
| `app/health.py` | Aggregates postgres + kalshi-connector + scheduler state |
| `app/routes.py` | FastAPI routes; `set_dependencies()` for testing |
| `app/main.py` | Lifespan: init pool → init http → start scheduler task |

## Tier Architecture

| Tier | Criteria | Purpose |
|---|---|---|
| **0** | score == 0.0 (inactive market) | Pruned — no analysis |
| **1** | 0 < score < `MIN_PRIORITY_SCORE`, or beyond `MAX_TIER2_MARKETS` cap | Monitored but low priority |
| **2** | Top `MAX_TIER2_MARKETS` markets with score ≥ `MIN_PRIORITY_SCORE` | Active prediction candidates |
| **3** | Top `MAX_TIER3_MARKETS` markets (subset of Tier 2) | Deep-reasoning candidates |

Tier 3 is always a strict subset of Tier 2. Results are sorted descending by `priority_score`.

## Scoring Algorithm

Each market receives a weighted score from 0–100:

```
score = (
  time_f   * weight_time   +    # 0.30
  volume_f * weight_volume +    # 0.25
  spread_f * weight_spread +    # 0.20
  liquid_f * weight_liquidity + # 0.15
  active_f * weight_activity    # 0.10
) / weight_total * 100
```

### Time Factor (`weight_time = 0.30`)

| Days to Expiry | Score |
|---|---|
| Expired (< 0) | 0.00 |
| < 0.5 days | 0.20 |
| 0.5–1 days | 0.50 |
| 1–7 days | **1.00** (sweet spot) |
| 14 days | 0.85 |
| 30 days | linear interpolation 0.85–0.55 |
| 90 days | linear interpolation 0.55–0.25 |
| > 90 days | 0.15 |
| No close_time | 0.10 |

The sweet spot (1–7 days) represents markets where predictions are both actionable and still uncertain enough to have value.

### Volume Factor (`weight_volume = 0.25`)

`log1p(volume) / log1p(volume_normalization)` capped at 1.0. Uses log normalization so that the first few hundred contracts carry more weight than the difference between 10,000 and 20,000.

### Spread Factor (`weight_spread = 0.20`)

Tight bid/ask spread signals a liquid market with efficient price discovery. Score = `max(0, 1 - spread / spread_normalization)` where spread = `yes_ask - yes_bid`. Markets with no bid/ask data score 0.

### Liquidity Factor (`weight_liquidity = 0.15`)

`log1p(open_interest) / log1p(liquidity_normalization)` capped at 1.0.

### Activity Factor (`weight_activity = 0.10`)

Binary: 1.0 if both `yes_bid` and `yes_ask` are present, otherwise 0.0.

## API Reference

### `GET /health`

Returns service status and dependency health.

**Response (200):**
```json
{
  "status": "ok",
  "kalshi_connector": true,
  "postgres": true,
  "last_scan": "2026-07-06T12:00:00+00:00",
  "markets_scored": 847,
  "tier3_candidates": 28,
  "dry_run_safe": true,
  "version": "0.1.0"
}
```

- `status`: `"ok"` if kalshi-connector reachable; `"degraded"` otherwise; `"starting"` before first initialization
- `dry_run_safe`: always `true` — the service never writes or approves trades

### `GET /opportunities`

Returns all currently ranked markets.

**Query params:**
- `tier` (int, 0–3): filter by tier
- `limit` (int, 1–1000): cap the result set

**Response (200):**
```json
{
  "markets": [
    {
      "market_id": "KXINX-24DEC31-T4800",
      "ticker": "KXINX-24DEC31-T4800",
      "title": "Will the S&P 500 exceed 4800 by Dec 31?",
      "priority_score": 72.4,
      "assigned_tier": 2,
      "scoring_timestamp": "2026-07-06T12:00:00+00:00",
      "metadata": {
        "time_score": 0.85,
        "volume_score": 0.62,
        "spread_score": 0.90,
        "liquidity_score": 0.55,
        "activity_score": 1.0,
        "days_remaining": 14.0
      }
    }
  ],
  "total": 847,
  "tier_counts": {"0": 12, "1": 720, "2": 87, "3": 28},
  "scored_at": "2026-07-06T12:00:00+00:00",
  "version": "0.1.0"
}
```

### `GET /opportunities/top`

Returns only Tier 3 markets — the deep-reasoning candidates.

**Query params:**
- `limit` (int, 1–200): cap the result set

Response format is identical to `GET /opportunities`.

### `POST /refresh`

Triggers an immediate scoring pass outside the scheduled interval. Returns 503 if the service is not yet initialized.

**Response (200):**
```json
{
  "status": "ok",
  "markets_scored": 847,
  "tier_counts": {"0": 12, "1": 720, "2": 87, "3": 28},
  "duration_ms": 312
}
```

## PostgreSQL Schema

```sql
CREATE SCHEMA IF NOT EXISTS opportunity;
CREATE TABLE IF NOT EXISTS opportunity.market_scores (
    market_id           TEXT PRIMARY KEY,
    ticker              TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    priority_score      DOUBLE PRECISION NOT NULL,
    assigned_tier       INTEGER NOT NULL,
    scoring_timestamp   TIMESTAMPTZ NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'
);
```

Scores are upserted on every scan (`ON CONFLICT (market_id) DO UPDATE`). The table is the historical record; the in-memory cache is the live feed served by the API.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `KALSHI_CONNECTOR_URL` | `http://kalshi-connector:8003` | kalshi-connector base URL |
| `POSTGRES_URL` | _(required)_ | PostgreSQL connection string |
| `DISCOVERY_INTERVAL_SECONDS` | `300` | Seconds between scheduled scans |
| `MAX_TIER2_MARKETS` | `100` | Tier 2 cap (active candidates) |
| `MAX_TIER3_MARKETS` | `30` | Tier 3 cap (deep-reasoning candidates) |
| `MIN_PRIORITY_SCORE` | `5.0` | Minimum score to reach Tier 2 |
| `KALSHI_MARKET_LIMIT` | `1000` | Max markets fetched from kalshi-connector per scan |
| `WEIGHT_TIME` | `0.30` | Time factor weight |
| `WEIGHT_VOLUME` | `0.25` | Volume factor weight |
| `WEIGHT_SPREAD` | `0.20` | Spread factor weight |
| `WEIGHT_LIQUIDITY` | `0.15` | Liquidity factor weight |
| `WEIGHT_ACTIVITY` | `0.10` | Activity factor weight |
| `VOLUME_NORMALIZATION` | `10000.0` | Volume reference for log normalization |
| `LIQUIDITY_NORMALIZATION` | `5000.0` | Open interest reference |
| `SPREAD_NORMALIZATION` | `30.0` | Maximum spread before score reaches 0 |
| `HTTP_TIMEOUT` | `30.0` | Outbound HTTP timeout (seconds) |
| `PREDICTION_QUEUE_URL` | `http://prediction-queue:8006` | Prediction Queue base URL |
| `PUBLISH_TO_QUEUE` | `true` | Set to `false` to disable publishing entirely |
| `QUEUE_PUBLISH_BATCH_SIZE` | `30` | Max Tier 3 markets published per scan cycle |

## Queue Publishing (SPEC-020)

After every successful scoring pass, the Opportunity Engine publishes Tier 3 markets to the Prediction Queue.

### Publish timing

Publishing occurs immediately after scoring completes, within the same `run_scan` call. Both the `POST /refresh` route and the background scheduler trigger publishing.

### What is published

Only **Tier 3** markets (the top `MAX_TIER3_MARKETS` by priority score) are published. Tier 1 and Tier 2 markets are never sent to the queue.

### Payload per opportunity

```json
{
  "market_id": "KXBTC-24DEC25-T120000",
  "ticker": "KXBTC-24DEC25-T120000",
  "priority_score": 87.3,
  "metadata": {
    "title": "Will BTC close above $120,000 today?",
    "assigned_tier": 3,
    "days_remaining": 0.18,
    "time_score": 0.5
  }
}
```

### Duplicate handling

The Opportunity Engine submits all eligible Tier 3 markets on every cycle without duplicate checking. The Prediction Queue owns deduplication — existing QUEUED entries are updated in place (`added=0, updated=N`).

### Failure recovery

If the Prediction Queue is unreachable, the failure is logged and swallowed. The scan result is retained, the in-memory state is updated, and postgres is upserted normally. The next scheduled scan will retry publishing automatically.

Log on success:

```text
Successfully published 30 opportunities (added=12 updated=18)
```

Log on failure:

```text
Prediction Queue unavailable: ... — continuing normally
```

### Disabling

Set `PUBLISH_TO_QUEUE=false` in `.env` to disable publishing without affecting market discovery.

## Scheduler Behaviour

- The background loop starts with an initial sleep of `DISCOVERY_INTERVAL_SECONDS` so it does not compete with service startup and healthcheck.
- `POST /refresh` bypasses the schedule and runs a scan immediately (and also triggers publishing).
- If kalshi-connector is unreachable, `get_markets()` returns an empty list; the scan succeeds with zero markets and updates the in-memory state accordingly.
- If postgres is unreachable, `upsert_scores` is skipped silently; the in-memory cache is still updated.
- If the Prediction Queue is unreachable, publishing is skipped silently; the scan and postgres upsert proceed normally.

## Implementation Notes

- **No AI**: scoring is entirely deterministic. The same market with the same data always scores the same.
- **No trades**: this service is read-only. `dry_run_safe: true` in `/health` is a permanent guarantee, not a mode.
- **Graceful degradation**: kalshi-connector or postgres unavailability reduces functionality without crashing. The scheduler loop swallows all exceptions and retries on the next interval.
- **Module-level state**: `scheduler._last_scan` and `scheduler._scored_markets` are process-local. They are reset when the container restarts. The postgres table is the durable record.
- **`_set_state()` for tests**: tests inject scheduler state directly without running a real scan. This is the same pattern used in risk-manager and kalshi-connector tests.
