# IB Trade History Skill Design

## Goal

Add a read-only `ib-trade-history` skill under `skills/ib-suite/` that reads
Interactive Brokers Flex Query trade records for a requested period and returns
every execution plus a base-currency trading summary.

## Scope

The skill exposes `/ib-trade-history`. It accepts explicit
`--start-date YYYY-MM-DD` and `--end-date YYYY-MM-DD` arguments. When a user
does not state a period, the skill uses the inclusive seven-calendar-day window
ending today. The SKILL.md instructions resolve natural-language periods such
as "this month" to explicit ISO dates before running the script.

The Flex Query configured in IBKR must cover the requested period. The script
filters the downloaded report locally using inclusive date bounds.

The feature does not persist Flex XML or trade history. It does not connect to
IB Gateway and never imports or calls an order API.

## Architecture

Create `skills/ib-suite/ib-trade-history/` with:

- `SKILL.md`: registers `/ib-trade-history`, documents the Flex prerequisites,
  commands, read-only boundary, and natural-language period handling.
- `scripts/trade_history.py`: validates dates, fetches the Flex statement,
  parses trades, filters the requested period, calculates the response, and
  prints one JSON object to stdout.
- `tests/`: imports the script without network access and tests the executable
  behavior using fixtures.

Extend `ib_common.schema` with Pydantic response models for a trade record,
summary, and whole query result. Extend
`ib-gateway/scripts/flex_fetch.py` with a deterministic Flex `Trade` parser
that supplies the shared fields needed by this skill.

## Data Contract

Each trade row represents one Flex execution. It includes:

- execution timestamp;
- symbol or contract identifier;
- BUY or SELL side;
- quantity, execution price, original-currency notional, and commission;
- currency, order type, exchange, and open/close indicator;
- original-currency and base-currency realized P&L;
- Flex `fxRateToBase` used for conversion.

The parser reads IBKR's `FIFO P/L` field and never locally reconstructs lot
matching. This preserves IBKR's accounting treatment for partial closes,
options, corporate actions, and account-specific lot rules.

The implementation requires a usable execution timestamp, FIFO realized P&L,
and FX rate when conversion is needed. A missing required field causes an
actionable error rather than a fabricated value.

## Summary Semantics

All summary monetary amounts use the account base currency from `config.yaml`.
Each row retains its original currency and unconverted amounts.

- `total_trades`, `buy_count`, and `sell_count` count execution rows.
- `total_notional` is the sum of absolute execution notionals converted with
  each row's Flex FX rate.
- `total_commission` is the sum of converted absolute commissions.
- A profitable trade has realized P&L greater than zero; a losing trade has
  realized P&L less than zero. Zero-P&L rows are excluded from win rate.
- `win_rate` is profitable count divided by profitable plus losing count.
- `average_profit` and `average_loss` calculate their respective non-zero
  samples in base currency.
- `profit_loss_ratio` is average profit divided by the absolute average loss.
  It is null when one side has no observations.

An empty range returns an empty trade array and zero counts. Invalid date
syntax, an inverted date range, Flex request failures, or missing required
data produce a non-zero exit with a fix direction.

## Security and Runtime Constraints

`FLEX_TOKEN` and `FLEX_QUERY_ID` are required environment variables. They are
never written to disk or stdout. The SKILL.md metadata declares the required
Python binary, workspace config, supported operating systems, and Flex
environment variables. The runtime is read-only and makes only the Flex Web
Service request.

## Test Strategy

Tests use a desensitized Flex XML fixture and an injected HTTP getter. They
cover:

- full field parsing and inclusive date filtering;
- default seven-day range and date validation;
- base-currency conversion of notional, commission, and realized P&L;
- multiple fills for one order remaining distinct rows;
- profitable, losing, zero-P&L, one-sided, and empty summaries;
- Flex handshake failures and missing required data;
- SKILL.md metadata, command paths, trigger examples, and read-only boundary.

No new dependency is required.
