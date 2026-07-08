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
- Forwards requests to Prediction API, Learning Engine, Reflection Engine, Opportunity Engine, Prediction Queue
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

### `/brief`

No parameters. The primary operational command for daily use.

Answers: *"If I haven't looked at the platform for several hours, what do I need to know?"*

Makes seven concurrent service calls (Opportunity Engine, Prediction Queue, Learning
Engine, Prediction API, Risk Manager) then runs a sequential reflection — all fast,
rule-based, no LLM. Optimised for mobile readability in under 30 seconds.

**Output sections:**

| Section | Content | Source |
|---|---|---|
| 🟢/🔴 **Platform** | Status, Uptime, Last Activity | All service health endpoints |
| 📊 **Activity** | Markets Scanned, Predictions completed | OE health, PQ stats |
| 📈 **Performance** | Accuracy, Confidence, Calibration, Resolved, Open | Learning Engine `/analyze` |
| ⭐ **Best Opportunity** | Title, Priority, Tier, Expiry | OE `/opportunities?limit=1` |
| 🧠 **Reflection** | Up to 2 strengths, 2 weaknesses, 1 recommendation | Reflection Engine `/reflect` |
| 🚨 **Operator Attention** | Flags any services down or Kalshi auth failure | Derived from health responses |

**Example output (all services healthy, history available):**

```
Platform Brief

🟢 Platform
Status: Running
Uptime: 18h 42m
Last Activity: 14m ago

📊 Activity
Markets Scanned: 1,084
Predictions: 214

📈 Performance
Accuracy: 63.8%
Confidence: 61.4%
Calibration: Active
Resolved: 482
Open: 91

⭐ Best Opportunity
Will BTC exceed $120,000?
Priority: 94.2  Tier: 3
Expires: 2h 24m

🧠 Reflection
Strength: Weather predictions improving.
Weakness: Finance confidence remains too high.
Recommendation: Continue monitoring confidence calibration.

✅ No operator action required.
```

**Cold start (no resolved predictions yet):**

```
📈 Performance
*Insufficient historical data.*
```

**Operator attention example (Kalshi auth failed):**

```
🚨 Operator Attention
• Kalshi authentication failed.
```

**Failure behavior:** All seven initial calls use `asyncio.gather(..., return_exceptions=True)`.
Each section degrades independently — a failed service produces a reduced section, not a
failed command. Reflection is skipped (not errored) when Learning Engine is unavailable.
The response is always a valid string within Discord's 2,000-character limit.

**Data sources summary:**
- Platform Status and Last Activity: OE, PQ, Prediction API, Risk Manager `/health`
- Activity: OE `markets_scored`, PQ `by_state.COMPLETED`
- Performance: Learning Engine `POST /analyze`
- Best Opportunity: OE `GET /opportunities?limit=1`
- Reflection: LE `POST /analyze` → RE `POST /reflect` (rule-based, no LLM)
- Operator Attention: derived from all health responses + `kalshi_connector` flag

---

---

## Automatic Workflow Notifications

When `DISCORD_NOTIFICATION_CHANNEL_ID` is set, the bot automatically posts one
notification to that channel after every completed autonomous workflow cycle. No
slash command is needed.

### Trigger

The notifier polls the Opportunity Engine `/health` endpoint every 60 seconds
for a changed `last_scan` timestamp. When detected, it waits 120 seconds (grace
period for downstream processing — prediction queue, risk manager, learning
engine, reflection engine), then gathers state from all services and posts
exactly one message.

**Manual scans** (`/scan`) are labelled `Manual` in the notification header.
Scheduled scans are labelled `Scheduled`.

### Example notification

