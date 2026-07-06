# Risk Manager

The platform's trade evaluation and position sizing service. Ninth service
(SPEC-013), after [Kalshi Connector](KALSHI_CONNECTOR.md).

## Purpose

The Risk Manager receives completed predictions and determines whether a
proposed trade should be executed. It enforces configurable risk rules,
calculates position sizing, and persists every decision to PostgreSQL for
audit and future analysis.

**What it does:**
- Evaluates 7 independent risk rules against each prediction
- Calculates position size (contracts and maximum price) when rules pass
- Persists every decision (approved or denied) to `risk.trade_decisions`
- Fetches live account state from Kalshi Connector for balance and open positions
- Returns structured approval or denial responses with per-rule check results

**What it does not do:**
- Execute trades
- Communicate with Kalshi directly (delegates to Kalshi Connector)
- Perform AI reasoning or prediction generation
- Access Ollama
- Analyze historical performance
- Make decisions based on market structure

Trade strategy belongs upstream. This service only decides whether a
proposed trade is safe to execute under the current platform rules.

## Risk Rules

All 7 rules are evaluated independently. A single failure is enough to
deny the trade. All rule thresholds are configurable via environment
variables.

| Rule | Env Var | Default | Passes when |
| --- | --- | --- | --- |
| Confidence | `MIN_CONFIDENCE` | `0.60` | `confidence >= min_confidence` |
| Expected Value | `MIN_EXPECTED_VALUE` | `0.01` | `expected_value >= min_expected_value` |
| Edge | `MIN_EDGE` | `0.05` | `edge >= min_edge` |
| Open Positions | `MAX_OPEN_POSITIONS` | `10` | `open_count < max_open_positions` |
| Daily Loss | `MAX_DAILY_LOSS` | `10000` | `today_exposure + new_trade_cost <= max_daily_loss` |
| Bankroll | `MAX_POSITION_PERCENT` | `5.0` | `contracts * price <= balance * percent / 100` |
| Consecutive Losses | `MAX_CONSECUTIVE_LOSSES` | `5` | Consecutive denied evaluations < limit |

`MAX_DAILY_LOSS` is in cents (10000 = $100.00). The daily exposure is the
sum of `recommended_contracts * recommended_max_price` for all approved
decisions made today — a spending cap, not realized P&L (the service does
not execute trades and cannot observe actual outcomes).

Consecutive losses are consecutive `approved=false` entries in recent
decisions (newest first). This acts as a safety valve when predictions are
consistently failing evaluation.

## Position Sizing

Position sizing runs even when rules are being evaluated (pure function,
no I/O). The results are included in the response only if all rules pass
(and `DRY_RUN=false`); otherwise sizing is `null`.

**Max price:**
```
max_price = clamp(probability * 100 - (edge * 100 * 0.5), 1, 99)
```

A conservative bid that gives up half the edge as a safety buffer.
Result is rounded to the nearest cent and clamped to [1, 99].

**Contracts:**
```
allowed_exposure = balance * max_position_percent / 100
contracts = floor(allowed_exposure / max_price)
contracts = min(contracts, 100)
```

Capped at 100 contracts. Returns 0 if balance is zero or non-positive.

## Dry-Run Mode

`DRY_RUN=true` is the default. In dry-run mode:

- All 7 risk rules are still evaluated normally
- Position sizing is still calculated when rules pass
- The response always has `approved=false`
- The denial reason is `"Dry-run mode: trade not submitted."`
- Sizing fields are populated when all checks pass (so the caller can see what would have been approved)

Set `DRY_RUN=false` in `.env` only when real trading is intended.

## API

### GET /health

Returns service status and dependency health.

```json
{
    "status": "ok",
    "postgres": true,
    "kalshi_connector": true,
    "dry_run": true,
    "version": "0.1.0"
}
```

`status` is `"ok"` when PostgreSQL is reachable, `"degraded"` when it is
not. Kalshi Connector health is reported separately. `"starting"` is
returned if the service has not yet initialized.

---

### POST /evaluate

Evaluates a prediction proposal against all configured risk rules.

**Request:**
```json
{
    "prediction_id": "pred_20260705T120000_abc12345",
    "probability": 0.65,
    "confidence": 0.75,
    "expected_value": 0.08,
    "edge": 0.10,
    "market_ticker": "AAPL-24-GT150",
    "market_category": "finance"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `prediction_id` | string | ID of the originating prediction |
| `probability` | float [0, 1] | Predicted probability of the YES outcome |
| `confidence` | float [0, 1] | Model confidence in the prediction |
| `expected_value` | float | Estimated expected value of the trade |
| `edge` | float | Estimated edge over the market price |
| `market_ticker` | string | Kalshi market ticker |
| `market_category` | string | Market category (default: `"finance"`) |

**Response (approved):**
```json
{
    "prediction_id": "pred_20260705T120000_abc12345",
    "approved": true,
    "reason": "All configured risk criteria satisfied.",
    "recommended_contracts": 90,
    "recommended_max_price": 60,
    "risk_checks": {
        "confidence": true,
        "expected_value": true,
        "edge": true,
        "open_positions": true,
        "daily_loss": true,
        "bankroll": true,
        "consecutive_losses": true
    }
}
```

**Response (denied):**
```json
{
    "prediction_id": "pred_20260705T120000_abc12345",
    "approved": false,
    "reason": "Confidence 0.42 below minimum 0.60; Edge 0.02 below minimum 0.05.",
    "recommended_contracts": null,
    "recommended_max_price": null,
    "risk_checks": {
        "confidence": false,
        "expected_value": true,
        "edge": false,
        "open_positions": true,
        "daily_loss": true,
        "bankroll": true,
        "consecutive_losses": true
    }
}
```

When denied, `reason` lists all failing rules separated by semicolons.
When in dry-run mode and all checks pass, sizing is populated but
`approved=false`.

## PostgreSQL Schema

```sql
CREATE SCHEMA IF NOT EXISTS risk;

