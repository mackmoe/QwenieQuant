# Kalshi Connector

The platform's Kalshi API abstraction layer. Eighth service (SPEC-012), after
[Discord Control](DISCORD_CONTROL.md).

## Purpose

The Kalshi Connector is a thin HTTP abstraction layer that provides a clean,
normalized interface between the Prediction AI Platform and the Kalshi
prediction market API. It normalizes Kalshi's API responses into
platform-friendly models, isolating the rest of the platform from Kalshi's
API structure and from changes to it.

**What it does:**
- Authenticates with Kalshi (RSA-PSS signed requests)
- Retrieves active markets and market details
- Retrieves order books
- Retrieves account balance
- Retrieves open positions
- Places limit orders
- Cancels orders
- Normalizes all Kalshi responses to platform-friendly models
- Periodically polls PostgreSQL for unresolved predictions and records resolved outcomes (SPEC-018)
- Triggers the Learning Engine after each outcome is recorded (fire-and-forget)

**What it does not do:**
- Make trading decisions
- Implement bankroll management or risk management
- Call the Prediction API
- Modify existing prediction records
- Perform learning or reflection (triggers Learning Engine, does not implement it)

The connector is an API abstraction layer and outcome collection agent.

## Authentication

Kalshi's v2 API uses RSA-PSS signature authentication. Each request carries
three headers:

| Header | Value |
| --- | --- |
| `KALSHI-ACCESS-KEY` | Your API key, identifying the account |
| `KALSHI-ACCESS-SIGNATURE` | Base64-encoded RSA-PSS/SHA-256 signature |
| `KALSHI-ACCESS-TIMESTAMP` | Milliseconds since Unix epoch (as a string) |

The signed message is: `{timestamp_ms}{METHOD}{/trade-api/v2/path}` — the
same path used in the URL, including the `/trade-api/v2` prefix, without
query parameters.

Authentication is implemented in `app/authentication.py`. The private key is
never logged, cached beyond the request, or stored anywhere except the
in-memory settings object.

## Supported Endpoints

### GET /health

Returns service status and Kalshi connectivity.

```json
{
    "status": "ok",
    "credentials_configured": true,
    "kalshi_reachable": true,
    "environment": "production",
    "version": "0.1.0"
}
```

`status` is `"ok"` only when credentials are configured AND Kalshi is
reachable. Otherwise `"degraded"`. `"starting"` is returned if the service
has not yet initialized.

---

### GET /account

Returns the account's available cash balance.

```json
{
    "balance": 100000,
    "portfolio_value": 0
}
```

All monetary values are in **cents** throughout the platform. `balance` is
the available cash. `portfolio_value` is non-zero when Kalshi returns it from
the balance endpoint.

---

### GET /markets

Returns a list of markets. Supports query parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `limit` | `100` | Number of markets to return (1–1000) |
| `status` | `"active"` | Market status filter (`active`, `closed`, `settled`) |
| `series_ticker` | — | Filter by series (e.g. `AAPL`) |

```json
[
    {
        "ticker": "AAPL-24-GT150",
        "title": "Will AAPL close above $150?",
        "status": "active",
        "yes_bid": 55,
        "yes_ask": 57,
        "no_bid": 43,
        "no_ask": 45,
        "volume": 1000,
        "open_interest": 200,
        "close_time": "2024-12-31T23:59:00+00:00",
        "result": null
    }
]
```

Prices are in cents (0–99). A YES price of `55` means 55¢ per contract.
Pagination is not implemented — returns the first page only.

---

### GET /market/{ticker}

Returns a single market by ticker.

Same schema as a single element in `GET /markets`.

---

### GET /orderbook/{ticker}

Returns the current order book for a market.

```json
{
    "ticker": "AAPL-24-GT150",
    "yes": [
        {"price": 55, "count": 100},
        {"price": 54, "count": 200}
    ],
    "no": [
        {"price": 43, "count": 150}
    ]
}
```

Each level is `{price: int, count: int}`. Prices in cents.