```
🤖 Prediction Platform Update
Workflow #3 | Scheduled | 2026-07-08 14:00 UTC

🟢 Platform
Status: Healthy
Last Activity: Just now

📊 Activity
Markets Scanned: 1,042
Queued: 30
Predictions: 30

📈 Performance
Accuracy: 63.8%
Confidence: 61.4%
Calibration: Active
Resolved: 482
Open: 91
Model: qwen3:8b

⭐ Best Opportunity
Will BTC exceed $120,000?
Priority: 94.2  Tier: 3
Expires: 2h 24m

🧠 Learning
• Sports predictions continue outperforming finance.
• Recent calibration reduced average confidence by 6%.

💡 Reflection
Strength: Prediction consistency improved.
Weakness: Finance confidence remains too high.
Recommendation: Continue monitoring calibration performance.

✅ No operator action required.

──────────────
Quick Commands: `/brief`  `/markets`  `/scan`  `/performance`  `/activity`
```

### Configuration

| Variable | Required | Description |
|---|---|---|
| `DISCORD_NOTIFICATIONS_ENABLED` | No | Default: `true` — set to `false` to disable all notifications |
| `DISCORD_NOTIFICATION_CHANNEL_ID` | No | Discord channel snowflake ID; leave blank to disable |

Notifications are disabled when `DISCORD_NOTIFICATION_CHANNEL_ID` is empty or
`DISCORD_NOTIFICATIONS_ENABLED=false`. Slash commands are unaffected in either case.

### Notification sections

| Section | Content | Source |
|---|---|---|
| Header | Workflow #, trigger (Scheduled/Manual), timestamp | In-memory counter + OE `last_scan` |
| 🟢/🔴 Platform | Status, Last Activity | All service health endpoints |
| 📊 Activity | Markets Scanned, Queued, Predictions | OE health, PQ stats |
| 📈 Performance | Accuracy, Confidence, Calibration, Resolved, Open, Model | LE `/analyze` |
| ⭐ Best Opportunity | Title, Priority, Tier, Expiry | OE `/opportunities?limit=1` |
| 🧠 Learning | Up to 2 key observations | LE `/analyze` observations field |
| 💡 Reflection | Up to 2 strengths, 2 weaknesses, 1 recommendation | RE `/reflect` |
| 🚨 Operator Attention | Service failures, Kalshi auth, zero markets | Derived from health responses |
| Quick Commands | Static reminder of useful slash commands | Static text |

Learning and Reflection sections are omitted when the respective engines are
unavailable or return no data.

### Failure behavior

Discord failures are logged and silently absorbed. The workflow never depends on
notification delivery — a failed send does not interrupt, retry, or delay any
autonomous processing. If the configured channel is not found, an error is
logged and no message is sent.

---

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

---

### `/markets`

Read-only. Retrieves the currently ranked market opportunities from the
Opportunity Engine. Does not trigger predictions, queue markets, or execute
trades.

**Parameters:**
- `category` (optional, default: `All`) — one of `All`, `Finance`, `Politics`,
  `Sports`, `Weather`

When a category is provided, the results are filtered client-side by matching
the category string against each market's title and ticker.

**Example output:**

```
Kalshi Market Opportunities

1. Will BTC close above $120,000 today?
Ticker: `KXBTC-24DEC25-T120000`
Priority: 94.2  |  Tier: 3  |  Expires: 4h
────────────────────────────
2. Will Dallas reach 100°F tomorrow?
Ticker: `KXWEATHER-DALLAS-100F`
Priority: 91.7  |  Tier: 3  |  Expires: 1d 17h
────────────────────────────
...
Showing 10 of 843 opportunities.
```

**Empty result:**

```
No opportunities are currently available.
```

**Service unavailable:**

```
❌ Opportunity Engine is currently unavailable.
```

No stack traces are exposed. The bot does not crash on service failure.

---

### `/scan`

No parameters. Triggers an immediate market scan on the Opportunity Engine via
`POST /refresh`. The engine re-fetches all active Kalshi markets, scores them,
and returns the results. The command blocks until the scan completes (typically
2–6 seconds) and reports the outcome.

Use this after a stack restart (the OE has a 300-second startup delay before
its first automatic scan) or anytime you want fresh market data without waiting
for the next scheduled cycle.

**Example output (scan completed):**

```
✅ Market scan complete.
The Opportunity Engine has completed a new market discovery cycle.

**Markets Scored:** 1,084
**Tier 3 Candidates:** 28
**Duration:** 4.2s
**Completed:** 14:37 UTC
```

