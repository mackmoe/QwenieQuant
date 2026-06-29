# Docker Architecture

This document describes the infrastructure defined in `compose/docker-compose.yml`.
It does not describe application internals — only what each container is for and
how they fit together.

## Service Responsibilities

| Service | Responsibility | Status |
|---|---|---|
| `ollama` | Runs LLM inference locally, CPU-only, so agents don't depend on an external model API. | **Deployed** (SPEC-004) — see [OLLAMA.md](OLLAMA.md) |
| `postgres` | System of record for predictions, outcomes, and learning history. | Defined, disabled — not yet deployed |
| `searxng` | Self-hosted search, giving agents a way to research without a third-party search API. | Defined, disabled — not yet deployed |
| `prediction-api` | Generates predictions using `ollama` and reads/writes `postgres`. | Stubbed — no app code yet |
| `learning-engine` | Reviews past predictions and outcomes in `postgres` to refine strategy. | Stubbed — no app code yet |
| `discord-control` | Human-in-the-loop interface for monitoring and steering agents. | Stubbed — no app code yet |

Services are deployed one at a time, each establishing a stable baseline
before the next is added. `ollama` is the first; `postgres` and `searxng`
are fully defined in `docker-compose.yml` but commented out, the same way
the three application services are, until their own deployment phase.

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

## Persistent Storage

Three named volumes exist, one per piece of state that must survive a
container restart:

- `ollama_models` — downloaded model weights, large and slow to re-fetch.
- `postgres_data` — the platform's only database.
- `searxng_config` — SearXNG's own settings.

No other volumes are defined. `prediction-api`, `learning-engine`, and
`discord-control` are stateless by design — any state they need belongs in
`postgres`, not in a container volume.

`ollama_models` is currently in use and verified persistent across
container recreation (see [OLLAMA.md](OLLAMA.md)). `postgres_data` and
`searxng_config` exist in the compose file but are not yet attached to a
running container.

## Startup Philosophy

Nothing in this repository starts automatically by default, and services
are brought up one at a time rather than all together. `ollama` is the
only service currently running (`docker compose up -d ollama`); every
other service stays commented out in `docker-compose.yml` until its own
deployment phase, so the file never implies something runnable that isn't:

1. `postgres` and `searxng` are fully defined but disabled until their own
   deployment phases.
2. `prediction-api`, `learning-engine`, and `discord-control` additionally
   need real Dockerfiles and application code before they can be enabled.
3. `compose/.env` must be populated from `compose/.env.example` with real,
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
