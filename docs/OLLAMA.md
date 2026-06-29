# Ollama

Local LLM inference for the platform. First production service deployed
(SPEC-004). Every other service stays disabled until its own deployment
phase.

## Installed Models

| Model | Purpose | Size |
|---|---|---|
| `qwen3:8b` | Primary reasoning model | 5.2 GB |
| `nomic-embed-text` | Embedding model | 274 MB |

No other models are installed. `qwen3:8b` is a "thinking" model — by
default it emits a reasoning trace (returned as a separate `thinking`
field by the API) before its final answer, which materially affects
latency (see Benchmark below).

## API Endpoint

```
http://127.0.0.1:11434
```

Published on the host's loopback interface only (`127.0.0.1:11434`), so
the API is reachable from local clients but not from outside the machine.
Other containers on the `internal` compose network reach it as
`http://ollama:11434`.

Verified working:

```
curl http://127.0.0.1:11434/api/version
curl http://127.0.0.1:11434/api/generate -d '{"model":"qwen3:8b","prompt":"..."}'
curl http://127.0.0.1:11434/api/embed -d '{"model":"nomic-embed-text","input":"..."}'
```

## Persistence

Models are stored on the named Docker volume `ollama_models`, mounted at
`/root/.ollama` inside the container (host-side at
`/var/lib/docker/volumes/compose_ollama_models/_data`). Verified by
stopping, removing, and recreating the container: both models were still
present afterward with no re-download.

## Deployment

```
cd compose
cp .env.example .env   # set OLLAMA_PORT
docker compose up -d ollama
```

Only the `ollama` service is enabled. `postgres`, `searxng`, and the three
application services remain commented out in `docker-compose.yml` until
their own deployment phases.

## Verification Performed

- Container reaches and stays in `healthy` state (`ollama list` healthcheck).
- API responds on `/api/version`, `/api/generate`, and `/api/embed`.
- Exactly two models installed, both required, no extras.
- Model storage survives container stop/remove/recreate.
- `docker compose ps` / `docker ps` confirm no other platform service
  (`postgres`, `searxng`, or any application service) is running.
- Restart policy is configured as `unless-stopped` (confirmed via
  `docker inspect`), and the container correctly comes back `healthy`
  after a stop/start cycle with no data loss.

## Benchmark (Baseline, Not Optimized)

Test machine: 6 CPU cores, ~15 GiB RAM, CPU-only (no GPU). Test prompt:
*"In one sentence, what is the capital of France?"*

| Metric | Cold start (model not loaded) | Warm (model already loaded) |
|---|---|---|
| Model load time | 11.5s | 0.2s (already resident) |
| Time to first token (incl. reasoning) | 13.2s | 1.7s |
| Time to first answer token (after reasoning) | 58.3s | 50.7s |
| Time to complete short prompt | 60.4s | 52.9s |
| Peak RAM during inference | 5.53 GiB | 5.52 GiB |
| Peak CPU during inference | ~600% (saturates all 6 cores) | ~595% |
| Generation rate (reasoning + answer tokens) | ~3.4 tok/s | ~3.4 tok/s |
| Idle RAM (model unloaded) | ~13–30 MiB | — |

Most of the latency for this model comes from its reasoning trace, not
from prompt processing or model loading — the first *visible* answer
token only appears after ~50-190 reasoning tokens have been generated at
~3.4 tokens/sec on this CPU-only hardware. These are unoptimized
baseline numbers for context length, quantization, threads, etc.; no
tuning was attempted in this phase.
