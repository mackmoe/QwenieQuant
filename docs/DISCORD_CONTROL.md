# Discord Control

The platform's operator interface. Seventh service (SPEC-011), after
[Ollama](OLLAMA.md), [SearXNG](SEARXNG.md), [PostgreSQL](POSTGRES.md),
[prediction-api](PREDICTION_API.md), [learning-engine](LEARNING_ENGINE.md),
and [reflection-engine](REFLECTION_ENGINE.md).

## Purpose

Discord Control is an operational control plane — a thin coordination layer
that forwards operator commands to existing platform services and returns
formatted responses. It contains no business logic, no AI reasoning, and no
direct database access. Every capability it exposes lives in another service.

**What it does:**
- Accepts slash commands from authorized Discord users
- Forwards requests to Prediction API, Learning Engine, Reflection Engine
- Returns concise, readable formatted responses

**What it does not do:**
- Execute trades or autonomous decisions
- Access PostgreSQL directly
- Call Ollama directly
- Implement conversational AI
- Restart infrastructure

## Command Reference

All commands are guild-specific (instant propagation after bot start).
Unauthorized users receive a denial message — the command does not execute.

### `/status`

Returns a single-screen overview of all platform services.

```
Platform Status
✅ Prediction API — ok
✅ Learning Engine — ok
✅ Reflection Engine — ok
✅ PostgreSQL — ok
✅ Ollama — reachable
✅ SearXNG — reachable
```

Checks are run concurrently. Each ✅/❌ icon is live state at the time the
command runs.

---

### `/predict`

**Parameters:**
- `question` (required) — the prediction question, 10–500 characters
- `category` (optional, default: `finance`) — one of `finance`, `politics`,
  `sports`, `weather`

Forwards to `POST /predict` on the Prediction API. Returns the model's
answer and confidence. Reasoning is shown, truncated at 300 characters.

⚠️ This command can take up to 5 minutes on CPU — the bot defers immediately
and sends a followup when the prediction is ready.

---

### `/analyze`

No parameters. Invokes `POST /analyze` on the Learning Engine with default
settings (up to 250 recent predictions, no date filters). Returns aggregate
metrics and up to 5 observations.

---

### `/reflect`

No parameters. Runs a fresh `/analyze` internally, then forwards the resulting
`analysis_id` to `POST /reflect` on the Reflection Engine. Returns structured
strengths, weaknesses, patterns, and recommendations.

## Authorization

Command execution is restricted to an allow-list of Discord user snowflake IDs
defined in `ALLOWED_USER_IDS`. Unauthorized users receive:

```
❌ You are not authorized to use this command.
```

The allow-list is checked before any service call is made. Authorization is
stateless — no database lookup, no session — just a membership check against
the configured set.

## Service Communication

All service calls use HTTP. No direct PostgreSQL or Ollama access.

```
Discord user
    │
    ▼ slash command
discord-control
    ├─ GET  prediction-api:8000/health    (/status)
    ├─ POST prediction-api:8000/predict   (/predict)
    ├─ GET  learning-engine:8001/health   (/status)
    ├─ POST learning-engine:8001/analyze  (/analyze, /reflect)
    ├─ GET  reflection-engine:8002/health (/status)
    ├─ POST reflection-engine:8002/reflect (/reflect)
    ├─ GET  ollama:11434/api/tags         (/status, reachability probe)
    └─ GET  searxng:8080/healthz          (/status, reachability probe)
```

All calls use `httpx.AsyncClient`. Health probes time out at 5 s. `/predict`
uses a 330 s override to accommodate qwen3:8b's thinking chain.

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | Yes | Bot token from Discord Developer Portal |
| `DISCORD_GUILD_ID` | Yes | Server (guild) ID for slash command registration |
| `ALLOWED_USER_IDS` | Yes | Comma-separated user snowflakes authorized to run commands |
| `PREDICTION_API_URL` | No | Default: `http://prediction-api:8000` |
| `LEARNING_ENGINE_URL` | No | Default: `http://learning-engine:8001` |
| `REFLECTION_ENGINE_URL` | No | Default: `http://reflection-engine:8002` |
| `OLLAMA_URL` | No | Default: `http://ollama:11434` |
| `SEARXNG_URL` | No | Default: `http://searxng:8080` |
| `HTTP_TIMEOUT` | No | Default: `60.0` (seconds; `/predict` overrides to 330 s) |

