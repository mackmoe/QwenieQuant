# PostgreSQL

The platform's persistent data store. Third production service deployed
(SPEC-006), after [Ollama](OLLAMA.md) and [SearXNG](SEARXNG.md).

## Why PostgreSQL Is the System of Record

Every other service on this platform is either stateless (search,
inference) or will eventually need to read back something it wrote
earlier — past predictions, what actually happened, what was learned from
that, and what an agent reasoned at the time. PostgreSQL is the one place
all of that lives. It is **not** a vector database with a relational
veneer; it's a relational system of record that happens to also store
vectors (via pgvector) next to the structured facts they describe, in the
same transactional store, with the same backup and durability guarantees.
Splitting "facts" and "embeddings" into two separate databases would mean
two sources of truth and a synchronization problem this platform doesn't
need.

## pgvector

The `vector` extension is enabled (currently v0.8.3) so the `memory`
schema can store embeddings alongside the agent memories they represent.
It is used by the image `pgvector/pgvector:pg16` — the pgvector project's
own build of the official `postgres:16` image with the extension compiled
in. This is the standard way to get pgvector without maintaining a custom
Dockerfile: same Postgres, one extension added.

Verified functional, not just installed:

```sql
SELECT '[1,2,3]'::vector(3) <-> '[4,5,6]'::vector(3) AS distance;
--      distance
-- -------------------
--  5.196152422706632
```

## Persistence

Data lives on the named volume `postgres_data`, mounted at
`/var/lib/postgresql/data`. Verified by stopping, removing, and
recreating the container: all five schemas and the `vector` extension
were still present afterward, with no re-initialization.

Initialization scripts (`docker/postgres/init/`) only run once, against
an empty data directory — the official Postgres entrypoint's own
behavior. They are not re-run on every restart, so they're safe to read
as "what this database started as," not "what it currently is."

## Backup Strategy (High-Level)

No backup automation exists yet — out of scope for this phase. The
intended approach for a single-instance, CPU-only deployment like this
one:

- Periodic `pg_dump` (logical backup) written to `backups/` (already
  gitignored — see the root `.gitignore`), rather than relying solely on
  the Docker volume.
- Because initialization is idempotent and declarative (`CREATE SCHEMA IF
  NOT EXISTS`, `CREATE EXTENSION IF NOT EXISTS`), restoring onto a fresh
  container is just: start `postgres` against an empty volume, let init
  run, then restore the latest `pg_dump`.
- No replication or point-in-time recovery for now — appropriate for the
  platform's current single-node scale, revisited if/when that changes.

## Schema Layout

Five schemas, created by `docker/postgres/init/02-schemas.sql`. Tables
are added by each service that owns that data, not in the initialization
scripts.

| Schema | Purpose | Tables |
| --- | --- | --- |
| `prediction` | Generated predictions and their eventual outcomes. | `prediction_requests`, `prediction_responses` (SPEC-008), `prediction_outcomes` (SPEC-009) |
| `learning` | Review of past predictions and outcomes, used to refine future strategy. | `learning_summaries` (SPEC-009) |
| `memory` | Persistent agent memory, including embeddings (pgvector). | None yet |
| `reflection` | Structured reflections on learning analyses: strengths, weaknesses, patterns, recommendations. | `reflections` (SPEC-010) |
| `system` | Platform-level operational records (e.g. job runs, audit history). | None yet |

## Prediction Tables (SPEC-008)

The `prediction-api` service creates these tables at startup via
`CREATE TABLE IF NOT EXISTS` (idempotent; safe to restart). The init
scripts in `docker/postgres/init/` only run on an empty data directory and
cannot be used for post-initialization DDL.

**`prediction.prediction_requests`** — one row per incoming request:

| Column | Type | Notes |
| --- | --- | --- |
| `prediction_id` | TEXT PK | `pred_YYYYMMDDTHHMMSS_xxxxxxxx` — sortable, human-readable |
| `created_at` | TIMESTAMPTZ | Server-set on insert |
| `question` | TEXT | The prediction question |
| `category` | TEXT | `weather`, `sports`, `politics`, or `finance` |
| `options` | JSONB | The valid answer choices |
| `context` | JSONB | Optional structured context from caller |
| `resolution_date` | DATE | Optional |
| `market_id` | TEXT | Optional external passthrough identifier |
| `prompt_version` | TEXT | Prompt template version at time of inference |

**`prediction.prediction_responses`** — one row per completed prediction,
linked 1:1 to its request:

| Column | Type | Notes |
| --- | --- | --- |
| `prediction_id` | TEXT PK | FK → `prediction_requests.prediction_id` |
| `created_at` | TIMESTAMPTZ | Server-set on insert |
| `prediction` | TEXT | The model's chosen option |
| `confidence` | DOUBLE PRECISION | 0.0–1.0 |
| `reasoning` | TEXT | Model's explanation |
| `key_factors` | JSONB | List of factors that influenced the prediction |
| `model` | TEXT | Ollama model name used |
| `execution_ms` | INTEGER | Ollama inference time in milliseconds |
| `search_used` | BOOLEAN | Whether SearXNG context was included |
| `memory_used` | BOOLEAN | Whether historical context was included |
| `validation_status` | TEXT | `valid` if response passed all validators |
| `response_payload` | JSONB | Full serialized `PredictionResponse` for audit |

