---
name: ib-portfolio-analyst
description: Read-only IB diagnostics: account health, concentration, P&L attribution, trade review, portfolio risk, pre-trade check — a P0-P3 findings report with charts.
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [config.yaml]
    os: [darwin, linux]
---

# ib-portfolio-analyst

Turns the local data lake (populated by `ib-gateway`) into a structured
P0–P3 diagnostic report. Never contacts IB and never places orders — it
reads snapshots, bars and executions that were already synced.

## Prerequisite

Run `ib-gateway`'s `/ib-sync` first so a snapshot exists under `data/snapshots/`.

## /ib-analyze — run all diagnostics

```bash
{baseDir}/../../.venv/bin/python {baseDir}/scripts/analyze.py \
  --config ./config.yaml \
  --snapshot data/snapshots/<account>/<ts>.json \
  --bars data/timeseries/daily_bars.json \
  --executions data/timeseries/executions.json \
  --out data/runs/$(date +%Y%m%dT%H%M%S)
```

Produces `report.md` plus interactive `.html` and static `.png` charts in the
output directory. `--bars`/`--executions` are optional; risk and trade-review
sections are included only when their data is present.

## Findings

Each finding carries: priority (P0–P3), dimension, finding, evidence,
impact, suggestion, trigger condition, confidence, and data limitations.
Findings are diagnostic and directional only — never return promises.

## Notes

- All thresholds live in `config.yaml` under `thresholds:` (see ib-common's `config.example.yaml`).
- Pre-trade check is a local estimate in v1; a real IB WhatIf margin check is planned for v2.
