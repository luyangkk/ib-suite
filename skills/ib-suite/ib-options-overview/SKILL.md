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
with `readonly=True`, subscribes only long enough to collect model Greeks, then
cancels every market-data subscription. It never places, modifies, or cancels
orders.

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/options_overview.py --config .ib-suite/config.yaml
```

The JSON lists each contract's underlying, Call/Put, long/short side, strike,
expiry, inclusive calendar DTE, quantity, cost, price, market value, unrealized
P&L, IV, Delta, Gamma, Theta, Vega, and ITM/ATM/OTM state. `summary` includes
aggregate Greeks, daily time-value decay, expiry distribution, and absolute
market-value underlying concentration.

Delayed data is accepted. Unavailable price, underlying price, IV, or Greek
fields remain `null` and are explained in `data_limitations`; no unavailable
market data is fabricated as zero.
