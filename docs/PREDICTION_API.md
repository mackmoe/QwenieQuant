# Prediction API

The AI Core service for the platform. Fourth production service deployed
(SPEC-007), after [Ollama](OLLAMA.md), [SearXNG](SEARXNG.md), and
[PostgreSQL](POSTGRES.md). Persistence layer added in SPEC-008. SearXNG
integration added in SPEC-014.

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
  "search_context_used": true,
  "sources":             ["https://example.com/article"]
}
```

`prediction` is always one of the values from `options`. Responses never
contain raw LLM text — they are always validated before being returned.

`search_context_used` is `true` only when SearXNG returned at least one
result that was included in the prompt. `sources` lists the URLs of the
evidence items actually supplied.

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
2. **Search decision** — `searxng.needs_search()` evaluates the question
   and category deterministically. No model is consulted.
3. **SearXNG queried (when needed)** — `searxng.search()` fetches up to
   `SEARXNG_MAX_RESULTS` results. If SearXNG is unavailable or times out,
   the search is skipped silently and inference continues without evidence.
4. **Prompt built** — `prompt_builder.build_prediction_prompt()` constructs
   system and user prompts. When evidence is available, a "Current Evidence"
   section is appended to the user prompt.
5. **Inference timed** — wall-clock time starts.
6. **Ollama called** — `/api/chat` with `format: json`; blocking until the
   full response is available.
7. **Inference timed** — wall-clock time stops; `execution_ms` recorded.
8. **Model output validated** — JSON parse, required fields, confidence
   range, option membership (502 on failure).
9. **`prediction_id` generated** — `pred_YYYYMMDDTHHMMSS_xxxxxxxx`.
10. **Response constructed** — `PredictionResponse` assembled from validated
    LLM output, request metadata, and search result metadata.
11. **Persisted** — `prediction_requests` and `prediction_responses` rows
    inserted in a single transaction. If the pool is unavailable, this step
    is skipped silently (the API response is unaffected).
12. **Response returned** — structured JSON, always includes `prediction_id`.

## SearXNG Integration

### Search Decision (deterministic)

`searxng.needs_search(question, category)` returns `True` or `False`
without calling any model. The decision is based on:

1. **Stable-fact exemptions** — checked first. Questions about astronomical
   constants, arithmetic, gravity, or other unchanging facts are never
   searched, regardless of category.

2. **Time-sensitivity keywords** — if the question contains any of:
   `today`, `tonight`, `tomorrow`, `this week`, `this month`, `latest`,
   `current`, `recent`, `bitcoin`, `btc`, `ethereum`, `crypto`, `stock
   price`, `nasdaq`, `inflation`, etc., search is used.

3. **Category default** — all four platform categories (`weather`, `sports`,
   `politics`, `finance`) concern time-sensitive outcomes and default to
   search when no exemption applies.

**Examples:**

| Question | Category | Search? |
| --- | --- | --- |
| "Will Dallas reach 100°F tomorrow?" | weather | Yes |
| "Will Bitcoin close above $120k this month?" | finance | Yes |
| "Will the Yankees win tonight?" | sports | Yes |
| "Will the sun rise tomorrow?" | weather | **No** (stable fact) |
| "What is 7 × 9?" | finance | **No** (arithmetic) |
| "Is gravity real?" | finance | **No** (stable knowledge) |

### SearXNG Query

When search is needed, the full question is sent to SearXNG's JSON API:

```
GET {SEARXNG_URL}/search?q={question}&format=json&categories=general&language=en
```

Up to `SEARXNG_MAX_RESULTS` (default: 5) results with non-empty `content`
fields are returned as `SearchResult(title, snippet, url)` objects.

### Failure Behavior

SearXNG failure **never fails the prediction**:

- **Timeout** (exceeds `SEARXNG_TIMEOUT`): logged as WARNING, search
  returns empty list, inference continues without evidence.
- **Connection error** (SearXNG unreachable): logged as WARNING, same
  behavior.
- **HTTP error** (non-2xx response): logged as WARNING, same behavior.
- **Empty results**: logged as DEBUG, inference continues without evidence.

In all failure cases, `search_context_used` is `false` in the response.

### Prompt Construction

When evidence is available, the user prompt includes a section:

```
Current Evidence:
* Bitcoin is trading near $118,000 as of today.
* The market saw high volatility this week amid regulatory news.
```

The system prompt instructs the model to:

- Use supplied evidence when available
- Fall back to internal knowledge when no evidence is provided
- Never invent evidence
- Never claim to have searched when no evidence was supplied

Only the `content` (snippet) from each SearXNG result is included.
Titles and URLs are excluded from the prompt to minimize token usage;
URLs are returned in `sources` in the response but not sent to the model.

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

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_URL` | `http://ollama:11434` | Ollama service URL |
| `OLLAMA_MODEL` | `qwen3:8b` | Model to use for inference |
| `OLLAMA_TIMEOUT` | `300` | Inference timeout in seconds |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG service URL |
| `SEARXNG_TIMEOUT` | `10.0` | Search timeout in seconds |
| `SEARXNG_MAX_RESULTS` | `5` | Maximum results to include in prompt |
| `POSTGRES_URL` | `""` | PostgreSQL connection URL (empty = disabled) |