---

### GET /positions

Returns all open positions in the portfolio.

```json
[
    {
        "ticker": "AAPL-24-GT150",
        "side": "yes",
        "count": 10,
        "realized_pnl": 500,
        "unrealized_pnl": 200,
        "market_exposure": 550
    }
]
```

Kalshi's signed position integer (positive = YES, negative = NO) is
normalized to `side` + `count` (always positive). All PNL values in cents.

---

### POST /order

Places a limit order.

Request:
```json
{
    "ticker": "AAPL-24-GT150",
    "side": "yes",
    "action": "buy",
    "count": 10,
    "price": 55,
    "order_type": "limit"
}
```

- `side`: `"yes"` or `"no"`
- `action`: `"buy"` or `"sell"`
- `price`: in cents (1–99)
- `order_type`: `"limit"` (only supported type)

Response:
```json
{
    "order_id": "ord-abc123",
    "ticker": "AAPL-24-GT150",
    "side": "yes",
    "action": "buy",
    "count": 10,
    "price": 55,
    "order_type": "limit",
    "status": "resting",
    "filled_count": 0,
    "remaining_count": 10,
    "created_time": "2024-06-01T12:00:00+00:00"
}
```

---

### POST /cancel

Cancels an order by ID.

Request:
```json
{
    "order_id": "ord-abc123"
}
```

Response: the cancelled order with `"status": "canceled"`.

## Outcome Collection (SPEC-018)

The Kalshi Connector runs a background outcome polling loop that continuously compares platform predictions against reality.

### How it works

Every `OUTCOME_POLL_SECONDS` (default 300 seconds):

1. **Discover** — Query `prediction.prediction_requests` for all predictions with a `market_id` that do not yet have a row in `prediction.prediction_outcomes`.
2. **Query** — For each unresolved prediction, call `GET /market/{market_id}` on the Kalshi API to check resolution status.
3. **Skip** — If `market.result` is `null`, the market is still open. Move to the next prediction.
4. **Persist** — If `market.result` is set (e.g. `"yes"` or `"no"`), insert a row into `prediction.prediction_outcomes` with:
   - `predicted_value` — what our model predicted
   - `actual_value` — what Kalshi says the result is
   - `prediction_correct` — `True` if they match (case-insensitive), `False` otherwise
   - `market_close_time` — when the market closed
   - `collected_time` — when this outcome was recorded
   - `metadata` — question and confidence from the original prediction
5. **Trigger** — After persisting a new outcome, POST `{}` to `{LEARNING_ENGINE_URL}/analyze` (fire-and-forget). If the Learning Engine is unavailable, log the failure and continue; outcome collection never blocks on learning.

### Duplicate prevention

`ON CONFLICT (prediction_id) DO NOTHING` ensures each prediction produces at most one outcome row, even if the poller cycles while a previous insert is in-flight.

### Failure recovery

| Failure | Behaviour |
|---|---|
| Kalshi unreachable for a specific market | Log warning; skip that prediction; continue with the rest |
| PostgreSQL unavailable at startup | Outcome collection disabled for this run; service starts normally |
| Learning Engine unavailable | Log warning; outcome is still recorded; next poll proceeds |
| Unexpected exception in poll loop | Log exception; sleep; retry next cycle |

### PostgreSQL schema

The connector extends the existing `prediction.prediction_outcomes` table (first created by `prediction-api`) with outcome-specific columns:

```sql
-- Extended columns added by kalshi-connector on startup (ADD COLUMN IF NOT EXISTS)
ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS market_id TEXT;
ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS predicted_value TEXT;
ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS actual_value TEXT;
ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS prediction_correct BOOLEAN;
ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS market_close_time TIMESTAMPTZ;
ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS collected_time TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
```

---

## Error Handling

All Kalshi errors are mapped to consistent HTTP responses:

