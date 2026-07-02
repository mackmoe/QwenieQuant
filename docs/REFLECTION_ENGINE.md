# Reflection Engine

The platform's structured reflection service. Sixth production service deployed
(SPEC-010), after [Ollama](OLLAMA.md), [SearXNG](SEARXNG.md),
[PostgreSQL](POSTGRES.md), [prediction-api](PREDICTION_API.md), and
[learning-engine](LEARNING_ENGINE.md).

## Responsibility

Review a completed learning analysis and produce a structured reflection
identifying strengths, weaknesses, recurring patterns, and recommendations.
Nothing more.

It does **not** modify code, prompts, or configuration. It does **not** execute
trades, create experiments, or take autonomous action. Every output is read-only
with respect to the `prediction` and `learning` schemas.

## Reflection Lifecycle

```
POST /reflect (analysis_id)
       │
       ▼
fetch_summary(analysis_id)       ← learning.learning_summaries
       │
       ├─ not found → 404
       │
       ▼
fetch_recent_summaries(limit=10) ← learning.learning_summaries
       │
       ▼
extract_strengths(summary)       ← summaries.py (single-summary analysis)
extract_weaknesses(summary)
generate_recommendations(...)
       │
       ▼
detect_all(recent_summaries)     ← patterns.py (cross-summary patterns)
       │
       ▼
assemble ReflectionResult
       │
       ▼
persist_reflection(result)       → reflection.reflections
       │
       ▼
return ReflectionResult
```

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
Always returns HTTP 200.

### `POST /reflect`

Request body:

```json
{
  "analysis_id": "analysis_20260702T031452_799c1f6f"
}
```

`analysis_id` is required. If the referenced summary does not exist in
`learning.learning_summaries`, returns HTTP 404.

Response:

```json
{
  "reflection_id": "reflection_20260702T033042_15f29699",
  "analysis_id": "analysis_20260702T031452_799c1f6f",
  "generated_at": "2026-07-02T03:30:42.571814Z",
  "strengths": [
    "Average confidence is 0.75, which is consistently high."
  ],
  "weaknesses": [
    "Only 1 resolved outcome(s) — insufficient to draw reliable accuracy conclusions.",
    "Inference time averages 179.3s, which is above the 120s threshold.",
    "Only 1 prediction(s) analyzed — insufficient for statistical confidence."
  ],
  "patterns": [
    "Category 'finance' dominates prediction history (100% of all predictions across 1 analysis).",
    "All predictions across 1 analysis used model 'qwen3:8b'."
  ],
  "recommendations": [
    "Collect more resolved outcomes before drawing accuracy conclusions.",
    "Increase prediction volume to improve statistical reliability."
  ]
}
```

Every reflection is persisted to `reflection.reflections` before the response
is returned.

## Data Flow

The reflection engine reads from `learning.learning_summaries` and writes to
`reflection.reflections`. It does not read from the `prediction` schema
directly — it builds upon the learning engine's aggregated summaries rather
than duplicating its work.

```
prediction schema   →   learning-engine   →   learning.learning_summaries
                                                         │
                                              reflection-engine reads here
                                                         │
                                              reflection.reflections
```

## How Strengths and Weaknesses Are Extracted

Single-summary analysis (`summaries.py`), rule-based:

**Strengths** (conditions that must be met):
- Accuracy ≥ 75% with ≥ 3 resolved outcomes
- Average confidence ≥ 0.75
- Average inference time < 120 s
- Predictions analyzed ≥ 5

**Weaknesses** (any of these triggers a weakness):
- No resolved outcomes (accuracy cannot be assessed)
- Fewer than 3 resolved outcomes (statistically insufficient)
- Accuracy < 55% with ≥ 3 resolved outcomes
- Average confidence < 0.55
- Average inference time ≥ 120 s
- Fewer than 5 predictions analyzed

**Recommendations** — observations only, not actions:
- If no outcomes: "Record real-world outcomes to enable accuracy measurement."
- If too few outcomes: "Collect more resolved outcomes before drawing conclusions."
- If accuracy below threshold: "Investigate confidence calibration."
- If prediction volume low: "Increase prediction volume."
- If no issues: "Continue monitoring; no immediate areas of concern identified."

## How Patterns Are Detected

Cross-summary analysis (`patterns.py`), rule-based, requires ≥ 2 summaries
per detector:

| Detector | Description |
| --- | --- |
| Accuracy trend | Improving / declining / stable (< 5% spread) / varied |
| Confidence pattern | Consistently high/moderate/low (< 10% spread) or varied |
| Category dominance | Single category ≥ 70% of all predictions |
| Model consistency | Single model across all summaries, or multi-model breakdown |
| Data volume | Average < 5 predictions per analysis → "consistently low" |

