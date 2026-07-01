# Docker Architecture

This document describes the infrastructure defined in `compose/docker-compose.yml`.
It does not describe application internals — only what each container is for and
how they fit together.

## Service Responsibilities

| Service | Responsibility | Status |
| --- | --- | --- |
| `ollama` | Runs LLM inference locally, CPU-only, so agents don't depend on an external model API. | **Deployed** (SPEC-004) — see [OLLAMA.md](OLLAMA.md) |
| `searxng` | Self-hosted search, giving agents a way to research without a third-party search API. | **Deployed** (SPEC-005), internal-only — see [SEARXNG.md](SEARXNG.md) |
| `postgres` | System of record for predictions, learning history, agent memory, and reflections. | **Deployed** (SPEC-006), internal-only — see [POSTGRES.md](POSTGRES.md) |
| `prediction-api` | Transforms structured prediction requests into structured AI predictions via `ollama`. | **Deployed** (SPEC-007), localhost-only — see [PREDICTION_API.md](PREDICTION_API.md) |
| `learning-engine` | Reviews past predictions and outcomes in `postgres` to refine strategy. | Stubbed — no app code yet |
| `discord-control` | Human-in-the-loop interface for monitoring and steering agents. | Stubbed — no app code yet |

Services are deployed one at a time, each establishing a stable baseline
before the next is added. `ollama` was first, `searxng` second, `postgres`
third. Only the three application services remain commented stubs in
`docker-compose.yml`, until their own deployment phases.

Each service exists for exactly one reason and owns exactly one concern. No
service was added speculatively — anything not directly needed by prediction
generation, learning, persistence, research, or human control was left out
(see SPEC-003 exclusion list: Grafana, Prometheus, Redis, Open WebUI, LiteLLM,
Qdrant, Chroma, Kafka, RabbitMQ, Traefik, Nginx).

## Networking

All services share a single internal bridge network (`internal`). Services
reach each other by container name (e.g. `prediction-api` connects to
`postgres:5432` and `ollama:11434`). A single flat network is the simplest
option that satisfies current needs; there is no multi-tenant or
public-facing requirement yet that would justify network segmentation or a
reverse proxy.

`ollama` publishes its API to `127.0.0.1` on the host, since local
development clients need to reach it directly. `searxng` and `postgres`
publish **nothing** to the host — both are reachable only from other
containers on `internal` (as `http://searxng:8080` and `postgres:5432`
respectively), since neither has a legitimate reason to be reached from
outside the Docker network.

## Persistent Storage

Named volumes exist, one per piece of state that must survive a container
restart:

- `ollama_models` — downloaded model weights, large and slow to re-fetch.
- `postgres_data` — the platform's actual database files. Schemas and the
  `vector` extension are created by `docker/postgres/init/` the first
  time this volume is empty; see [POSTGRES.md](POSTGRES.md).
- `searxng_config` — any non-settings runtime files SearXNG keeps under
  `/etc/searxng`. The settings themselves are a version-controlled,
  read-only bind mount (`config/searxng/settings.yml`), not part of this
  volume — see [SEARXNG.md](SEARXNG.md).
- `searxng_cache` — SearXNG's on-disk query cache.

No other volumes are defined. `prediction-api`, `learning-engine`, and
`discord-control` are stateless by design — any state they need belongs in
`postgres`, not in a container volume.

All four volumes are currently in use and verified persistent across
container recreation.

## Startup Philosophy

Nothing in this repository starts automatically by default, and services
are brought up one at a time rather than all together. `ollama`, `searxng`,
`postgres`, and `prediction-api` are currently running (`docker compose up
-d ollama searxng postgres prediction-api`); `learning-engine` and
`discord-control` stay commented out in `docker-compose.yml` until their
own deployment phase, so the file never implies something runnable that isn't:

1. `learning-engine` and `discord-control` need real Dockerfiles and
   application code before they can be enabled.
2. `compose/.env` must be populated from `compose/.env.example` with real,
   non-placeholder values before any given service is started.

## Why Each Service Exists

- **ollama** — prediction generation needs an LLM; running it locally keeps
  the platform CPU-only and independent of external API availability/cost.
- **postgres** — the learning loop is meaningless without a durable record
  of past predictions and their outcomes; one relational store is enough.
- **searxng** — predictions about real-world events need current
  information; self-hosted search avoids a third-party API dependency.
- **prediction-api** — the actual prediction-generation surface other
  services and humans interact with.
- **learning-engine** — closes the loop by turning recorded outcomes into
  improved future predictions.
- **discord-control** — every autonomous system needs a human override and
  visibility point; Discord is the chosen channel for that.