**Service unavailable:**

```
❌ Opportunity Engine unavailable.
Unable to start market scan.
```

**Failure behavior:** The OE `/refresh` error response is returned as an error
dict by the client layer. The formatter degrades cleanly — no stack trace is
exposed. The response is always a valid string.

---

### `/workflow`

No parameters. Returns a real-time platform activity summary by making six
concurrent service calls (Opportunity Engine, Prediction Queue health+stats,
Learning Engine, Reflection Engine, Prediction API). Any individual call
failure is isolated — the command always returns.

**Example output (all services healthy):**

```
Prediction AI Platform

Status: ✅ Running

Markets Scanned: 1,084
Tier 3 Candidates: 28
Queued: 12
In Progress: No
Completed: 187
Failed: 0

Prediction API: ✅  Learning: ✅  Reflection: ✅

Last Scan: 14m ago
```

**Degraded (one or more services down):**

```
Prediction AI Platform

Status: ⚠️ Degraded

Markets Scanned: Unavailable
...
```

**Failure behavior:** Each of the six service calls uses
`asyncio.gather(..., return_exceptions=True)`. A connection error on any
single service degrades the status display for that data source without
crashing the command. The response is always a valid string.

---

### `/performance`

No parameters. Calls `POST /analyze` on the Learning Engine and returns
accuracy, confidence, and calibration metrics.

**Example output (sufficient history):**

```
Platform Performance

Accuracy: 63.8%
Confidence: 61.4%
Calibration: Active
Resolved: 482
Open: 91
Predictions: 573

Model: qwen3:8b
```

**Cold start (fewer than 1 resolved outcome):**

```
Platform Performance

*Insufficient historical data.*

Predictions: 5
Calibration: Active
Model: qwen3:8b
```

**Service unavailable:**

```
Platform Performance

❌ Learning Engine unavailable.

Calibration: Active
```

**Calibration column** reflects the `CONFIDENCE_CALIBRATION_ENABLED`
setting at the time the command runs — it is display-only and mirrors
the prediction-api setting.

---

### `/run`

No parameters. Manually executes one complete workflow iteration using the
same code path as the autonomous scheduler: `queue.get_next()` → Prediction
API → Risk Manager → Kalshi order (if approved and not dry-run).

**Concurrency:** A single `asyncio.Lock` is shared between the scheduler and
manual executions. Only one iteration runs at a time.

- If the scheduler is currently running, `/run` responds immediately with a
  "busy" message showing the start time and elapsed seconds.
- If `/run` is already running, the scheduler skips its next cycle (logs
  "workflow_skipped reason=lock_held") and `/run` responds with "busy".

The response is deferred (Discord "Bot is thinking…") because the Prediction
API can take up to 5 minutes on CPU. The deferred timeout is 5 minutes.

**Example — completed:**

```
✅ Workflow Run Complete

Market: Gabriel Moreno: 1+
Ticker: MKT-XYZ
Prediction: Yes
Confidence: 75%
Risk: ❌ Rejected
Trade Status: rejected
Duration: 3.2s
*Dry-run mode — no real trades placed.*
```

**Example — queue empty:**

```
📭 Workflow Run Complete

*The queue is empty — no markets are awaiting prediction.*
```

**Example — another execution in progress:**

```
⚙️ Workflow Already Running
Started: 2026-07-07T23:00:00+00:00
Elapsed: 42s

*Try again when the current execution completes.*
```

**Example — downstream service requeued:**

```
🔄 Workflow Run — Requeued

Market: Will BTC exceed $120k?
Prediction: Yes
Confidence: 80%

*A downstream service was unavailable. The market has been requeued for retry.*
```

**Failure behavior:** If an unexpected error occurs during the workflow
iteration, the queue entry is marked FAILED and the response contains
status `failed`. The lock is always released, even on exceptions.

---

### `/activity`

No parameters. Returns a reverse-chronological timeline of recent platform
events: completed prediction queue entries and the most recent opportunity
scan. Events from the Prediction Queue and Opportunity Engine are fetched
concurrently and merged by timestamp.

**Example output:**

