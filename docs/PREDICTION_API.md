# Prediction API

The AI Core service for the platform. Fourth production service deployed
(SPEC-007), after [Ollama](OLLAMA.md), [SearXNG](SEARXNG.md), and
[PostgreSQL](POSTGRES.md). Persistence layer added in SPEC-008.

## Responsibility

One job: receive a structured prediction request, orchestrate inference
through Ollama, validate the structured response, persist it, and return
structured JSON. Nothing else.

- **No trading logic.** It knows nothing about Kalshi, markets, or orders.
- **No learning.** It does not review past predictions or update strategy.
- **No Discord.** It does not emit events or accept commands from Discord.
- **No embedding.** It does not read from or write to the `memory` schema.

Any application that can form a JSON POST request can consume this API
without modification.

## Endpoints

```
GET  /health   — liveness and dependency status
POST /predict  — structured prediction request → structured response
GET  /docs     — OpenAPI (Swagger UI), development only
```

## Request Schema

```json
{
  "question":        "Will X happen by Y?",             // 10–500 chars, required
  "category":        "finance|sports|politics|weather", // required
  "options":         ["Yes", "No"],                     // 2–10 choices, default ["Yes","No"]
  "context":         { "key": "value" },                // optional structured context
  "resolution_date": "2025-03-31",                      // optional ISO date
  "market_id":       "optional-external-id"             // optional passthrough
}
```

Categories are intentionally generic. Any domain with a yes/no or
multiple-choice resolution can use this API.

## Response Schema

```json
{
  "prediction_id":       "pred_20260701T040608_85594185",
  "question":            "Will X happen by Y?",
  "prediction":          "Yes",
  "confidence":          0.72,
  "reasoning":           "2–4 sentence explanation.",
  "key_factors":         ["factor 1", "factor 2"],
  "model":               "qwen3:8b",
  "created_at":          "2026-07-01T04:06:08Z",
  "search_context_used": false,
  "sources":             []
}
```

`prediction` is always one of the values from `options`. Responses never
contain raw LLM text — they are always validated before being returned.

## prediction_id