CREATE TABLE IF NOT EXISTS risk.trade_decisions (
    decision_id         TEXT PRIMARY KEY,
    prediction_id       TEXT NOT NULL,
    approved            BOOLEAN NOT NULL,
    reason              TEXT NOT NULL,
    recommended_contracts INTEGER,
    recommended_max_price INTEGER,
    evaluation_duration_ms INTEGER,
    risk_checks         JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

The schema is created at startup (`CREATE SCHEMA IF NOT EXISTS`) so no
manual migration step is required.

`decision_id` format: `decision_YYYYMMDDTHHMMSS_xxxxxxxx` where the suffix
is 8 hex characters of a UUID4.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `DRY_RUN` | No | `true` | Set to `false` to enable real approvals |
| `MIN_CONFIDENCE` | No | `0.60` | Minimum confidence to approve |
| `MIN_EXPECTED_VALUE` | No | `0.01` | Minimum expected value to approve |
| `MIN_EDGE` | No | `0.05` | Minimum edge to approve |
| `MAX_POSITION_PERCENT` | No | `5.0` | Max % of balance per trade |
| `MAX_OPEN_POSITIONS` | No | `10` | Max simultaneous open positions |
| `MAX_DAILY_LOSS` | No | `10000` | Max daily trade exposure in cents |
| `MAX_CONSECUTIVE_LOSSES` | No | `5` | Max consecutive denied evaluations |
| `KALSHI_CONNECTOR_URL` | No | `http://kalshi-connector:8003` | URL of Kalshi Connector |
| `POSTGRES_URL` | No | `""` | PostgreSQL connection URL |
| `HTTP_TIMEOUT` | No | `30.0` | HTTP client timeout in seconds |

PostgreSQL is optional at startup. If `POSTGRES_URL` is empty or the
connection fails, decisions are still evaluated and returned; they are
not persisted. Daily loss and consecutive loss checks default to 0
and empty list respectively.

## Deployment

```sh
docker compose up -d risk-manager
```

Requires `postgres` and `kalshi-connector` to be healthy (enforced by
`depends_on` in docker-compose.yml). Once started, `/health` reports
both dependency statuses and dry-run mode.

## Service Layout

```text
services/risk-manager/
├── app/
│   ├── main.py           — FastAPI app, lifespan, httpx + asyncpg setup
│   ├── config.py         — pydantic-settings (env vars, risk thresholds)
│   ├── models.py         — EvaluationRequest, EvaluationResponse, RiskChecks
│   ├── evaluator.py      — Pure function run_evaluation(), 7 rule functions
│   ├── position_sizing.py — calculate_max_price(), calculate_contracts()
│   ├── kalshi_client.py  — KalshiConnectorClient (get_account, get_positions)
│   ├── postgres.py       — Pool init, persist_decision, exposure/decisions queries
│   ├── health.py         — HealthStatus model + get_health()
│   └── routes.py         — GET /health, POST /evaluate; set_dependencies()
├── tests/
│   ├── test_evaluator.py        — 57 tests: all 7 rules, run_evaluation, dry_run
│   ├── test_position_sizing.py  — 16 tests: max_price, contracts, clamping
│   ├── test_kalshi_client.py    — 9 tests: account, positions, reachability
│   ├── test_postgres.py         — 11 tests: persist, exposure, decisions, health
│   └── test_routes.py           — 12 tests: /health, /evaluate, validation
├── pytest.ini          — asyncio_mode = auto
├── Dockerfile
└── requirements.txt
```

Total: 105 tests passing.

## Logging

Each evaluation logs: prediction_id, approved, reason, elapsed time.

```
2026-07-05 12:00:01 INFO app.routes prediction_id=pred_001 approved=True reason=All configured risk criteria satisfied. elapsed=45ms
```

Never logged: Kalshi API keys, PostgreSQL passwords.

---

## Implementation Observations

**1. Daily loss is a spending cap, not realized P&L.** The service does not
execute trades and cannot observe outcomes. `MAX_DAILY_LOSS` limits the sum
of `recommended_contracts * recommended_max_price` for approved decisions
today. This is a forward-looking spending cap — not a P&L guardrail.

**2. Consecutive losses tracks denied evaluations.** Because the service
does not observe trade outcomes, "consecutive losses" is implemented as
consecutive `approved=false` decisions (newest first). This signals that
predictions are consistently failing evaluation, which may indicate a
model or configuration problem requiring attention.

**3. Bankroll check delegates to position sizing.** When Kalshi Connector
is unreachable, `get_account()` returns `balance=0`. Zero balance causes
`calculate_contracts()` to return 0, which fails the bankroll check
(`contracts <= 0`). The result is a natural denial without special-casing
Kalshi unavailability.

**4. PostgreSQL is optional.** The service starts and evaluates normally
without a database. Daily loss and consecutive loss checks default to
safe values (0 and [] respectively). Decisions are not persisted when the
pool is None.
