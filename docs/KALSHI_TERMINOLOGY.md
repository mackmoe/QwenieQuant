# Kalshi Platform — Terminology Reference

Quick reference for Kalshi market structure, pricing, orders, positions, and
settlement terminology. Terms are drawn from the Kalshi Trade API v2 and
mirrored by our `kalshi-connector` service
(`services/kalshi-connector/app/`).

---

## Object Hierarchy

Kalshi's discovery hierarchy, which this platform mirrors end to end:

```text
Category          Sports
  └─ Series       MLB Player Hits          (series_ticker, belongs to ONE category)
       └─ Event   Moreno to record 1+ hit? (event_ticker, carries category + series_ticker)
            └─ Market   YES/NO contract    (ticker, carries event_ticker)
```

- **Category** — high-level discovery grouping (per Kalshi's glossary). A series
  belongs to exactly one category. Full set verified against live /events data
  (July 2026): Sports, Elections, Entertainment, Politics, Economics, Financials,
  Climate and Weather, Science and Technology, Crypto, Companies, Commodities,
  Mentions, Social, World, Health, Transportation (+ "Exotics" seen on MVE
  markets). The API strings differ from the website navigation ("Science and
  Technology" vs the site's "science" URL; "Entertainment" vs "Culture";
  "Climate and Weather" vs "Climate"), and Kalshi adds categories without
  notice — so the platform stores category as an open string, never a closed
  enum, and scans ALL categories with no filter.
- **Subcategory** — narrower discovery grouping; a series can belong to several.
- The platform resolves a market's category via its event: the Opportunity Engine
  fetches open events (`GET /events`), joins on `event_ticker`, and carries
  `category`, `series_ticker`, and `event_ticker` in queue metadata.

## Market Structure

| Term | Definition |
| ------ | ------------ |
| **Series** | A group of related markets (e.g., `KXMLB` = all MLB markets). Identified by a `series_ticker`. Belongs to one category. |
| **Event** | A specific occurrence within a series (e.g., "Cubs vs. Cardinals, July 8"). Identified by `event_ticker`; carries `category` and `series_ticker`. |
| **Market** | One binary YES/NO contract within an event. Identified by a unique `ticker` (e.g., `KXMLB-23-MILWIN`); carries `event_ticker`. |
| **Ticker** | The unique identifier for a market. Ticker prefixes identify the series (`KXMLB`, `KXNBA`, `KXNFL`, `KXNHL`, etc.). |
| **Status** | A market's lifecycle stage: `open` → `closed` → `settled` → `finalized`. (The older API used `active` instead of `open`; our connector accepts both.) |
| **Multi-outcome market** | A market whose title aggregates several sub-outcomes as a comma-separated string (e.g., `"yes Milwaukee,yes Baltimore,yes Detroit"`). Our workflow skips these (`status: "skipped", reason: "multi_outcome"`). |

## Pricing

| Term | Definition |
| ------ | ------------ |
| **Price** | Platform-internal prices are in **cents**, range 1–99. A price of `55` = 55¢ = $0.55 per contract. |
| **Dollar-string fields** | The current API (`api.elections.kalshi.com`) returns prices as dollar strings (`yes_bid_dollars: "0.6100"`) and counts as `_fp` strings (`volume_fp: "11627.90"`); the legacy integer-cent fields are gone. The connector converts both formats to cents/ints at the boundary. Fractional trading means sub-cent prices exist (`"0.0020"` = 0.2¢). |
| **yes_bid / yes_ask** | Best current buy/sell prices for the YES side. |
| **no_bid / no_ask** | Best current buy/sell prices for the NO side. Relationship: `no_price = 100 − yes_price`. |
| **Spread** | Gap between bid and ask. Wider spread = less liquid market. |
| **Mid price** | `(yes_bid + yes_ask) / 2` — what our workflow uses as the market's implied probability. |
| **Order book** | The list of resting orders at each price level, per side (`yes` / `no` arrays of `[price, count]`). |

## Orders

| Term | Definition |
| ------ | ------------ |
| **Order** | A request to buy or sell contracts. Key fields: `side` (yes/no), `action` (buy/sell), `count` (quantity), `yes_price` or `no_price`, `type` (limit/market). |
| **Limit order** | An order that executes only at the specified price or better. Our platform places limit orders exclusively. |
| **Market order** | An order that executes immediately at the best available price. |
| **Resting order** | A limit order that hasn't filled yet; it sits in the order book waiting for a counterparty. |
| **Fill** | A confirmed execution of part or all of an order. |
| **filled_count / remaining_count** | Contracts executed vs. still waiting in the book. |
| **Order status** | `resting`, `filled`, `canceled`, `pending`. |
| **Cancel** | Removing a resting order from the book (`DELETE /portfolio/orders/{order_id}`). |

## Positions & Portfolio

| Term | Definition |
| ------ | ------------ |
| **Position** | Contracts you hold in a market. In the raw API, a positive `position` count = YES contracts, negative = NO contracts. |
| **Balance** | Available cash, in cents (`GET /portfolio/balance`). |
| **Portfolio value** | Estimated value of all open positions, in cents. |
| **Realized PnL** | Profit/loss from closed (settled or sold) positions, in cents. |
| **Unrealized PnL** | Profit/loss on still-open positions at current market prices, in cents. |
| **Market exposure** | Dollar amount at risk on an open position, in cents. |
| **Open interest** | Total contracts currently held across all traders in a market. |
| **Volume** | Total contracts ever traded in a market. |

## Settlement

| Term | Definition |
| ------ | ------------ |
| **Settlement** | When a market closes and resolves to YES (`result: "yes"`) or NO (`result: "no"`). |
| **Payout** | YES holders receive $1.00 (100¢) per contract if the market settles YES; NO holders receive $1.00 per contract if it settles NO. Losing side receives $0. |
| **close_time** | The timestamp when trading stops and the market awaits resolution. |
| **Expiration** | Same concept as close; our queue tracks `days_remaining` until close. |

## Naming Convention

Platform code uses Kalshi's field names wherever a concept maps to Kalshi's
API: `count` (not quantity), `side`, `action`, `ticker`, `yes_bid`/`yes_ask`,
`close_time`, `result`, `filled_count`/`remaining_count`. New code should
follow this rule.

**Deliberate divergences** — these differ from Kalshi's names because they are
live database columns or established internal concepts; renaming would require
migrations on tables with historical data:

| Our name | Kalshi name | Where it lives | Why it stays |
| ---------- | ------------- | ---------------- | -------------- |
| `market_id` | `ticker` | queue + workflow_results DB tables, all services | Same value as ticker; column exists in historical data |
| `expiration_time` | `close_time` | `queue.prediction_queue` DB column | DB column with history; connector itself uses `close_time` |
| `outcome` | `result` | `learning.outcomes` schema, Learning/Reflection Engines | Core learning-loop concept across three services |
| `order_type` | `type` | connector request model | `type` shadows a Python builtin; translated at the API boundary |
| `/account` | `/portfolio/balance` | connector route | Descriptive internal route; proxies Kalshi's portfolio balance |
| `price` (single field) | `yes_price` / `no_price` | connector order request | Simplification: `side` + `price`; translated to the right field at the boundary |

## How Our Platform Maps to Kalshi

| Our concept | Kalshi equivalent |
| ------------- | ------------------- |
| Opportunity Engine `priority_score` | Internal ranking — not a Kalshi concept |
| `market_id` / `ticker` in queue | Kalshi market `ticker` |
| `metadata.title` | Kalshi market `title` |
| `metadata.spread` | `yes_ask − yes_bid` |
| Workflow `probability` | Model's P(YES); compared to mid price for edge/EV |
| Risk Manager `edge` | `P(model) − P(market)` from the traded side's perspective |
| Trade execution | `POST /portfolio/orders` (limit order via kalshi-connector) |

## Key API Endpoints (via kalshi-connector)

| Endpoint | Purpose |
| ---------- | --------- |
| `GET /markets` | List markets (filter by `status`, `series_ticker`, `limit`) |
| `GET /events` | List events with `category` and `series_ticker` (cursor-paginated) |
| `GET /events/{event_ticker}` | Single event detail |
| `GET /markets/{ticker}` | Single market detail |
| `GET /markets/{ticker}/orderbook` | Order book for a market |
| `GET /portfolio/balance` | Cash balance + portfolio value |
| `GET /portfolio/positions` | Open positions (`market_positions`) |
| `POST /portfolio/orders` | Place an order |
| `DELETE /portfolio/orders/{order_id}` | Cancel a resting order |