Every response includes a `prediction_id` in the format
`pred_YYYYMMDDTHHMMSS_xxxxxxxx`. It is the primary traceability key
across the entire platform — the same ID links the API response to the
caller, the `prediction_requests` row, and the `prediction_responses` row
in PostgreSQL. See [POSTGRES.md](POSTGRES.md#prediction_id-design) for
the full format specification.

## Prediction Lifecycle

For every `POST /predict` call:

1. **Request validated** — Pydantic rejects invalid inputs before any
   inference starts (422 on failure).
2. **Stubs called** — `postgres.fetch_historical_context()` and
   `searxng.search()` are called; both currently return empty lists.
3. **Prompt built** — `prompt_builder.build_prediction_prompt()` constructs
   the system and user prompts from the request fields.
4. **Inference timed** — wall-clock time starts.
5. **Ollama called** — `/api/chat` with `format: json`; blocking until the
   full response is available.
6. **Inference timed** — wall-clock time stops; `execution_ms` recorded.
7. **Model output validated** — JSON parse, required fields, confidence
   range, option membership (502 on failure).
8. **`prediction_id` generated** — `pred_YYYYMMDDTHHMMSS_xxxxxxxx`.
9. **Response constructed** — `PredictionResponse` assembled from validated
   LLM output and request metadata.
10. **Persisted** — `prediction_requests` and `prediction_responses` rows
    inserted in a single transaction. If the pool is unavailable, this step
    is skipped silently (the API response is unaffected).
11. **Response returned** — structured JSON, always includes `prediction_id`.

## Persistence Flow

`app/postgres.py` manages the connection pool and the two tables in the
`prediction` schema. The pool is initialized at startup
(`postgres.startup()` called from the FastAPI lifespan). Tables are
created via `CREATE TABLE IF NOT EXISTS` on every startup — idempotent,
safe to restart.

If `POSTGRES_URL` is not set, or if PostgreSQL is unreachable at startup,
persistence is disabled for the session. The service still handles
inference requests; predictions are returned but not stored. This allows
the service to start without a database (e.g., during local development
without Docker).

The persist call is a single transaction: both the request row and the
response row are inserted atomically. If either insert fails, both are
rolled back and the error is logged — the API response is still returned.

## Validation Rules

**Incoming requests** — validated by Pydantic before the route handler
runs. Invalid category, short question, missing field: 422.

**Model output** — validated in `app/validators.py` before constructing
the response:

- JSON must parse cleanly (malformed → 502)
- `confidence` must be 0.0–1.0 (out of range → 502)
- `prediction` must be one of `options` exactly (wrong value → 502)
- Required fields (`prediction`, `confidence`, `reasoning`) must all be
  present (missing fields → 502)

## Ollama Integration

`app/ollama.py` calls `/api/chat` with `format: "json"` to enforce
structured output. Model and URL are read from environment:

```
OLLAMA_URL    — default: http://ollama:11434
OLLAMA_MODEL  — default: qwen3:8b
```

**Timeout** — default 300 seconds. `qwen3:8b` generates an internal
reasoning chain before producing the JSON response; at ~3 tok/s on CPU
this can run 2–4 minutes. The full generation completes before the first
byte is returned (`stream: false`). The thinking chain is discarded
(available in the raw `thinking` field but not forwarded to callers).

## SearXNG (Stub)

`app/searxng.py` defines the interface for a future phase. Called
unconditionally; returns an empty list. Implementing it does not require
touching `routes.py`.

## Module Layout

| Module | Responsibility |
| --- | --- |
| `main.py` | FastAPI app instantiation, lifespan (pool startup/shutdown) |
| `config.py` | All environment variable access via pydantic-settings |
| `models.py` | Pydantic models: request, response, internal LLM output |
| `routes.py` | Route handlers only — no logic, no prompt building |
| `ollama.py` | HTTP calls to Ollama's `/api/chat` endpoint |
| `prompt_builder.py` | Prompt construction; never called from outside routes |
| `validators.py` | LLM response parsing and validation |
| `health.py` | Health status aggregation |
| `postgres.py` | Connection pool lifecycle and prediction persistence |
| `searxng.py` | SearXNG interface stub |

## Connection Information

```
host:  127.0.0.1 (localhost, not Docker-internal)
port:  ${PREDICTION_API_PORT}  (default: 8000)
```

Exposed to localhost only. Not reachable from outside the host machine.
Other containers on the `internal` network reach it as
`http://prediction-api:8000`.

## Running Tests

```bash
cd services/prediction-api
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests mock Ollama and PostgreSQL — no running services needed. 29 tests
covering:

- Health ok / degraded states
- Successful prediction with all required fields present
- `prediction_id` format and uniqueness
- `persist_prediction` called with `execution_ms` on every success
- Invalid category, short question, missing field (422)
- Malformed JSON from model (502)
- Missing required fields from model (502)
- Model returns option not in options list (502)
- Confidence out of range (502)
- Ollama unreachable (503)
- Custom multi-option predictions
- `persist_prediction` no-op when pool is None
- `fetch_recent_predictions` returns empty list when pool is None
- Two SQL inserts executed per persist call
- Both inserts wrapped in a single transaction
- First insert uses the correct `prediction_id`
- Second insert includes the correct `execution_ms`

## Deployment

```bash
cd compose
docker compose up -d prediction-api
```

Waits for `ollama` and `postgres` to be `healthy` before starting
(via `depends_on` with `condition: service_healthy`).

## Verification Performed

- Container reaches and stays in `healthy` state (Python urllib healthcheck
  on `/health`).
- `/health` returns `{"status": "ok", "ollama": true}` when Ollama is up.
- `/predict` returns a fully-validated structured response with `prediction_id`
  in `pred_YYYYMMDDTHHMMSS_xxxxxxxx` format for a real inference request.
- Both `prediction.prediction_requests` and `prediction.prediction_responses`
  rows inserted atomically; verified via `psql` after a live call.
- `fetch_recent_predictions()` returns the persisted row with correct fields.
- `execution_ms` recorded accurately (179283 ms for a real qwen3:8b inference
  on CPU, consistent with ~3 tok/s benchmark).
- 29/29 unit tests pass with mocked Ollama and PostgreSQL.
- `ollama`, `searxng`, and `postgres` stayed `healthy` throughout.
