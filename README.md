# Prediction AI Platform

## Mission

Build a self-hosted, CPU-only AI platform that powers autonomous agents capable of
researching, reasoning about, and trading on prediction markets — while learning
and improving from their own outcomes over time.

## High-Level Architecture

The platform is organized around a small set of cooperating services rather than
a single monolith:

- **prediction-api** — interface for generating and serving market predictions.
- **learning-engine** — reviews past predictions and outcomes to refine strategy
  and prompts over time.
- **discord-control** — human-in-the-loop interface for monitoring and steering
  agent behavior.

These services share a common set of prompts, configuration, and memory, and are
designed to run on self-hosted, CPU-only hardware. They are backed by local
infrastructure — an LLM runtime (Ollama), a database, and self-hosted search —
deployed incrementally, one service at a time. See
[docs/DOCKER_ARCHITECTURE.md](docs/DOCKER_ARCHITECTURE.md) for current status.

## Repository Layout

```
docker/      Dockerfiles for individual services
compose/     Docker Compose definitions
config/      Non-secret configuration and placeholders
docs/        Project documentation
scripts/     Operational and developer scripts
backups/     Local backup artifacts (not committed)
prompts/     Versioned prompt templates, grouped by purpose
  prediction/  Prompts used to generate predictions
  learning/    Prompts used to drive learning/improvement loops
  reflection/  Prompts used for self-review of past decisions
  personas/    Agent persona definitions
services/    Application services
  prediction-api/    Prediction generation service
  learning-engine/   Outcome review and learning service
  discord-control/   Discord-based control interface
memory/      Persistent agent memory/state (not committed)
experiments/ Exploratory work, not production code
tests/       Automated tests
```

## Development Philosophy

- **Simplicity first.** Every file and directory must justify its existence.
- **CPU-only by default.** No assumption of GPU availability anywhere in the design.
- **Incremental.** Structure comes before implementation; nothing here is built
  ahead of need.
- **Maintainability over cleverness.** Favor clear, boring solutions over
  premature abstraction.

Infrastructure and application services are brought up incrementally, one
at a time, each establishing a stable baseline before the next is added.
Four services are currently running: Ollama (LLM inference), SearXNG
(search), PostgreSQL + pgvector (persistence), and the Prediction API (AI
Core). See [docs/DOCKER_ARCHITECTURE.md](docs/DOCKER_ARCHITECTURE.md) for
current deployment status of all services.