**`prediction.prediction_outcomes`** — one row per resolved prediction,
added when the real-world outcome is known. Owned by `prediction-api`
(SPEC-009); `learning-engine` reads it but does not create it, so the FK
constraint is always satisfiable regardless of service startup order:

| Column | Type | Notes |
| --- | --- | --- |
| `prediction_id` | TEXT PK | FK → `prediction_requests.prediction_id` |
| `outcome` | TEXT | The actual result (must match an option from the original request) |
| `resolved_at` | TIMESTAMPTZ | Server-set on insert |

## Learning Tables (SPEC-009)

The `learning-engine` service creates this table at startup via
`CREATE TABLE IF NOT EXISTS` (idempotent; same pattern as prediction-api).

**`learning.learning_summaries`** — one row per analysis run:

| Column | Type | Notes |
| --- | --- | --- |
| `analysis_id` | TEXT PK | `analysis_YYYYMMDDTHHMMSS_xxxxxxxx` — same pattern as `prediction_id` |
| `analyzed_at` | TIMESTAMPTZ | Server-set on insert |
| `time_range_start` | TIMESTAMPTZ | Earliest `created_at` among analyzed predictions (nullable) |
| `time_range_end` | TIMESTAMPTZ | Latest `created_at` among analyzed predictions (nullable) |
| `predictions_analyzed` | INTEGER | Total predictions fetched |
| `outcomes_available` | INTEGER | Predictions that had a resolved outcome |
| `accuracy` | DOUBLE PRECISION | Fraction correct; NULL when no outcomes available |
| `average_confidence` | DOUBLE PRECISION | Mean model confidence across all predictions |
| `average_execution_ms` | DOUBLE PRECISION | Mean Ollama inference time in milliseconds |
| `model_breakdown` | JSONB | `{"model_name": count}` |
| `category_breakdown` | JSONB | `{"category": count}` |
| `observations` | JSONB | Ordered list of plain-English observation strings |

### prediction_id Design

Format: `pred_YYYYMMDDTHHMMSS_xxxxxxxx`
Example: `pred_20260701T040608_85594185`

Properties:

- **Globally unique** — the 8-char hex suffix (from UUID4) is the uniqueness
  guarantee.
- **Human-readable** — the timestamp is legible without a decoder.
- **Sortable by time** — lexicographic sort on `prediction_id` gives
  chronological order (IDs from different seconds sort correctly; within
  the same second, ordering by the random suffix is acceptable since the
  collision probability is ~1 in 4 billion).
- **The primary traceability key** — the same `prediction_id` links the
  request row, the response row, and the API response to the caller.

### Learning Engine Access

The schema stores facts (what was asked, what was predicted, when, how
long it took) without conclusions (no scores, no quality labels). The
learning engine joins `prediction_requests`, `prediction_responses`, and
`prediction_outcomes` on `prediction_id` to produce analysis summaries.
See [LEARNING_ENGINE.md](LEARNING_ENGINE.md).

Each schema has a `COMMENT ON SCHEMA` matching the description above,
queryable directly from Postgres:

```sql
SELECT nspname, obj_description(oid) FROM pg_namespace
WHERE nspname IN ('prediction','learning','memory','reflection','system');
```

## Connection Information

PostgreSQL is **internal-only** — no port is published to the host.
`docker port postgres` returns nothing, and `docker compose config` shows
no `ports:` entry for the service. It is reachable only from other
containers on the compose `internal` network:

```text
host:     postgres
port:     5432
database: ${POSTGRES_DB}
user:     ${POSTGRES_USER}
password: ${POSTGRES_PASSWORD}
```

All four values are set in `compose/.env` (gitignored; see
`compose/.env.example` for the placeholder names). There is no other way
to reach this database — not from the host, not from outside the Docker
network.

## Verification Performed

- Container reaches and stays in `healthy` state (`pg_isready` healthcheck).
- `vector` extension installed and functionally tested (see above).
- All five schemas created, each with zero tables and the correct comment.
- No host port published; reachable by name (`postgres:5432`) from
  another container on the `internal` network (tested with a throwaway
  `postgres:16-alpine` client running `pg_isready -h postgres`).
- Data, schemas, and the extension all survive a full
  stop/remove/recreate cycle.
- `ollama` and `searxng` stayed `healthy` throughout postgres's
  deployment, restart, and testing — independent service lifecycles.

## Deployment

```sh
cd compose
cp .env.example .env   # set OLLAMA_PORT, POSTGRES_USER/PASSWORD/DB, PREDICTION_API_PORT, LEARNING_ENGINE_PORT
docker compose up -d
```
