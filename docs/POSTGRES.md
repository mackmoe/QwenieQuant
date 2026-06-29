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

Five empty schemas, created by `docker/postgres/init/02-schemas.sql`. No
tables exist yet — those are added in later phases, by whichever service
owns that data, not in this initialization step.

| Schema | Purpose |
|---|---|
| `prediction` | Generated predictions and their eventual outcomes. |
| `learning` | Review of past predictions and outcomes, used to refine future strategy. |
| `memory` | Persistent agent memory, including embeddings (pgvector). |
| `reflection` | Self-review of past decisions and reasoning. |
| `system` | Platform-level operational records (e.g. job runs, audit history). |

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

```
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

```
cd compose
cp .env.example .env   # set OLLAMA_PORT, POSTGRES_USER/PASSWORD/DB
docker compose up -d ollama searxng postgres
```

Only `ollama`, `searxng`, and `postgres` are enabled. `prediction-api`,
`learning-engine`, and `discord-control` remain commented stubs until
their own deployment phases.
