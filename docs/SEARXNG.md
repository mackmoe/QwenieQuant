# SearXNG

Self-hosted, metasearch-based web search for the platform. Second
production service deployed (SPEC-005), after [Ollama](OLLAMA.md). It
exists so `prediction-api` (once built) can research current events
without depending on a third-party search API.

## Service Purpose

Prediction-market agents need up-to-date, real-world information to
reason about open questions. SearXNG provides that as a self-hosted JSON
API, aggregating a small set of underlying search backends — no API key,
no per-query cost, no external dependency on a commercial search API
provider.

This deployment is **internal-only and machine-facing**: it has no
published host port and no human ever browses its web UI. It is reached
only by other containers on the `internal` Docker network, returning
JSON for programmatic consumption.

## API Endpoint

```
http://searxng:8080
```

Reachable only from other containers on the compose `internal` network
(Docker's embedded DNS resolves the container name). There is no
host-published port — `docker port searxng` returns nothing, and
`docker compose config` shows no `ports:` entry for the service.

Key routes:

- `GET /healthz` → `200 OK` liveness check (used by the container healthcheck).
- `GET /search?q=...&format=json` → JSON search results.
- `GET /config` → JSON description of the running instance, including
  which engines are currently enabled — useful for verifying the engine
  set without reading server-side config.

Example (run from another container on the `internal` network):

```
curl "http://searxng:8080/search?q=capital+of+France&format=json"
```

## Configuration Location

```
config/searxng/settings.yml
```

This file is version-controlled and bind-mounted **read-only** into the
container at `/etc/searxng/settings.yml`. SearXNG's entrypoint only
auto-generates a settings file when none exists at that path — since the
bind mount is always present, the container never silently regenerates or
drifts from what's in the repo.

Two supporting named volumes exist for files SearXNG itself manages at
runtime, neither of which is configuration:

- `searxng_config` → `/etc/searxng` (any non-settings files SearXNG keeps there)
- `searxng_cache` → `/var/cache/searxng` (on-disk query cache)

`server.secret_key` in `settings.yml` is a static, committed, plain
human-readable string — deliberately **not** a generated secret. The key
only signs CSRF/session tokens for a service with no published port and
no human browser session ever created against it, so it carries no real
exposure, and committing a high-entropy generated value would look like
(and trigger detection as) a leaked credential for no actual security
benefit. SearXNG does require the value to differ from its own shipped
placeholder (`ultrasecretkey`) — it refuses to start otherwise — so a
plain, obviously-non-secret string is used instead. Keeping it as a
literal also avoids SearXNG's entrypoint silently regenerating a new one
in the volume on every fresh deploy, which would make the deployment
non-reproducible for no benefit.

## Enabled Engines

Only three engines are enabled, out of 84 enabled by default in the
upstream image. Each is enabled via `use_default_settings.engines.keep_only`
in `settings.yml`, which disables every other default engine outright.

| Engine | Why |
|---|---|
| `duckduckgo` | Primary general web search. No API key, no usage cost. |
| `google` | Second general web search backend, for redundancy — if one backend gets rate-limited or blocked, queries still succeed via the other. Broad, current coverage of news and events relevant to prediction markets. |
| `wikipedia` | Structured background facts (people, places, organizations) referenced in market questions. Returned as an infobox, not a search result. |

Everything else the image ships with — images, video, music, torrents,
code search, academic search, maps, translation, etc. — is disabled.
None of it serves the "research a prediction-market question" use case,
and every additional engine is one more thing that can break or get
rate-limited for no benefit (per "optimize for reliability over
breadth").

## Health Verification

Performed and confirmed:

- Container reaches and stays in `healthy` state. Healthcheck is
  `wget --spider http://localhost:8080/healthz` (curl is not present in
  the image; wget is).
- `GET /healthz` returns `200 OK`.
- `GET /config` confirms exactly `duckduckgo`, `google`, and `wikipedia`
  are enabled — nothing else.
- `GET /search?q=...&format=json` returns real results from `google` and
  `duckduckgo`, and a Wikipedia infobox for an entity query (tested with
  "capital of France" and "Albert Einstein").
- Reachable by container name (`http://searxng:8080`) from another
  container on the `internal` network — verified with a throwaway
  `curlimages/curl` container attached to the same network.
- No host port is published — verified via `docker port searxng`
  (empty) and `docker compose config` (no `ports:` key for the service).
- Ollama remained `healthy` throughout SearXNG's deployment, restart, and
  testing — the two services don't interfere with each other.

## Restart Verification

Performed and confirmed:

- `docker compose stop searxng && docker compose rm -f searxng && docker compose up -d searxng`
  recreates the container cleanly and it reaches `healthy` again within
  the healthcheck's `start_period`.
- After recreation, `/config` still shows exactly the same three engines
  enabled, and `settings.yml` inside the container is unchanged — proving
  the bind-mounted config (not container-internal state) is the source
  of truth.
- `restart: unless-stopped` is set, matching the policy used for `ollama`.
- Ollama was unaffected by SearXNG's stop/remove/recreate cycle, and
  vice versa — each service's lifecycle is independent.

## Deployment

```
cd compose
cp .env.example .env   # set OLLAMA_PORT; SearXNG needs no variables
docker compose up -d searxng
```

Only `ollama` and `searxng` are enabled. `postgres` and the three
application services remain commented out in `docker-compose.yml` until
their own deployment phases.
