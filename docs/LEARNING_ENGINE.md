# Learning Engine

The platform's analysis service. Fifth production service deployed (SPEC-009),
after [Ollama](OLLAMA.md), [SearXNG](SEARXNG.md), [PostgreSQL](POSTGRES.md),
and [prediction-api](PREDICTION_API.md).

## Responsibility

Analyze historical predictions from PostgreSQL and produce structured learning
summaries with plain-English observations. Nothing more.

It does **not** modify prompts, generate code, make predictions, execute trades,
or take autonomous action of any kind. Every output is read-only with respect to
the `prediction` schema.

## API

### `GET /health`

```json
{
  "status": "ok",
  "postgres": true,
  "version": "0.1.0"
}
```

`status` is `"ok"` when PostgreSQL is reachable, `"degraded"` otherwise.
Returns HTTP 200 in both cases — the caller decides whether degraded is
acceptable for their use case.

### `POST /analyze`

Request body (all fields optional):

```json
{
  "limit": 250,
  "since": "2026-01-01T00:00:00Z",
  "until": "2026-07-01T00:00:00Z"
}
```

| Field | Type | Default | Constraints |
| --- | --- | --- | --- |
| `limit` | integer | 250 | 1–10000 |
| `since` | datetime (ISO 8601) | null (no lower bound) | — |
| `until` | datetime (ISO 8601) | null (no upper bound) | — |

Response:

```json
{
  "analysis_id": "analysis_20260702T031452_799c1f6f",
  "analyzed_at": "2026-07-02T03:14:52.922087Z",
  "time_range": "2026-07-01 to 2026-07-01",
  "time_range_start": "2026-07-01T04:06:08.265803Z",
  "time_range_end": "2026-07-01T04:06:08.265803Z",
  "predictions_analyzed": 1,
  "outcomes_available": 1,
  "accuracy": 1.0,
  "average_confidence": 0.75,
  "average_execution_ms": 179283.0,
  "model_breakdown": {"qwen3:8b": 1},
  "category_breakdown": {"finance": 1},
  "observations": [
    "1 prediction(s) analyzed.",
    "Accuracy is 100.0% across 1 resolved prediction(s).",
    "Average model confidence is 0.75; 1 of 1 predictions (100.0%) have confidence >= 0.70.",
    "Average inference time is 179.3s per prediction.",
    "All predictions used model 'qwen3:8b'.",
    "Most common category is 'finance' (1 of 1 predictions)."
  ]
}
```

Every analysis run is persisted to `learning.learning_summaries` before the
response is returned. See [POSTGRES.md](POSTGRES.md) for the full table schema.

## How Observations Are Generated

Observations are rule-based — no LLM calls. Each observation is derived
directly from the computed metrics:

1. **Count** — how many predictions were analyzed.
2. **Accuracy** — if any outcomes are available, fraction correct as a
   percentage. If none, states that accuracy cannot be calculated.
3. **Confidence** — mean confidence and the fraction of predictions at or
   above the 0.70 threshold.
4. **Execution time** — mean Ollama inference time in seconds.
5. **Model breakdown** — single model named directly; multiple models
   summarized by count.
6. **Category breakdown** — dominant category and its fraction.
7. **High-confidence calibration** — when ≥5 outcomes are available and mean
   confidence is ≥0.80, reports accuracy specifically among those
   high-confidence predictions.

This approach is auditable, deterministic, and produces no speculation.

## Service Layout

```text
services/learning-engine/
├── app/
│   ├── main.py        — FastAPI app, lifespan (pool startup/shutdown)
│   ├── config.py      — pydantic-settings (POSTGRES_URL)
│   ├── models.py      — AnalysisRequest, AnalysisSummary, HealthStatus
│   ├── postgres.py    — asyncpg pool, fetch_predictions, persist_summary, is_reachable
│   ├── metrics.py     — pure functions: accuracy, confidence, execution_ms, breakdowns
│   ├── summaries.py   — build_observations() — rule-based observation generation
│   ├── analyzer.py    — run_analysis() — orchestrates fetch → compute → observe → persist
│   └── routes.py      — GET /health, POST /analyze
├── tests/
│   ├── test_health.py    — 2 tests
│   ├── test_metrics.py   — 18 tests
│   ├── test_summaries.py — 11 tests
│   └── test_analyze.py   — 22 tests (53 total)
├── Dockerfile
└── requirements.txt
```

## analysis_id Format

`analysis_YYYYMMDDTHHMMSS_xxxxxxxx`  
Example: `analysis_20260702T031452_799c1f6f`

Same design as `prediction_id`: timestamp prefix for readability and
time-sortability, 8-char UUID4 hex suffix for uniqueness. No new dependencies.

## Configuration

| Environment Variable | Default | Notes |
| --- | --- | --- |
| `POSTGRES_URL` | `""` | Full asyncpg DSN. Service starts without it but `/health` reports `postgres: false` and no data is persisted. |

Set in `compose/.env` via Docker Compose environment interpolation:

```text
POSTGRES_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
```

## Networking

Published to `127.0.0.1:${LEARNING_ENGINE_PORT}:8001` (default port 8001).
Internal services reach it as `http://learning-engine:8001`.

## Dependencies

- `postgres` must be `healthy` before the container starts (`depends_on:
  condition: service_healthy`).
- No dependency on `ollama` — the learning engine makes no inference calls.

## Graceful Degradation

If PostgreSQL is unreachable at startup, the service starts anyway with
`_pool = None`. All postgres calls short-circuit silently. `/health` reports
`"status": "degraded", "postgres": false`. `/analyze` returns a 503.
