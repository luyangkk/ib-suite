---
name: ib-suite
description: Read-only Interactive Brokers toolchain index. Use when orienting in the skills/ directory, deciding which IB skill to run (ib-gateway vs ib-portfolio-analyst) or in what order, or when integrating the toolchain from another system. Not for doing the work itself — the sub-skills own that.
metadata:
  openclaw:
    homepage: https://docs.openclaw.ai/tools/skills
    requires:
      bins: [python3]
      config: [config.yaml]
    os: [darwin, linux]
---

# ib-suite — Interactive Brokers read-only toolchain

This directory is a **read-only** IB (Interactive Brokers) diagnostics toolchain:
pull account data from IB, land it in a local data lake, and turn it into a
graded portfolio-diagnostics report. **Nothing here ever places, modifies, or
cancels an order.** Ingestion connects with `readonly=True`; analysis never
touches the network.

This SKILL.md is the entry point. It does not run anything itself — it tells you
(and OpenClaw) which sub-skill to run, in what order, and how the pieces fit.

## 1. Directory overview

| Component | What it is | Runs a command? | Network? |
|---|---|---|---|
| [ib-common](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-suite/ib-common) | Shared `pip`-installable package (config / schema / storage / metrics / charts). **Not a skill.** | No | No |
| [ib-gateway](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-suite/ib-gateway) | Read-only ingestion skill → `/ib-sync` | Yes | Yes (IB Gateway / Flex) |
| [ib-portfolio-analyst](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-suite/ib-portfolio-analyst) | Offline diagnostics skill → `/ib-analyze` | Yes | No |

```
skills/ib-suite/
  SKILL.md                 # <- you are here (index / router)
  scripts/setup_venv.sh    # shared venv bootstrap (installs ib-common editable)
  ib-common/               # shared library (installed editable into .venv)
  ib-gateway/              # /ib-sync   : IB/Flex -> local data lake
  ib-portfolio-analyst/    # /ib-analyze: data lake -> report.md + charts
```

**Scope.** In: read-only sync, snapshots, Parquet history, and P0–P3 findings
across account health, concentration, P&L attribution, trade review, portfolio
risk, pre-trade simulation, and dividends. **Out (hard boundary):** order
placement/modification/cancellation, live WhatIf margin checks, real-time market
data, and any write path to IB. Do not add these under the banner of
"completeness".

## 2. Run guide

Dependency direction: `ib-common` ← `ib-gateway` (produces data) ← `ib-portfolio-analyst` (consumes data).

```
setup_venv.sh        ->  ib-gateway /ib-sync      ->  ib-portfolio-analyst /ib-analyze
(install ib-common)      (write data lake)             (read lake -> report)
```

1. **Setup once (or after dependency changes).** Bootstraps the shared `.venv`
   and installs `ib-common` (editable) plus runtime deps. Idempotent.
   ```bash
   bash {baseDir}/scripts/setup_venv.sh
   cp {baseDir}/ib-common/config.example.yaml ./config.yaml   # then edit ports/thresholds
   ```

   **Runtime data lives outside the skill dir.** Keep the real `config.yaml` and
   the data lake under the workspace, e.g. `<workspace>/.ib-suite/config.yaml`
   and `<workspace>/.ib-suite/data/` (set `storage.root: .ib-suite/data`). The
   skill directory ships only code and `config.example.yaml`; reinstalling the
   skill must never overwrite user data. Entry scripts take explicit `--config`
   / `--out` and don't depend on the current working directory.

2. **Ingest (ib-gateway, online).** Start IB Gateway (paper 4002 / live 4001)
   with API access, then run `/ib-sync`. Writes `data/snapshots/<account>/<ts>.json`
   and appends `data/timeseries/positions_history.parquet`. See
   [ib-gateway/SKILL.md](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-suite/ib-gateway/SKILL.md).
3. **Analyze (ib-portfolio-analyst, offline).** Run `/ib-analyze` against a
   snapshot to produce `report.md` + `.html`/`.png` charts. See
   [ib-portfolio-analyst/SKILL.md](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/skills/ib-suite/ib-portfolio-analyst/SKILL.md).

**Which skill do I run?**

| You want to… | Run |
|---|---|
| Refresh account/position data from IB | `ib-gateway` → `/ib-sync` |
| Produce a diagnostic report from existing data | `ib-portfolio-analyst` → `/ib-analyze` |
| Test either skill without IB | its `tests/` fixtures (see §5) |