### ALLOWED_USER_IDS format

`ALLOWED_USER_IDS` accepts plain comma-separated Discord user snowflakes.
Whitespace around commas is ignored.

**Single user:**

```env
ALLOWED_USER_IDS=444992730335019019
```

**Multiple users:**

```env
ALLOWED_USER_IDS=444992730335019019,123456789012345678
```

Do not use JSON array syntax (`[...]`) or quoted strings — plain integers
and commas only. Empty segments (consecutive commas or a leading/trailing
comma) are rejected at startup.

## Deployment

The service requires real Discord credentials. The container is left stopped
by default. Once credentials are set in `compose/.env`:

```sh
docker compose up -d discord-control
```

The bot registers slash commands to the configured guild on startup (`on_ready`).
Commands are available immediately in Discord after registration. The Docker
healthcheck verifies the bot connected by checking for a `/tmp/bot_ready` signal
file written when `on_ready` fires.

## Service Layout

```text
services/discord-control/
├── app/
│   ├── main.py         — entry point: creates httpx client, clients, bot
│   ├── config.py       — pydantic-settings (all env vars, user ID parsing)
│   ├── clients.py      — PredictionClient, LearningClient, ReflectionClient,
│   │                      check_reachable (Ollama/SearXNG probes)
│   ├── health.py       — check_all_services() (concurrent health aggregation)
│   ├── formatter.py    — format_status/prediction/analysis/reflection/error
│   ├── commands.py     — is_authorized, handle_status/predict/analyze/reflect
│   ├── discord_bot.py  — create_bot(), slash command registration, on_ready
├── tests/
│   ├── test_formatter.py  — 19 tests
│   ├── test_clients.py    — 12 tests
│   └── test_commands.py   — 18 tests (49 total)
├── pytest.ini          — asyncio_mode = auto
├── Dockerfile
└── requirements.txt
```

## Logging

Each command handler logs: command name, user ID, elapsed time, success/failure.
Example:

```
2026-07-02 04:00:01 INFO app.commands predict user=123456789012345678 category=finance elapsed=179300ms success=True
```

No secrets (tokens, passwords) are logged.

---

## Implementation Observations

These are observations for future phases, not changes to this implementation.

**1. No audit trail.** Commands are logged to stdout but not persisted. A
future phase should record each command, user, timestamp, and result to
`system.command_log` in PostgreSQL for auditability and usage analytics.

**2. `/predict` response latency.** At ~3 tok/s on CPU, qwen3:8b can take
3–5 minutes. Discord's "Bot is thinking…" spinner covers this, but the 330 s
timeout is tightly matched to the Ollama timeout in prediction-api. If
prediction-api's timeout is raised, this client override should be updated.

**3. Authorization is binary.** All authorized users have identical permissions.
A future phase could implement role-based access (e.g., read-only operators vs.
full operators) using Discord roles rather than a flat user ID list.

**4. `/reflect` always runs a fresh analysis.** This is simple and ensures the
reflection is based on current data, but adds latency and creates a new
`learning.learning_summaries` row on every `/reflect` call. A future phase
could accept an optional `analysis_id` parameter to reflect on a prior analysis
without triggering a new one.

**5. No published port.** discord-control exposes no HTTP endpoint. The Docker
healthcheck uses a signal file (`/tmp/bot_ready`) written by `on_ready`. This
is lightweight but only confirms the bot connected at some point in the past —
not that the WebSocket is currently healthy. A future phase could add an
aiohttp-based health endpoint on a secondary port.

**6. Single guild.** Commands are registered to one guild. Registering to
additional guilds (or globally) requires extending the `create_bot` function.
Global registration takes up to 1 hour to propagate and is not appropriate for
an operational control plane.
