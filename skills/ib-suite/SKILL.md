---
name: ib-suite
description: >-
  Read-only Interactive Brokers toolchain for account, position, daily P&L,
  trade, dividend, options, and offline portfolio analysis. Use when the user
  asks to inspect or analyze IBKR data without placing, modifying, or cancelling orders.
license: MIT
compatibility: >-
  Requires Python 3.11 or newer on macOS or Linux. Live account views require
  a locally running IB Gateway or TWS; historical trade and dividend reports
  require Interactive Brokers Flex Web Service credentials.
---

# IB Suite

IB Suite is a read-only Skill. It can inspect account data and produce reports;
it must never place, modify, or cancel an order. Treat `SKILL_ROOT` as the
absolute directory that contains this file, and `WORKSPACE_ROOT` as the user's
existing writable project directory. Do not write credentials, environments,
data, or reports below `SKILL_ROOT`.

## First use

Bootstrap the workspace-owned environment before running a capability:

```bash
bash "$SKILL_ROOT/scripts/setup_venv.sh" --workspace-root "$WORKSPACE_ROOT"
"$WORKSPACE_ROOT/.ib-suite/venv/bin/python" "$SKILL_ROOT/scripts/init_config.py" \
  --mode paper --out "$WORKSPACE_ROOT/.ib-suite/config.yaml"
```

Use `--mode live` only when the user explicitly chooses the live Gateway port.
The config, data, reports, and versioned virtual environments belong under
`$WORKSPACE_ROOT/.ib-suite/`. Existing configuration is never overwritten unless
the user explicitly requests `--force`.

## Route requests to the focused reference

| User need | Read this reference |
|---|---|
| Synchronize a Gateway snapshot or fetch source data | [Gateway](references/ib-gateway.md) |
| Inspect equity, cash, margin, buying power, or account P&L | [Account overview](references/ib-account-overview.md) |
| List and rank open positions | [Positions overview](references/ib-positions-overview.md) |
| Explain today's realized and unrealized P&L | [Daily P&L](references/ib-daily-pnl.md) |
| Inspect Flex executions, commissions, or trade performance | [Trade history](references/ib-trade-history.md) |
| Inspect paid or expected dividends | [Dividend income](references/ib-dividend-income.md) |
| Inspect option positions, Greeks, IV, expiry, or concentration | [Options overview](references/ib-options-overview.md) |
| Analyze local fixtures or the portfolio data lake offline | [Portfolio analyst](references/ib-portfolio-analyst.md) |

Read Flex setup only when the user needs to configure credentials:
[trade-history setup](references/ib-trade-history-flex-query-setup.md) and
[dividend setup](references/ib-dividend-income-flex-query-setup.md).

## Shared rules

- Resolve every command argument to an absolute path before execution.
- `storage.root: data` resolves relative to the config file. Legacy
  `.ib-suite/data` in a config stored at `.ib-suite/config.yaml` still resolves
  to the same data directory.
- Missing Gateway, Flex credentials, or data files must produce an actionable
  preflight error. Do not silently connect to a network service.
- Keep tokens, Query IDs, account numbers, and user paths out of output, logs,
  fixtures, and version control.
- Each reference provides its own input, output, and read-only constraints.
