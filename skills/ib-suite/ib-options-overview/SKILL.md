---
name: ib-options-overview
description: Read-only Interactive Brokers option positions and Greeks overview. Use when the user asks for open option contracts, IV, Delta, Gamma, Theta, Vega, moneyness, expiry exposure, or option concentration. Reads live positions and market data only - never places, modifies, or cancels an order.
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [config.yaml]
    os: [darwin, linux]
---

# ib-options-overview

Read every open option position and return one JSON risk overview. This connects
with `readonly=True`, subscribes only long enough to collect model Greeks, and
briefly requests one deduplicated underlying quote when option model data lacks
an underlying price. It cancels both option and underlying subscriptions
afterward. It never places, modifies, or cancels orders.

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/options_overview.py --config .ib-suite/config.yaml
```

The JSON lists each contract's underlying, Call/Put, long/short side, strike,
expiry, inclusive calendar DTE, quantity, cost, price, market value, unrealized
P&L, IV, Delta, Gamma, Theta, Vega, and ITM/ATM/OTM state. `summary` includes
aggregate Greeks, daily time-value decay, expiry distribution, and absolute
market-value underlying concentration.

Present the result in the user's language. Start with a compact Markdown table
and group positions by `moneyness` in this order: ITM, ATM, OTM, and UNKNOWN.
For a classified position with an underlying price, show the underlying price
and the in/out-of-the-money distance as the absolute difference between `underlying_price` and `strike`.
You may combine strikes only when symbol, right, expiry, and moneyness are
identical. Put positions with null moneyness in UNKNOWN and explain their
matching `data_limitations` below the table.

Delayed data is accepted. Unavailable price, underlying price, IV, or Greek
fields remain `null` and are explained in `data_limitations`; no unavailable
market data is fabricated as zero.