```
Recent Activity (newest first)

`22:14` · Prediction · Will BTC exceed $120k?
`22:09` · Prediction · Will gold close above $3,100?
`12:00` · Opportunity Scan · 1,084 markets
`11:47` · Prediction · Will EUR/USD fall below 1.08?
```

Each entry shows the HH:MM (UTC) of the event. Prediction entries show the
market title (truncated to 28 characters). Opportunity Scan entries show the
market count from the most recent scan.

**Empty queue, no OE scan:**

```
Recent Activity

*No recent activity.*
```

**Prediction Queue unavailable, OE available:**

```
Recent Activity (newest first)

`12:00` · Opportunity Scan · 1,084 markets
```

**Both unavailable:**

```
Recent Activity

❌ Prediction Queue unavailable.
```

**Failure behavior:** Prediction Queue and Opportunity Engine are fetched
concurrently with `asyncio.gather(..., return_exceptions=True)`. If either
fails, the other's data is still shown. The response is capped at 1,900
characters to stay safely under Discord's 2,000-character hard limit.

---

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
    ├─ GET  prediction-api:8000/health        (/status, /workflow)
    ├─ POST prediction-api:8000/predict       (/predict)
    ├─ GET  learning-engine:8001/health       (/status, /workflow)
    ├─ POST learning-engine:8001/analyze      (/analyze, /reflect, /performance)
    ├─ GET  reflection-engine:8002/health     (/status, /workflow)
    ├─ POST reflection-engine:8002/reflect    (/reflect)
    ├─ GET  opportunity-engine:8005/health    (/workflow, /activity)
    ├─ GET  opportunity-engine:8005/opportunities  (/markets)
    ├─ POST opportunity-engine:8005/refresh   (/scan, immediate market discovery)
    ├─ GET  prediction-queue:8006/health      (/workflow, /brief)
    ├─ GET  prediction-queue:8006/queue?limit=1          (/workflow, /brief, queue stats)
    ├─ GET  prediction-queue:8006/queue?state=COMPLETED  (/activity, recent events)
    ├─ GET  risk-manager:8004/health          (/brief, Kalshi auth + dry_run status)
    ├─ GET  ollama:11434/api/tags             (/status, reachability probe)
    └─ GET  searxng:8080/healthz              (/status, reachability probe)
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
| `OPPORTUNITY_ENGINE_URL` | No | Default: `http://opportunity-engine:8005` |
| `PREDICTION_QUEUE_URL` | No | Default: `http://prediction-queue:8006` |
| `RISK_MANAGER_URL` | No | Default: `http://risk-manager:8004` |
| `CONFIDENCE_CALIBRATION_ENABLED` | No | Default: `true` — display-only; mirrors prediction-api setting for `/performance` and `/brief` |
| `DISCORD_NOTIFICATIONS_ENABLED` | No | Default: `true` — set to `false` to disable automatic workflow notifications |
| `DISCORD_NOTIFICATION_CHANNEL_ID` | No | Discord channel snowflake ID for automatic notifications; leave blank to disable |
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
│   ├── main.py         — entry point: creates httpx client, all clients, bot
│   ├── config.py       — pydantic-settings (all env vars, user ID parsing)
│   ├── clients.py      — PredictionClient, LearningClient, ReflectionClient,
│   │                      OpportunityClient, PredictionQueueClient,
│   │                      RiskManagerClient,
│   │                      check_reachable (Ollama/SearXNG probes)
│   ├── health.py       — check_all_services() (concurrent health aggregation)
│   ├── formatter.py    — format_status/prediction/analysis/reflection/markets/error
│   │                      format_workflow/performance/activity/scan/brief/notification
│   │                      _time_ago, _fmt_hhmm, _fmt_uptime, _fmt_completed_at
│   ├── commands.py     — is_authorized,
│   │                      handle_status/predict/analyze/reflect/markets
│   │                      handle_workflow/performance/activity/scan/brief
│   ├── notifier.py     — WorkflowNotifier (background poller, autonomous notifications)
│   ├── discord_bot.py  — create_bot(), slash command registration, on_ready
├── tests/
│   ├── test_formatter.py  — 19 tests
│   ├── test_clients.py    — 12 tests
│   ├── test_commands.py   — 18 tests
│   ├── test_markets.py    — 38 tests
│   ├── test_dashboard.py  — 54 tests
│   ├── test_brief.py      — 59 tests
│   ├── test_scan.py       — 19 tests
│   └── test_notifier.py   — 59 tests (278 total)
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

