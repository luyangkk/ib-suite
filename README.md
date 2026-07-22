# ib-suite — Read-only Interactive Brokers diagnostics for AI agents

**English** | [简体中文](README.zh-CN.md)

[![CI](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml)
[![Agent Skill](https://img.shields.io/badge/format-Agent%20Skill-6f42c1)](#installation)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org/)
[![Read-only](https://img.shields.io/badge/IB%20access-read--only-2ea44f)](#safety--read-only-boundary)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

A portable **Agent Skill** suite (built on the `SKILL.md` convention) that pulls
**Interactive Brokers (IBKR)** account data **read-only** and turns it into
structured portfolio diagnostics — account health, positions, daily P&L, trade
history, dividend income, options Greeks, and a graded P0–P3 findings report.
**Nothing here ever places, modifies, or cancels an order.**

**Not tied to any single agent.** It integrates natively with
[OpenClaw](https://clawhub.ai) (slash commands + gating), works with any agent
runtime that loads `SKILL.md` skills, and — since every entry point is a plain
Python script that prints JSON to stdout, backed by the importable `ib-common`
library — can also be driven directly by any other agent, automation, or you.

One index skill + eight functional sub-skills + one shared library. The whole
`skills/ib-suite/` directory is the single installable unit.

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

`ib-suite` is the router/index skill; the real work is done by the eight
sub-skills below. Each is exposed as an `/ib-*` slash command under OpenClaw; on
other runtimes you invoke the same skill via its `SKILL.md`, or call the entry
script directly (see [Installation](#installation)).

| Skill | Command | What it does | Network |
|---|---|---|---|
| `ib-suite` | — | Index / router + first-run onboarding (venv + live/paper config). Runs nothing itself. | No |
| `ib-gateway` | `/ib-sync` | Read-only ingestion → local data lake (snapshot JSON + positions Parquet). | IB Gateway / Flex |
| `ib-account-overview` | `/ib-account-overview` | Live account snapshot: equity, cash, buying power, margin, liquidity, P&L, per-currency. | IB Gateway |
| `ib-positions-overview` | `/ib-positions-overview` | Live enriched positions, ranked four ways, most-concentrated name flagged. | IB Gateway |
| `ib-daily-pnl` | `/ib-daily-pnl` | Today's realized/unrealized P&L, ranked winners/losers, by asset class & currency. | IB Gateway |
| `ib-trade-history` | `/ib-trade-history` | Flex execution history, commissions, realized FIFO P&L, win/loss stats. | Flex Web Service |
| `ib-dividend-income` | `/ib-dividend-income` | Flex-only paid/expected dividends, tax, attribution, annual estimate, yield. | Flex Web Service |
| `ib-options-overview` | `/ib-options-overview` | Live option positions, IV, Greeks, expiry exposure, concentration. | IB Gateway |
| `ib-portfolio-analyst` | `/ib-analyze` | Offline diagnostics: reads the lake → P0–P3 findings `report.md` + charts. | No |

The four live overviews and the two Flex reporters **print a single parseable
JSON object to stdout and persist nothing**. Only `/ib-sync` writes to the local
data lake; `/ib-analyze` is fully offline.

---

## Prerequisites

- **Python ≥ 3.11** on `PATH` (the real engine; enforced by `pyproject.toml`).
- **A way to invoke it** — either an agent runtime that loads `SKILL.md` skills
  (e.g. [OpenClaw](https://clawhub.ai)), **or** nothing extra: call the entry
  scripts / import `ib-common` directly.
- **IB Gateway** (or TWS) running locally with the **Read-Only API enabled** —
  paper on port `4002`, live on port `4001` — required for every *live* skill
  (`/ib-sync`, account/positions/daily-P&L/options overviews).
- **A Flex Web Service token + Query IDs** — required only for the two Flex
  skills (`/ib-trade-history`, `/ib-dividend-income`). See [Configuration](#configuration).
- macOS or Linux (`os: [darwin, linux]`).

---

## Installation

Clone the repo, then build the shared virtualenv. The only difference between
runtimes is *where* you clone and *how* the skill gets discovered.

### 1. Clone

```bash
# With OpenClaw — clone into a skills root so it is auto-discovered:
git clone https://github.com/luyangkk/ib-suite.git \
  ~/.openclaw/workspace/skills/ib-suite

# With any other agent, or direct/library use — clone anywhere:
git clone https://github.com/luyangkk/ib-suite.git ~/ib-suite
```

OpenClaw scans skills roots recursively and discovers the nested
`skills/ib-suite/SKILL.md` (and every sub-skill) automatically — the skill *name*
comes from each `SKILL.md` frontmatter, not the folder path. Other SKILL.md-aware
runtimes point at the same files; anything else calls the scripts directly.

### 2. Bootstrap the shared virtualenv (once)

```bash
bash <clone>/skills/ib-suite/scripts/setup_venv.sh
```

`<clone>` is wherever you cloned in step 1. This is idempotent: it picks a
Python ≥ 3.11, creates `.venv`, and installs the shared `ib-common` package
(editable) plus runtime deps.

### 3a. Load it (OpenClaw)

```bash
# From an OpenClaw chat: archive the current session and start fresh
/new
# …or restart the gateway
openclaw gateway restart
```

Verify with `openclaw skills list` — you should see `ib-suite` and the `/ib-*`
commands.

### 3b. Load it (any other agent / direct use)

Point your agent at the cloned `skills/ib-suite/` directory and its `SKILL.md`
files, or just call the entry scripts (see [Quick Start](#quick-start)). No
agent-specific registration is required.

### Install PROMPT — paste this to any capable agent

Prefer to let the agent do it? Copy-paste the prompt below (the generic form
works for any agent; the parenthetical note adapts it to OpenClaw):

```text
Set up the read-only IBKR diagnostics skill suite for me:

1. Clone https://github.com/luyangkk/ib-suite.git to a local directory.
   (OpenClaw: clone it into my skills root, ~/.openclaw/workspace/skills/ib-suite)
2. Build the shared virtualenv:
   bash <clone>/skills/ib-suite/scripts/setup_venv.sh
3. Read <clone>/skills/ib-suite/SKILL.md and the sub-skill SKILL.md files so you
   know the available /ib-* capabilities, then tell me which ones you can run.
   (OpenClaw: instead reload skills with /new, run `openclaw skills list`, and
   show me every /ib-* command that is now available.)

Important: this suite is strictly read-only. Do NOT place, modify, or cancel any
order, and do NOT configure anything that writes to my IB account. If a step
fails, stop and tell me the exact error instead of guessing.
```

Before the first live run, start IB Gateway with the **Read-Only API** enabled.

---

## Quick Start

First use goes through onboarding (build the venv + pick live/paper to generate
the config), then run `/ib-sync` → `/ib-analyze`.

1. **First-run setup.** Under OpenClaw the `ib-suite` index skill owns this: it
   detects whether `.ib-suite/config.yaml` exists, ensures the venv, asks
   **live** (real account, port 4001) or **paper** (simulated, 4002) once, and
   generates the config. Under any other runtime, generate it yourself:
   ```bash
   <clone>/skills/ib-suite/.venv/bin/python \
     <clone>/skills/ib-suite/scripts/init_config.py --mode live --out .ib-suite/config.yaml
   ```
   Every connection is `readonly=True`, so *live* is read-only too.
2. **Start IB Gateway** with the Read-Only API enabled.
3. **Ingest** current account & positions — `/ib-sync` (OpenClaw), or the script below.
4. **Analyze** a snapshot into a graded report + charts — `/ib-analyze`, or the script below.

Which skill do I run?

| You want to… | Skill / command |
|---|---|
| Refresh account/position data from IB | `/ib-sync` |
| See equity, margin, liquidity & P&L right now | `/ib-account-overview` |
| List every position, ranked, most-concentrated flagged | `/ib-positions-overview` |
| See how the account did today and what drove it | `/ib-daily-pnl` |
| Historical fills, commission, realized P&L, win/loss | `/ib-trade-history` |
| Paid/expected dividends, tax, attribution, yield | `/ib-dividend-income` |
| Option holdings, IV, Greeks, expiry exposure | `/ib-options-overview` |
| A diagnostic report from existing data | `/ib-analyze` |

**Direct invocation (any agent / automation / human).** The entry scripts print
structured JSON / output paths to stdout and exit non-zero on failure — no agent
required:

```bash
SKILLS=<clone>/skills/ib-suite            # the cloned skill directory
VENV=$SKILLS/.venv/bin/python

# ingest
$VENV $SKILLS/ib-gateway/scripts/ib_sync.py --config .ib-suite/config.yaml

# Flex-only dividend income (inclusive dates required)
$VENV $SKILLS/ib-dividend-income/scripts/dividend_income.py \
  --config .ib-suite/config.yaml \
  --start-date 2026-01-01 --end-date 2026-07-19
```

You can also `import ib_common` (installed editable in `.venv`) to reuse the
config/schema/storage/metrics/charts helpers as a library.

---

## Configuration

Real config and data live under a workspace-local `.ib-suite/` directory
(gitignored); the skill directory ships only code and `config.example.yaml`.
Credentials stay local — never committed, never printed.

- **Location.** Runtime config and the data lake live under a workspace-local
  `.ib-suite/` directory (gitignored, created at runtime). The template is
  [`skills/ib-suite/ib-common/config.example.yaml`](skills/ib-suite/ib-common/config.example.yaml).
- **Connection.** `port: 4002` (paper) / `4001` (live); `read_only: true` — keep
  it true, this project never places orders.
- **Flex credentials.** `/ib-trade-history` and `/ib-dividend-income` share one
  `flex.token` but keep **separate per-window Query ID maps**
  (`flex.trade_history_query_ids` / `flex.dividend_query_ids`). Quote every ID in
  YAML to preserve leading zeros. Set the token via the skill's setup flow
  (passed through stdin) — never on the command line, never via env fallback.
- **Dividend Flex Query.** The dividend skill needs an Activity Flex Query with a
  365-day window and six required sections. See the standalone guide:
  [`skills/ib-suite/ib-dividend-income/flex-query-setup.md`](skills/ib-suite/ib-dividend-income/flex-query-setup.md).
- **Thresholds.** All P0–P3 grading thresholds (leverage, concentration, VaR,
  withholding drag, yield on cost, …) live under `thresholds:` in the config
  template — tune them there.
- **Cost control.** `options.fetch_market_data: false` by default: option
  position/price/P&L still work (IB-computed, free), but Greeks/IV are skipped to
  avoid IBKR snapshot charges. Set `true` to opt in.

---

## Safety & Read-only boundary

This is a **hard boundary**, not a preference:

- Every IB Gateway connection uses `readonly=True`; no module imports an order API.
- **No order placement / modification / cancellation, no live WhatIf margin
  checks, no real-time market-data streaming, no write path into IB** — ever.
- Flex reporters and offline analysis never touch your account state.
- Secrets (Flex token, Query IDs, account numbers) never appear in stdout, logs,
  or committed files. Fixtures are desensitized.

---

## Development & Testing

There is **no** `validate.py` / `package_skill.py`; validation is tests + review.

```bash
SKILLS=<clone>/skills/ib-suite

# First time, or after dependency changes: bootstrap the shared venv (idempotent)
bash $SKILLS/scripts/setup_venv.sh

# Full test run
$SKILLS/.venv/bin/python -m pytest skills -q

# One skill only, e.g. dividend income
$SKILLS/.venv/bin/python -m pytest skills/ib-suite/ib-dividend-income -q
```

Conventions: Python ≥ 3.11, `from __future__ import annotations`, Pydantic v2
models, TDD (red → green), and surgical changes only. Network/IB access hides
behind an injectable `client_factory` / `http_get` so tests run fully offline.

---

## Project Structure

```text
skills/ib-suite/                 the single installable Agent Skill unit
  SKILL.md                       index / router skill (always:true, owns onboarding)
  scripts/setup_venv.sh          idempotent shared-venv bootstrap
  ib-common/                     shared pip package (config/schema/storage/metrics/charts) — NOT a skill
  ib-gateway/                    /ib-sync                : IB/Flex → local data lake
  ib-account-overview/           /ib-account-overview    : live account overview → stdout JSON
  ib-positions-overview/         /ib-positions-overview  : live enriched positions → stdout JSON
  ib-daily-pnl/                  /ib-daily-pnl           : today's P&L breakdown → stdout JSON
  ib-trade-history/              /ib-trade-history       : Flex executions → stdout JSON
  ib-dividend-income/            /ib-dividend-income     : Flex dividends → stdout JSON
  ib-options-overview/           /ib-options-overview    : live options + Greeks → stdout JSON
  ib-portfolio-analyst/          /ib-analyze             : data lake → report.md + charts
```

See [`CLAUDE.md`](CLAUDE.md) for the full architecture, conventions, and
contributor rules.

---

## Disclaimer

This software is for **informational and diagnostic purposes only**. It is not
investment advice, and it makes no trading decisions. Interactive Brokers and
IBKR are trademarks of Interactive Brokers LLC; this project is not affiliated
with, endorsed by, or sponsored by Interactive Brokers. You are responsible for
your own use of your brokerage account and for complying with IBKR's terms.

---

## Contributing

Issues and PRs are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
dev setup, the read-only invariant, and commit conventions;
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for community expectations; and
[`SECURITY.md`](SECURITY.md) to report vulnerabilities privately. Run the full
test suite and keep secrets and runtime data (`.ib-suite/`, real `config.yaml`,
live snapshots) out of commits. See [`CLAUDE.md`](CLAUDE.md) for the full
architecture.

---

## License

[MIT](LICENSE) © the ib-suite contributors.