## Module Layout

| Module | Responsibility |
| --- | --- |
| `main.py` | FastAPI app instantiation, lifespan (pool startup/shutdown) |
| `config.py` | All environment variable access via pydantic-settings |
| `models.py` | Pydantic models: request, response, internal LLM output |
| `routes.py` | Route handlers: classify → search → prompt → infer → persist |
| `ollama.py` | HTTP calls to Ollama's `/api/chat` endpoint |
| `prompt_builder.py` | Prompt construction with optional evidence section |
| `validators.py` | LLM response parsing and validation |
| `health.py` | Health status aggregation |
| `postgres.py` | Connection pool lifecycle and prediction persistence |
| `searxng.py` | Search decision logic and SearXNG HTTP client |

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

Tests mock Ollama, PostgreSQL, and SearXNG — no running services needed.
63 tests covering:

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
- `search_context_used=true` when evidence returned
- `search_context_used=false` when search skipped or empty
- Prediction continues when SearXNG unavailable
- Evidence section appears in prompt when search results present
- No evidence section in prompt when search skipped
- All search decision cases: category defaults and keyword triggers
- All exemptions: sunrise/sunset, arithmetic, gravity
- Timeout/connection error/HTTP error all return empty list
- Empty result filtering (no-snippet results excluded)

## Deployment

```bash
cd compose
docker compose up -d prediction-api
```

Waits for `ollama` and `postgres` to be `healthy` before starting
(via `depends_on` with `condition: service_healthy`). SearXNG is reached
on the `internal` network as `http://searxng:8080` — no `depends_on`
needed since search degrades gracefully when SearXNG is unavailable.

---

## Implementation Observations

These are identified future improvements. Not implemented here.

**1. Search query refinement.** The prediction question is sent verbatim
to SearXNG. A future phase could extract a shorter, targeted query
(e.g., "Bitcoin price today" from "Will Bitcoin close above $120k this
month?") to improve result relevance.

**2. Category-specialized search.** Different categories could use
different SearXNG engine groups — `!news` for politics/current events,
`!finance` for market questions, dedicated weather APIs for weather
questions.

**3. RSS integration.** High-frequency topics (sports scores, market
prices) could be served from RSS feeds instead of web search for fresher,
more structured data.

**4. Weather API integration.** Specialized weather APIs (OpenWeatherMap,
NOAA) would provide more accurate forecast data than SearXNG for weather
questions.

**5. Sports API integration.** Dedicated sports data APIs would provide
structured scores, standings, and schedules rather than web search snippets.

**6. Result ranking.** Currently, results are taken in the order SearXNG
returns them. A future phase could score results by relevance to the
question or recency.

**7. Evidence deduplication.** Multiple SearXNG results sometimes carry
the same snippet from different sources. Deduplication before prompt
construction would reduce token usage without losing information.