**7. `/markets` category filtering is approximate.** The Opportunity Engine's
`ScoredMarket` model does not include a `category` field — Kalshi's `/markets`
endpoint does not return category; it lives on the `/events` endpoint. The
current implementation filters client-side by matching the category string
against market titles and tickers, which is heuristic and may miss or
mis-classify markets. A future phase should have the Opportunity Engine store
and expose the category from the events endpoint, enabling precise server-side
filtering. Pagination, sort options, search-by-ticker, and rich Discord embeds
are also natural improvements for `/markets`.

**9. `/brief` activity counts are incomplete.** The Activity section shows Markets Scanned
(from OE health) and Predictions Completed (from PQ `by_state.COMPLETED`), but cannot
show Risk Approved/Rejected counts, Dry Run Trades, Live Trades, or Learning/Reflection
cycle counts — no existing API endpoint exposes these aggregates. A future phase could
add a `GET /stats` endpoint to the Risk Manager and a `GET /workflow/summary` to the
Prediction Queue to surface these counts without direct database access.

**10. `/brief` always creates new Postgres rows.** Calling `/brief` triggers `POST /analyze`
(which writes a new `learning.learning_summaries` row) and `POST /reflect` (which writes a
new `reflection.reflections` row). This is normal service behavior, but running `/brief`
frequently accumulates rows faster than running `/analyze` and `/reflect` separately. A
future phase could add `GET /analyze/latest` and `GET /reflect/latest` endpoints to return
cached results when recent data is sufficient.

**11. No stored-reflection retrieval.** The Reflection Engine has no `GET /reflections/latest`
endpoint. `/brief` always triggers a fresh analyze+reflect cycle rather than reading a
previously computed result. The reflection is deterministic and rule-based (no LLM), so the
cost is low but non-zero. A future phase should add a retrieval endpoint.

**8. Single guild.** Commands are registered to one guild. Registering to
additional guilds (or globally) requires extending the `create_bot` function.
Global registration takes up to 1 hour to propagate and is not appropriate for
an operational control plane.

**12. Notification grace period is approximate.** The notifier waits 120 seconds
after detecting a new OE scan before collecting state and posting. This is long
enough for typical single-prediction cycles but may not cover large batches (e.g.,
30 tier-3 predictions at ~3 min each on CPU). A future phase could expose a
`GET /workflow/status` endpoint on the Prediction Queue that signals when all
in-flight items for a given scan have resolved.

**13. Workflow number resets on container restart.** `WorkflowNotifier._workflow_count`
is in-memory. Restarting discord-control resets it to zero. A future phase could
persist the counter to PostgreSQL via a `system.workflow_runs` table.

**14. Manual trigger detection is best-effort.** `signal_manual_trigger()` is called
before `/scan` runs, but a concurrent scheduled scan occurring at the same moment
could consume the flag. In practice, with an hourly scan interval, this race is
negligible. A future phase could include a scan origin field in the OE health
response to make trigger detection authoritative.

**15. Several activity fields are unavailable.** The spec calls for Risk Approved/
Rejected, Dry Run/Live Trades, Learning/Reflection cycle counts, Average Edge,
Dry Run ROI, and Live ROI. No existing API endpoint exposes these aggregates.
A future phase could add `GET /stats` to the Risk Manager and a workflow summary
endpoint to the Prediction Queue to surface these without direct database access.

**16. Notification also triggers new Postgres rows.** Each `_build_message()` call
runs `POST /analyze` (new `learning.learning_summaries` row) and `POST /reflect`
(new `reflection.reflections` row). With hourly scans, this adds 2 rows/hour
beyond what commands already create. Future `GET /latest` endpoints on both
services would eliminate this overhead.