| Condition | HTTP Status | Description |
| --- | --- | --- |
| Auth failure | `401` | Invalid or expired credentials |
| Rate limited | `429` | Too many requests (retry-after respected) |
| Not found | `404` | Market or order does not exist |
| Invalid order | `400` | Bad request (insufficient funds, invalid price) |
| Server error / network | `503` | Kalshi unavailable or unreachable |

The client retries `500`/`5xx`, `429`, and connection errors with exponential
backoff. Auth errors (`401`) and not-found errors (`404`) are not retried.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `KALSHI_API_KEY` | Yes | — | API key from Kalshi Developer Portal |
| `KALSHI_PRIVATE_KEY` | Yes* | — | PEM content; escape newlines as `\n` in env var |
| `KALSHI_PRIVATE_KEY_PATH` | Yes* | — | Path to PEM file (alternative to `KALSHI_PRIVATE_KEY`) |
| `KALSHI_ENVIRONMENT` | No | `production` | `"production"` or `"demo"` |
| `HTTP_TIMEOUT` | No | `30.0` | Default request timeout in seconds |
| `MAX_RETRIES` | No | `3` | Number of retry attempts on transient failures |
| `POSTGRES_URL` | No | — | PostgreSQL connection string; outcome collection disabled if unset |
| `OUTCOME_COLLECTION_ENABLED` | No | `true` | Set to `false` to disable outcome polling |
| `OUTCOME_POLL_SECONDS` | No | `300` | Seconds between outcome polling cycles |
| `LEARNING_ENGINE_URL` | No | `http://learning-engine:8001` | Learning Engine base URL for outcome trigger |

*One of `KALSHI_PRIVATE_KEY` or `KALSHI_PRIVATE_KEY_PATH` is required.

### Environments

| `KALSHI_ENVIRONMENT` | Base URL |
| --- | --- |
| `demo` | `https://demo-api.kalshi.co/trade-api/v2` |
| `production` | `https://trading-api.kalshi.com/trade-api/v2` |

Switch environments without code changes — credentials differ between demo
and production.

### Private Key Format

The RSA private key must be in PKCS#8 PEM format. The recommended approach
for Docker/compose is to mount the key file read-only and use `KALSHI_PRIVATE_KEY_PATH`:

```yaml
# docker-compose.yml
volumes:
  - ./keys/kalshi_private.key:/app/keys/kalshi_private.key:ro
environment:
  KALSHI_PRIVATE_KEY_PATH: /app/keys/kalshi_private.key
```

```
# .env
KALSHI_PRIVATE_KEY_PATH=/app/keys/kalshi_private.key
```

`KALSHI_PRIVATE_KEY` (inline PEM with escaped newlines) is also supported but
is fragile in practice — a stale file path accidentally left in that variable
passes a truthy check and silently breaks auth. Use `KALSHI_PRIVATE_KEY_PATH`
for production deployments.

The key file should be in `compose/keys/` which is excluded from git via
`.gitignore`. Never commit the key file.

## Deployment

The service requires Kalshi credentials. The container can be built and
started independently of other platform services:

```sh
docker compose up -d kalshi-connector
```

Once started, `/health` returns `"ok"` when credentials are valid and Kalshi
is reachable, `"degraded"` otherwise.

## Service Layout

```text
services/kalshi-connector/
├── app/
│   ├── main.py            — FastAPI app, lifespan, httpx client setup
│   ├── config.py          — pydantic-settings (env vars, PEM loading)
│   ├── authentication.py  — RSA-PSS signing, auth header construction
│   ├── client.py          — KalshiClient, retry logic, error types
│   ├── markets.py         — Market, OrderBook models + normalization
│   ├── orders.py          — Order models, place/cancel functions
│   ├── positions.py       — Position, Account models + normalization
│   ├── settlements.py     — Settlement model + normalization
│   ├── routes.py          — All FastAPI route handlers
│   ├── health.py          — HealthStatus model + get_health()
│   ├── postgres.py        — Pool init, outcome table extension, persist_outcome, get_unresolved
│   └── outcomes.py        — Outcome polling loop, _determine_correctness, _trigger_learning
├── tests/
│   ├── test_authentication.py  — 10 tests: signing, header construction
│   ├── test_client.py          — 19 tests: HTTP status handling, retries
│   ├── test_markets.py         — 21 tests: normalization, async functions
│   ├── test_orders.py          — 18 tests: models, normalization, placement
│   ├── test_positions.py       — 13 tests: normalization, account
│   ├── test_settlements.py     — 9 tests: normalization, async functions
│   ├── test_routes.py          — 20 tests: all endpoints, error handling
│   └── test_outcomes.py        — 18 tests: outcome collection, learning trigger, failure recovery
├── pytest.ini          — asyncio_mode = auto
├── Dockerfile
└── requirements.txt
```