**Note on optional inputs.** `/ib-sync` v1 lands only the account snapshot and
positions. Daily bars, executions, and dividends are optional JSON arrays
(matching the `DailyBar` / `Execution` / `Dividend` schema, e.g. exported from a
Flex report) that you pass to `/ib-analyze` directly; the corresponding report
sections appear only when their data is supplied.

## 3. Sub-skill module spec

Every functional sub-skill directory (`ib-gateway`, `ib-portfolio-analyst`, and
any future one) MUST follow this contract:

- **`SKILL.md` with valid frontmatter.** Required `name` + `description`, and
  `metadata.openclaw` (`requires.bins`, `requires.config`, `os`) so OpenClaw can
  discover and gate it. `name` MUST equal the directory name (lowercase, stable).
- **`description` states the read-only boundary.** Start with "Read-only", say
  what it does and when it triggers, and stay narrow enough to avoid mis-firing.
- **`scripts/` holds the deterministic entry logic.** Use `argparse`; validate
  required args; exit non-zero with an actionable message on failure. Commands in
  `SKILL.md` use the `{baseDir}` placeholder and `.venv/bin/python` — never
  absolute or hardcoded user paths.
- **Network/IB access hides behind an injectable factory** (`client_factory`,
  `http_get`) so `tests/` run fully offline against `fixtures/`.
- **Reuse `ib-common`, don't fork it.** Types come from `ib_common.schema`
  (pydantic v2); reuse `Finding`, `grade()`, `thresholds`, storage helpers, and
  `render()` for charts. New diagnostic modules live in `ib_analyst/`, expose
  `analyze(...) -> list[Finding]` with a module-level `DIM` constant and an
  optional `build_chart(...) -> plotly.Figure`, and are wired into
  `analyze.py`'s `run()`. New thresholds MUST also be added to
  `ib-common/config.example.yaml` under `thresholds:`.
- **`from __future__ import annotations`** at the top of every module; type-annotate
  functions; docstring public functions.

## 4. Invocation

**As OpenClaw slash commands (primary).** Once discovered, the sub-skills expose
`/ib-sync` and `/ib-analyze`. Gating is driven by each skill's `metadata.openclaw`
(`python3` on `PATH`, a `config.yaml`, and a supported OS).

**As direct scripts (for automation / other systems).** Call the entry scripts
with the shared interpreter; they print structured, parseable results (dicts /
output paths) to stdout and return non-zero on failure:

```bash
# ingest
{baseDir}/.venv/bin/python {baseDir}/ib-gateway/scripts/ib_sync.py --config ./config.yaml

# analyze (bars/executions/dividends optional)
{baseDir}/.venv/bin/python {baseDir}/ib-portfolio-analyst/scripts/analyze.py \
  --config ./config.yaml \
  --snapshot data/snapshots/<account>/<ts>.json \
  --out data/runs/$(date +%Y%m%dT%H%M%S)
```

**As a library.** `import ib_common` (installed editable) for config/schema/
storage/metrics/charts. Secrets are passed via environment only — e.g. the Flex
token as `$FLEX_TOKEN`; never hardcode tokens, account numbers, or user paths.

## 5. Version & maintenance

- **Suite version:** `0.1.0` (aligned with `ib-common` `0.1.0`).
- **Maintainers:** IB analyst toolchain owners — see repository git history /
  `CLAUDE.md` for the authoritative project rules and conventions.
- **Test baseline:** `54 passed`.
  ```bash
  skills/ib-suite/.venv/bin/python -m pytest skills -q          # full suite
  skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-portfolio-analyst -q   # one skill
  ```

### Changelog

| Version | Summary |
|---|---|
| 0.1.0 | Initial toolchain. `ib-common` shared package (config/schema/storage/metrics/charts). `ib-gateway`: `/ib-sync` read-only IB pull + Flex Web Service fetch/parse. `ib-portfolio-analyst`: `/ib-analyze` producing a P0–P3 report across account health, concentration, P&L attribution, trade review, portfolio risk, pre-trade simulation, and dividend analysis. Baseline: 54 tests passing. |

> Detailed design history lives in
> [docs/superpowers/plans/](file:///Users/bytedance/Work/aiWorkspace/openclaw-ib-skill/docs/superpowers/plans)
> (Plan 1 foundation / Plan 2 diagnostics / Plan 3 dividends) — consult on demand,
> don't load wholesale.
