---
name: ib-trade-history
description: Read-only Interactive Brokers trade history from Flex Query. Use when the user asks to list executions or fills for a date range, inspect buy and sell activity, commissions, order type, exchange, open/close status, realized FIFO P&L, win rate, average win/loss, or profit/loss ratio. Reads Flex records only - never places, modifies, or cancels an order.
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [config.yaml]
    os: [darwin, linux]
---

# ib-trade-history

Read only the requested IBKR Flex Query trade history. Do not place, modify, or
cancel orders; do not start IB Gateway; do not write trade data to the lake.

## Prerequisites

Configure the Flex Query `Trades` section to include `dateTime`, `tradeID`,
`symbol`, `buySell`, `quantity`, `tradePrice`, `ibCommission`, `currency`,
`ibCommissionCurrency`, `multiplier`, `orderType`, `exchange`,
`openCloseIndicator`, `fifoPnlRealized`, and `fxRateToBase`. Its configured
history window must cover the requested dates.

Set `data.base_currency` in `.ib-suite/config.yaml`. Before running
`/ib-trade-history`, check the local `flex.token` and `flex.query_id` fields
without exposing either value. When both fields are present, use the stored pair.
When neither field is present, ask the user for both the Flex token and Query ID,
then run:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
  --config .ib-suite/config.yaml --token '<provided-token>' --query-id '<provided-query-id>'
```

When exactly one field is present, ask for both values again and explicitly
replace the incomplete pair:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
  --config .ib-suite/config.yaml --token '<provided-token>' --query-id '<provided-query-id>' \
  --force
```

This setup persists plaintext credentials only in the ignored local config,
validates only local persistence, does not validate against the Flex Web Service,
and never echoes values. The runtime accepts only one complete credential pair:
local config takes precedence; otherwise it falls back to both `FLEX_TOKEN` and
`FLEX_QUERY_ID` environment variables. Never mix credential sources.

## Command

For a date range, resolve the user's dates to inclusive `YYYY-MM-DD` values and run:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/trade_history.py \
  --config .ib-suite/config.yaml \
  --start-date 2026-07-01 \
  --end-date 2026-07-17
```

With no stated time range, omit both date arguments to query the latest seven
calendar days:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/trade_history.py \
  --config .ib-suite/config.yaml
```

Interpret "this month" as the first day of the current month through today;
interpret "last month" as the previous calendar month; ask one clarifying
question for ambiguous phrases such as "recently".

The script prints one JSON object with `trades` and `summary`. Each fill keeps
its original currency; notional includes the Flex contract multiplier. `FIFO
P/L` is IBKR's realized P&L; do not recompute lots. An empty open/close
indicator is valid for CASH or IDEALFX fills. Commission conversion uses the
asset FX rate only when its currency matches the asset currency, or uses 1.0
when the commission is already in the account base currency. A third currency
commission has no independent Flex rate in this report, so the script rejects
it instead of inventing a base-currency total. Zero-P&L fills are excluded from
win rate. `profit_loss_ratio` is null when there are no winning or no losing
realized-P&L fills.
