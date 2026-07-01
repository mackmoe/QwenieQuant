# Prediction API

The AI Core service for the platform. Fourth production service deployed
(SPEC-007), after [Ollama](OLLAMA.md), [SearXNG](SEARXNG.md), and
[PostgreSQL](POSTGRES.md).

## Responsibility

One job: receive a structured prediction request, orchestrate inference
through Ollama, validate the structured response, and return structured
JSON. Nothing else.

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
  "question":        "Will X happen by Y?",          // 10–500 chars, required
  "category":        "finance|sports|politics|weather", // required
  "options":         ["Yes", "No"],                   // 2–10 choices, default ["Yes","No"]
  "context":         { "key": "value" },              // optional structured context
  "resolution_date": "2025-03-31",                    // optional ISO date
  "market_id":       "optional-external-id"           // optional passthrough
}
```

Categories are intentionally generic. Any domain with a yes/no or
multiple-choice resolution can use this API.

## Response Schema

```json
{
  "prediction_id":        "uuid",
  "question":             "Will X happen by Y?",
  "prediction":           "Yes",
  "confidence":           0.72,
  "reasoning":            "2–4 sentence explanation.",
  "key_factors":          ["factor 1", "factor 2"],
  "model":                "qwen3:8b",
  "created_at":           "2025-01-01T00:00:00Z",
  "search_context_used":  false,
  "sources":              []
}
```

`prediction` is always one of the values from `options`. Responses never
contain raw LLM text — they are always validated before being returned.

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

## PostgreSQL and SearXNG (Stubs)

`app/postgres.py` and `app/searxng.py` are stub modules that define the
interface for future phases. All functions return empty values:

```python
# postgres.py
async def fetch_historical_context(question: str) -> list: return []
async def persist_prediction(request, response) -> None:   pass

# searxng.py
async def search(query: str) -> list: return []
```

These are called unconditionally in the predict route so the plumbing is
already in place. Implementing them does not require touching `routes.py`.

## Module Layout

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app instantiation and router registration |
| `config.py` | All environment variable access via pydantic-settings |
| `models.py` | Pydantic models: request, response, and internal LLM output |
| `routes.py` | Route handlers only — no logic, no prompt building |
| `ollama.py` | HTTP calls to Ollama's `/api/chat` endpoint |
| `prompt_builder.py` | Prompt construction; never called from outside this module |
| `validators.py` | LLM response parsing and validation |
| `health.py` | Health status aggregation |
| `postgres.py` | PostgreSQL interface stub |
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

Tests mock Ollama — no running services needed. 14 tests covering:
- Health ok / degraded states
- Successful prediction with all fields
- Invalid category, short question, missing field (422)
- Malformed JSON from model (502)
- Missing required fields from model (502)
- Model returns option not in options list (502)
- Confidence out of range (502)
- Ollama unreachable (503)
- Custom multi-option predictions

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
- `/predict` returns a fully-validated structured response with all required
  fields for a real inference request to `qwen3:8b`.
- 14/14 unit tests pass with mocked Ollama.
- `ollama`, `searxng`, and `postgres` stayed `healthy` throughout
  deployment and testing — independent service lifecycles confirmed.