## Service Layout

```text
services/reflection-engine/
├── app/
│   ├── main.py        — FastAPI app, lifespan (pool startup/shutdown)
│   ├── config.py      — pydantic-settings (POSTGRES_URL)
│   ├── reflector.py   — ReflectRequest, ReflectionResult, run_reflection()
│   ├── postgres.py    — asyncpg pool, fetch_summary, fetch_recent_summaries,
│   │                    persist_reflection, is_reachable
│   ├── summaries.py   — extract_strengths, extract_weaknesses,
│   │                    generate_recommendations (single-summary, pure)
│   ├── patterns.py    — detect_* functions, detect_all (cross-summary, pure)
│   ├── routes.py      — GET /health, POST /reflect
│   └── health.py      — HealthStatus, get_health()
├── tests/
│   ├── test_reflect.py    — 19 tests (routes, reflection_id, validation,
│   │                         persistence, health)
│   ├── test_summaries.py  — 21 tests (strengths, weaknesses, recommendations)
│   └── test_patterns.py   — 19 tests (each detector + detect_all)
├── Dockerfile
└── requirements.txt
```

## Database Interaction

`reflection.reflections` table (created at startup via `CREATE TABLE IF NOT EXISTS`):

| Column | Type | Notes |
| --- | --- | --- |
| `reflection_id` | TEXT PK | `reflection_YYYYMMDDTHHMMSS_xxxxxxxx` |
| `analysis_id` | TEXT NOT NULL | References a `learning.learning_summaries` row (validated at application level) |
| `generated_at` | TIMESTAMPTZ | Server-set on insert |
| `strengths` | JSONB | Ordered list of plain-English strength strings |
| `weaknesses` | JSONB | Ordered list of plain-English weakness strings |
| `patterns` | JSONB | Ordered list of plain-English pattern strings |
| `recommendations` | JSONB | Ordered list of observation strings |

The `analysis_id` reference is validated at the application level (fetch
returns None → 404) rather than as a database FK, which avoids a
cross-schema initialization dependency on learning-engine's table existing
before reflection-engine's table is created.

## reflection_id Format

`reflection_YYYYMMDDTHHMMSS_xxxxxxxx`
Example: `reflection_20260702T033042_15f29699`

Same design as `prediction_id` and `analysis_id`: timestamp prefix for
readability and time-sortability, 8-char UUID4 hex suffix for uniqueness.

## Configuration

| Environment Variable | Default | Notes |
| --- | --- | --- |
| `POSTGRES_URL` | `""` | Full asyncpg DSN. Service starts without it but `/health` reports `postgres: false`. |

## Networking

Published to `127.0.0.1:${REFLECTION_ENGINE_PORT}:8002` (default port 8002).
Internal services reach it as `http://reflection-engine:8002`.

## Dependencies

- `postgres` must be `healthy` before startup.
- `learning-engine` must be `healthy` before startup — ensures
  `learning.learning_summaries` exists before the reflection engine attempts
  to query it.
- No dependency on `ollama` — no inference calls.

## Graceful Degradation

If PostgreSQL is unreachable at startup, the service starts with `_pool = None`.
`/health` reports `"status": "degraded"`. `POST /reflect` returns 503.

---

## Implementation Observations

These are observations for future phases, not changes to the current implementation.

**1. Hardcoded thresholds.** Accuracy (75%/55%), confidence (0.75/0.55), and
execution time (120 s) thresholds in `summaries.py` are fixed constants. As the
platform accumulates more prediction history, these should become configurable
via environment variables so they can be tuned without a code change.

**2. Pattern detection requires ≥ 2 summaries.** All pattern detectors return
`None` below this threshold, resulting in an empty `patterns` list on the first
reflection. This is correct behavior but worth surfacing to consumers: an empty
`patterns` list means insufficient history, not "no patterns found."

**3. Cross-schema dependency ordering.** The `depends_on: learning-engine:
condition: service_healthy` in docker-compose handles startup ordering, ensuring
`learning.learning_summaries` exists before reflection-engine attempts queries.
If learning-engine is later scaled or replaced, this dependency would need
revisiting.

**4. `analysis_id` validation is application-level.** A cross-schema FK would
enforce referential integrity at the database level, but creates a circular
initialization dependency (each service's table creation would need the other's
table to already exist). Application-level validation is the right tradeoff here.

**5. `recommendations` are observations, not actions.** This is correct for this
phase. A future strategy layer should interpret recommendations and decide
whether to act — that separation of concerns is not yet implemented.
