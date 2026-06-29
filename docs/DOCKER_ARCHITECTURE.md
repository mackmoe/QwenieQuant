# Docker Architecture

This document describes the infrastructure defined in `compose/docker-compose.yml`.
It does not describe application internals — only what each container is for and
how they fit together.

## Service Responsibilities

| Service | Responsibility | Status |
|---|---|---|
| `ollama` | Runs LLM inference locally, CPU-only, so agents don't depend on an external model API. | Defined, runnable |
| `postgres` | System of record for predictions, outcomes, and learning history. | Defined, runnable |
| `searxng` | Self-hosted search, giving agents a way to research without a third-party search API. | Defined, runnable |
| `prediction-api` | Generates predictions using `ollama` and reads/writes `postgres`. | Stubbed — no app code yet |
| `learning-engine` | Reviews past predictions and outcomes in `postgres` to refine strategy. | Stubbed — no app code yet |
| `discord-control` | Human-in-the-loop interface for monitoring and steering agents. | Stubbed — no app code yet |

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

## Startup Philosophy

Nothing in this repository starts automatically. The compose file is a
declaration of intended infrastructure, not a deployment trigger. Bringing
services up is a deliberate, explicit action left to a later phase, once:

1. `prediction-api`, `learning-engine`, and `discord-control` have real
   Dockerfiles and application code, and
2. `compose/.env` has been populated from `compose/.env.example` with real,
   non-placeholder values.

Until then, the three application services stay commented out in
`docker-compose.yml` rather than half-defined, so the file never implies
something runnable that isn't.

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