Total: 128 tests passing.

## Logging

Each request logs: method, path, HTTP status, elapsed time, attempt number.
Retries log the reason (rate limit, server error, network). Example:

```
2026-07-02 04:00:01 INFO app.client GET /markets status=200 elapsed=120ms attempt=0
2026-07-02 04:00:02 WARNING app.client Server error 503 on /portfolio/orders, retry in 1s
```

Never logged: API keys, private keys, signatures.

---

## Implementation Observations

These are observations for future phases, not changes to this implementation.

**1. Settlements endpoint not exposed.** The spec lists "Retrieve settlements"
as a responsibility but the API section does not include a `GET /settlements`
endpoint. The normalization logic and `get_settlements()` function are
implemented in `settlements.py` and work correctly; a future phase can wire
them to a route without touching the normalization code.

**2. No market pagination.** Kalshi's `/markets` endpoint returns a cursor for
pagination. This implementation returns only the first page. A future phase
should either thread the cursor through the platform response or iterate
internally and return all pages up to a configurable limit.

**3. Only limit orders.** The spec and implementation support `order_type=limit`
only. Kalshi also supports market orders (`type=market`), which do not require
a price. A future phase can extend `PlaceOrderRequest` with an optional price
and handle the market order path in `place_order()`.

**4. Retry backoff is not jittered.** The current backoff is `2^attempt`
seconds (1s, 2s, 4s). Under high concurrency, multiple clients could retry
simultaneously. A future phase should add ±50% jitter: `2^attempt * random(0.5, 1.5)`.

**5. Private key is loaded once at startup.** If the key is rotated (e.g.,
a new PEM is written to `KALSHI_PRIVATE_KEY_PATH`), the service must be
restarted. A future phase could reload on a SIGHUP or implement a hot-reload
endpoint.

**6. No position filtering.** `GET /positions` returns all open positions.
A future phase should support filtering by ticker or side for use in targeted
queries.

**7. Account endpoint is cash-only.** `GET /account` maps to Kalshi's
`/portfolio/balance` which returns available cash. `portfolio_value` is
populated only if Kalshi returns it from that endpoint. A future phase could
compute portfolio value from positions or use a dedicated portfolio endpoint
if Kalshi adds one.

**9. `prediction.prediction_outcomes` table schema conflict.** The `prediction-api` service creates `prediction.prediction_outcomes` with a minimal 3-column schema (prediction_id, outcome, resolved_at) and a FK to `prediction_requests`. The Kalshi Connector extends this table using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on startup, which is safe regardless of which service starts first. When kalshi-connector starts first, it creates the table without the FK; when prediction-api starts first, the FK is preserved. Either way, the INSERT always provides both legacy columns and the new extended columns, so both schemas are compatible.

**8. `kalshi_reachable: true` does not mean authentication succeeded.** The
`/health` endpoint probes reachability by making an unauthenticated GET to the
base URL. Kalshi returns `401` for unauthenticated requests; the connector
treats any HTTP response (including 401) as "reachable" because the server is
up. A `401` on authenticated endpoints (`/account`, `/positions`) indicates a
credential mismatch — the API key and private key must be from the same Kalshi
key pair. Verify on the Kalshi developer portal that the API key ID matches the
key pair used to generate the PEM file.
