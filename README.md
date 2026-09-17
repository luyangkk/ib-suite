# ib-suite — Read-only Interactive Brokers diagnostics for AI agents

**English** | [简体中文](README.zh-CN.md)

[![CI](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml)
[![Agent Skill](https://img.shields.io/badge/format-Agent%20Skill-6f42c1)](#installation)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org/)
[![Read-only](https://img.shields.io/badge/IB%20access-read--only-2ea44f)](#safety--read-only-boundary)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

A portable **Agent Skill** for reading **Interactive Brokers (IBKR)** account
data and producing structured portfolio diagnostics: account health, positions,
daily P&L, trade history, dividend income, options Greeks, and a graded P0–P3
findings report. **It never places, modifies, or cancels an order.**

The repository publishes one installable skill, `ib-suite`. It is not tied to a
specific agent: any runtime that supports the [Agent Skills
format](https://agentskills.io/specification) can load its `SKILL.md`; the
scripts also work directly from an agent, automation, or shell. Operational
instructions for the individual capabilities are bundled as focused reference
documents, rather than separate installable skills.

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Safety & Read-only boundary](#safety--read-only-boundary)
- [Development & Testing](#development--testing)
- [Project Structure](#project-structure)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

---

## Features

`ib-suite` is the single entry skill. It routes a request to the appropriate
reference document and script; no capability below is installed separately.

| Capability | What it does | Network |
|---|---|---|
| `ib-suite` | Entry skill, first-run setup, and capability routing. | No |
| Gateway sync | Read-only ingestion into the workspace-local data lake: snapshot JSON and positions Parquet. | IB Gateway / Flex |
| Account overview | Live account snapshot: equity, cash, buying power, margin, liquidity, P&L, and currency breakdown. | IB Gateway |
| Positions overview | Live enriched positions, ranked four ways, with the most concentrated name flagged. | IB Gateway |
| Daily P&L | Today's realized and unrealized P&L, ranked winners and losers, by asset class and currency. | IB Gateway |
| Trade history | Flex execution history, commissions, realized FIFO P&L, and win/loss statistics. | Flex Web Service |
| Dividend income | Flex-only paid and expected dividends, tax, attribution, annual estimate, and yield. | Flex Web Service |
| Options overview | Live option positions, IV, Greeks, expiry exposure, and concentration. | IB Gateway |
| Portfolio analyst | Offline diagnostics that turn local data into a P0–P3 `report.md` and charts. | No |

The live overviews and Flex reporters print one parseable JSON object to stdout
and do not persist their result. Gateway sync writes the local data lake; the
portfolio analyst is offline once its input files have been supplied.

---

## Prerequisites

- **Python 3.11 or newer** on `PATH`.
- An agent runtime that supports `SKILL.md`, or a shell/automation that can run
  the included Python scripts directly.
- **IB Gateway** (or TWS) running locally with the **Read-Only API** enabled —
  paper commonly uses port `4002`, live commonly uses `4001`. It is needed for
  Gateway sync and live account, position, daily-P&L, and options views.
- A **Flex Web Service token and Query IDs** for trade history and dividend
  income. See [Configuration](#configuration).
- macOS or Linux.

---

## Installation

### Install with Skills CLI

The normal installation path is the Skills CLI. It discovers the one published
skill and lets you select the target agent supported by your local CLI.

```bash
npx skills add luyangkk/ib-suite --skill ib-suite
```

If the target runtime needs an explicit destination, choose its documented
copy or link mode in the CLI. Once installed, point the agent at the installed
`ib-suite/SKILL.md`. There are no nested skills to register.

Maintainers validate installation with `skills@1.5.26`; that pin is a
reproducibility detail for CI and is not a requirement imposed on users:

```bash
npx --yes skills@1.5.26 add luyangkk/ib-suite --list
```

The command should list only `ib-suite`, including with `--full-depth`.

### Clone for manual integration or development

If your runtime does not use the Skills CLI, clone the repository and point it
at `skills/ib-suite/SKILL.md`:

```bash
git clone https://github.com/luyangkk/ib-suite.git
cd ib-suite
```

The skill directory is read-only after installation. Choose an existing,
writable workspace outside that directory for configuration, environments,
data, and reports.

### Bootstrap the workspace environment

Set absolute paths, then run the idempotent bootstrap once:

```bash
export SKILL_ROOT="$(pwd)/skills/ib-suite"
export WORKSPACE_ROOT="$HOME/ib-suite-workspace"  # create or choose a writable workspace
mkdir -p "$WORKSPACE_ROOT"

bash "$SKILL_ROOT/scripts/setup_venv.sh" --workspace-root "$WORKSPACE_ROOT"
```

The bootstrap selects Python 3.11+, creates a versioned virtual environment,
and exposes it at `$WORKSPACE_ROOT/.ib-suite/venv`. It never writes runtime
state below `$SKILL_ROOT`.

For a verified offline installation, provide a matching wheelhouse:

```bash
bash "$SKILL_ROOT/scripts/setup_venv.sh" \
  --workspace-root "$WORKSPACE_ROOT" --offline --wheelhouse "$WHEELHOUSE"
```

Before the first live run, start IB Gateway with the **Read-Only API** enabled.

---

## Quick Start

First create the workspace-local configuration. Use `paper` for a simulated
Gateway, or use `live` only after explicitly choosing the live Gateway port.

```bash
export CONFIG="$WORKSPACE_ROOT/.ib-suite/config.yaml"

"$WORKSPACE_ROOT/.ib-suite/venv/bin/python" \
  "$SKILL_ROOT/scripts/init_config.py" \
  --mode paper --out "$CONFIG"
```

All connections use `readonly=True`, including `live` mode.

1. Start IB Gateway or TWS and enable its Read-Only API.
2. Read `SKILL.md`, then the reference that matches the request.
3. Run a read-only capability. For example, ingest the current account and
   positions:

   ```bash
   "$WORKSPACE_ROOT/.ib-suite/venv/bin/python" \
     "$SKILL_ROOT/ib-gateway/scripts/ib_sync.py" --config "$CONFIG"
   ```

4. Use the resulting snapshot for an offline report:

   ```bash
   "$WORKSPACE_ROOT/.ib-suite/venv/bin/python" \
     "$SKILL_ROOT/ib-portfolio-analyst/scripts/analyze.py" \
     --config "$CONFIG" \
     --snapshot "$WORKSPACE_ROOT/.ib-suite/data/snapshots/<account>/<timestamp>.json" \
     --out "$WORKSPACE_ROOT/.ib-suite/data/runs/<timestamp>"
   ```

Which capability should I use?

| You want to… | Read this reference |
|---|---|
| Refresh account and position data from IB | [Gateway sync](skills/ib-suite/references/ib-gateway.md) |
| See equity, margin, liquidity, and P&L now | [Account overview](skills/ib-suite/references/ib-account-overview.md) |
| List and rank open positions | [Positions overview](skills/ib-suite/references/ib-positions-overview.md) |
| Explain today's realized and unrealized P&L | [Daily P&L](skills/ib-suite/references/ib-daily-pnl.md) |
| Inspect historical fills, commissions, and realized P&L | [Trade history](skills/ib-suite/references/ib-trade-history.md) |
| Inspect paid or expected dividends, tax, and yield | [Dividend income](skills/ib-suite/references/ib-dividend-income.md) |
| Inspect option holdings, IV, Greeks, expiry, and concentration | [Options overview](skills/ib-suite/references/ib-options-overview.md) |
| Produce a diagnostic report from local data | [Portfolio analyst](skills/ib-suite/references/ib-portfolio-analyst.md) |

The scripts print structured JSON or output paths to stdout and return a
non-zero exit status on failure. This makes them usable without an agent.

---

## Configuration

Runtime state is isolated in `$WORKSPACE_ROOT/.ib-suite/`; the installed skill
ships code, locked dependency definitions, references, and the configuration
template only. Credentials remain local and must never be committed or printed.

- **Location.** The configuration is
  `$WORKSPACE_ROOT/.ib-suite/config.yaml`. The template is
  [`skills/ib-suite/ib-common/config.example.yaml`](skills/ib-suite/ib-common/config.example.yaml).
  `storage.root: data` is resolved relative to that configuration file.
- **Connection.** Use `port: 4002` for paper or `4001` for live as appropriate;
  keep `read_only: true`.
- **Flex credentials.** Trade history and dividend income share `flex.token`
  but use separate Query-ID maps. Quote each Query ID in YAML to preserve
  leading zeros. Provide a token through the setup flow or stdin, never on the
  command line or as a committed environment-variable fallback.
- **Flex queries.** Follow the [trade-history setup](skills/ib-suite/references/ib-trade-history-flex-query-setup.md)
  or [dividend setup](skills/ib-suite/references/ib-dividend-income-flex-query-setup.md)
  before using those reporters.
- **Thresholds.** P0–P3 thresholds for leverage, concentration, VaR,
  withholding drag, yield on cost, and more are under `thresholds:` in the
  configuration template.
- **Cost control.** `options.fetch_market_data: false` is the default. Position,
  price, market value, and P&L still use IB-computed portfolio fields, while
  Greeks and IV are skipped to avoid IBKR snapshot charges. Set it to `true`
  only when you intend to request that market data.

---

## Safety & Read-only boundary

This is a hard boundary, not a preference:

- Every IB Gateway connection uses `readonly=True`; no module imports an order API.
- No order placement, modification, cancellation, real-time WhatIf margin
  check, real-time market-data stream, or write path into IB is included.
- Flex reporters and offline analysis never change account state.
- Flex tokens, Query IDs, account numbers, and live snapshots must not appear
  in stdout, logs, fixtures, or version control.

---

## Development & Testing

The committed runtime, build, and test locks are generated with
`uv==0.12.13`. When an input changes, regenerate all relevant lock files with
that version. Use an isolated development environment; it is not the
workspace-owned runtime environment used by an installed skill.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes \
  -r skills/ib-suite/requirements-test.lock
.venv/bin/python -m pip install -e skills/ib-suite/ib-common

# Full suite
PYTHONPATH=skills/ib-suite/ib-common .venv/bin/python -m pytest skills/ib-suite -q

# Distribution and bootstrap contract
PYTHONPATH=skills/ib-suite/ib-common .venv/bin/python -m pytest \
  skills/ib-suite/scripts/tests/test_bootstrap.py \
  skills/ib-suite/tests/test_distribution_contract.py -q
```

Use Python 3.11+, write a failing test before implementation, and keep changes
small. Tests must stay offline: network and IB access are behind injectable
clients. Do not commit virtual environments, `.ib-suite/`, credentials, live
snapshots, or generated reports.

---

## Project Structure

```text
skills/ib-suite/                 one installable Agent Skill
  SKILL.md                       entry skill and capability router
  references/                    focused instructions for each capability
  scripts/setup_venv.sh          workspace-owned environment bootstrap
  scripts/bootstrap.py           versioned environment lifecycle
  requirements-*.in / *.lock     runtime, build, and test dependencies
  ib-common/                     shared Python package: config, schema, storage, metrics, charts
  ib-gateway/                    account and positions -> local data lake
  ib-account-overview/           live account overview -> stdout JSON
  ib-positions-overview/         live positions overview -> stdout JSON
  ib-daily-pnl/                  daily P&L breakdown -> stdout JSON
  ib-trade-history/              Flex trade history -> stdout JSON
  ib-dividend-income/            Flex dividend report -> stdout JSON
  ib-options-overview/           live options and Greeks -> stdout JSON
  ib-portfolio-analyst/          local data -> report and charts
```

---

## Disclaimer

This software is for **informational and diagnostic purposes only**. It is not
investment advice, and it makes no trading decisions. Interactive Brokers and
IBKR are trademarks of Interactive Brokers LLC; this project is not affiliated
with, endorsed by, or sponsored by Interactive Brokers. You are responsible for
your own use of your brokerage account and for complying with IBKR's terms.

---

## Contributing

Issues and pull requests are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md)
for development setup and commit conventions,
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for community expectations, and
[`SECURITY.md`](SECURITY.md) to report vulnerabilities privately. Run the full
test suite and keep secrets and runtime data out of commits.

---

## License

[MIT](LICENSE) © the ib-suite contributors.
