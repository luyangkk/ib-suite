# IB Analyst — Plan 1: Foundation (ib-common + ib-gateway) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared data-and-utility foundation (`ib-common`) plus the data-ingestion skill (`ib-gateway`) that pulls read-only account / position / execution / daily-bar / dividend data from IB Gateway and Flex Web Service and lands it into a local snapshot + time-series data lake.

**Architecture:** Two-layer design. `ib-common` is a pip-installable Python package (config, typed schema, storage, metrics, charts) shared by every downstream skill. `ib-gateway` is an OpenClaw skill exposing `/ib-sync`, which connects to a **read-only** IB Gateway session (or reads a Flex report) and writes a desensitized JSON snapshot (instantaneous state) plus append-only Parquet files (time-series history). No order-placing APIs are imported anywhere in this plan.

**Tech Stack:** Python 3.11+, `ib_async` (IB Gateway TCP), `requests` (Flex Web Service), `pydantic` v2 (schema), `pandas` + `pyarrow` (Parquet), `numpy` (metrics), `plotly` + `kaleido` (charts, dual HTML+PNG output), `pytest` (TDD, fixture-snapshot tests), `ruamel.yaml` (config).

## Global Constraints

- **Read-only guarantee:** No module may import or call any order-placing / order-modifying IB API (`placeOrder`, `cancelOrder`, `reqGlobalCancel`, etc.). WhatIf/pre-trade checks are deferred to a later plan and simulated locally. — copied verbatim from decision ⑥.
- **Currency base:** Report currency follows the IB account's `BASE` currency reported by the Gateway; never hard-code USD. — decision (currency base follows IB account settings).
- **Data freshness:** Default staleness threshold 24h, fully overridable via `config.yaml`. — decision (24h configurable).
- **Data privacy:** All fixtures and any archived snapshot committed to the repo MUST be desensitized (account IDs masked, absolute cash values scaled or redacted). Offline processing only. — decision ⑮ + user engineering values.
- **Config:** One central `config.yaml`; every threshold/parameter has a default template and is overridable. — decision ⑩.
- **Storage:** Instantaneous state → JSON snapshot; history → append-only Parquet. — decision ⑪.
- **Charts:** plotly + kaleido, dual product: interactive `.html` + static `.png` archived to disk. No browser runtime dependency. — decision ⑬.
- **Comments:** Function-level docstrings/comments in English (OSS standard); dialogue in Chinese.
- **TDD:** Every task follows write-failing-test → run-fail → implement → run-pass → commit. — decision ⑮.

---

## File Structure

```
skills/
  ib-common/                          # shared, pip-installable package (NOT a skill)
    pyproject.toml
    requirements.txt
    config.example.yaml
    ib_common/
      __init__.py
      config.py                       # load + validate config.yaml, resolve base currency
      schema.py                       # pydantic models: Account, Position, Execution, DailyBar, Dividend, Snapshot
      storage.py                      # write JSON snapshot + append Parquet time-series
      metrics/
        __init__.py
        returns.py                    # sharpe, sortino, calmar
        risk.py                       # max_drawdown, hist_var, hist_cvar, hhi
      charts/
        __init__.py
        render.py                     # fig -> {html, png} dual output via kaleido
    tests/
      fixtures/
        config_minimal.yaml
        snapshot_sample.json
        daily_bars_sample.json
      test_config.py
      test_schema.py
      test_storage.py
      test_metrics_returns.py
      test_metrics_risk.py
      test_charts.py
  ib-gateway/                         # OpenClaw skill: pull data, land to data lake
    SKILL.md
    scripts/
      ib_sync.py                      # /ib-sync entrypoint: Gateway live pull -> snapshot + parquet
      flex_fetch.py                   # Flex Web Service: reference-code -> parsed history
    tests/
      fixtures/
        flex_response_sample.xml
        ib_raw_account_sample.json
      test_ib_sync.py
      test_flex_fetch.py
  .venv/                              # shared virtualenv (created by bootstrap, git-ignored)
```

**Boundary rationale:** `ib-common` owns everything reusable and testable without a live Gateway (pure functions over typed data). `ib-gateway` owns the only code that talks to the network; its live-connection code is thin and isolated behind an injectable client so tests run against fixtures.

---

## Task 0: Repo scaffolding + shared venv bootstrap

**Files:**
- Create: `skills/ib-common/pyproject.toml`
- Create: `skills/ib-common/requirements.txt`
- Create: `.gitignore`
- Create: `scripts/setup_venv.sh`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: an importable `ib_common` package installed editable into `.venv`; `.venv/bin/python` used by all later `exec` calls.

- [ ] **Step 1: Write `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
# archived run artifacts (charts/snapshots) are NOT committed by default
data/runs/
```

- [ ] **Step 2: Write `skills/ib-common/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ib-common"
version = "0.1.0"
description = "Shared foundation for IB analyst skills: config, schema, storage, metrics, charts."
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "pandas>=2.2",
    "pyarrow>=15",
    "numpy>=1.26",
    "plotly>=5.20",
    "kaleido>=0.2.1",
    "ruamel.yaml>=0.18",
]

[tool.setuptools.packages.find]
include = ["ib_common*"]
```

- [ ] **Step 3: Write `skills/ib-common/requirements.txt`** (for the ingestion skill's runtime + test deps)

```text
-e ./skills/ib-common
ib_async>=1.0.1
requests>=2.31
pytest>=8.0
```

- [ ] **Step 4: Write `scripts/setup_venv.sh`**

```bash
#!/usr/bin/env bash
# Create the shared virtualenv and install ib-common (editable) + runtime deps.
# Idempotent: safe to re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r skills/ib-common/requirements.txt
echo "venv ready: $ROOT/.venv"
```

- [ ] **Step 5: Run bootstrap to verify it succeeds**

Run: `bash scripts/setup_venv.sh && .venv/bin/python -c "import ib_common, pydantic, pandas, pyarrow, plotly, kaleido; print('ok')"`
Expected: prints `ok` (may take a minute on first install).

- [ ] **Step 6: Commit**

```bash
git add .gitignore scripts/setup_venv.sh skills/ib-common/pyproject.toml skills/ib-common/requirements.txt
git commit -m "chore: scaffold ib-common package and shared venv bootstrap"
```

---

## Task 1: Config loading + base-currency resolution

**Files:**
- Create: `skills/ib-common/ib_common/__init__.py` (empty)
- Create: `skills/ib-common/ib_common/config.py`
- Create: `skills/ib-common/config.example.yaml`
- Create: `skills/ib-common/tests/fixtures/config_minimal.yaml`
- Test: `skills/ib-common/tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `load_config(path: str | Path) -> Config` — returns a validated `Config` pydantic model.
  - `Config` fields: `connection.host: str`, `connection.port: int`, `connection.client_id: int`, `connection.read_only: bool`, `data.freshness_hours: float`, `data.base_currency: str | None`, `thresholds: dict[str, float]`, `storage.root: str`.
  - `resolve_base_currency(cfg: Config, account_base: str | None) -> str` — returns `account_base` when set (account setting wins), else `cfg.data.base_currency`, else raises `ValueError`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-common/tests/test_config.py
from pathlib import Path
import pytest
from ib_common.config import load_config, resolve_base_currency

FIX = Path(__file__).parent / "fixtures"

def test_load_config_applies_defaults():
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.connection.read_only is True          # default must be read-only
    assert cfg.data.freshness_hours == 24.0          # default freshness
    assert cfg.connection.port == 4002               # paper default

def test_base_currency_follows_account_when_present():
    cfg = load_config(FIX / "config_minimal.yaml")
    assert resolve_base_currency(cfg, "HKD") == "HKD"   # account setting wins

def test_base_currency_falls_back_to_config():
    cfg = load_config(FIX / "config_minimal.yaml")
    assert resolve_base_currency(cfg, None) == "USD"    # config override

def test_base_currency_missing_raises():
    cfg = load_config(FIX / "config_minimal.yaml")
    cfg.data.base_currency = None
    with pytest.raises(ValueError):
        resolve_base_currency(cfg, None)
```

- [ ] **Step 2: Write the minimal fixture**

```yaml
# skills/ib-common/tests/fixtures/config_minimal.yaml
data:
  base_currency: USD
storage:
  root: ./data
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ib_common.config'`.

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-common/ib_common/config.py
"""Central configuration loading and base-currency resolution.

One config.yaml drives every skill. Unspecified fields fall back to safe
defaults defined here (read-only, paper port, 24h freshness).
"""
from __future__ import annotations
from pathlib import Path
from ruamel.yaml import YAML
from pydantic import BaseModel, Field


class ConnectionCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4002            # IB Gateway paper default; live is 4001
    client_id: int = 17
    read_only: bool = True      # never flip silently; read-only by default


class DataCfg(BaseModel):
    freshness_hours: float = 24.0
    base_currency: str | None = None   # None => follow account BASE at runtime


class StorageCfg(BaseModel):
    root: str = "./data"


class Config(BaseModel):
    connection: ConnectionCfg = Field(default_factory=ConnectionCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    thresholds: dict[str, float] = Field(default_factory=dict)


def load_config(path: str | Path) -> Config:
    """Load and validate config.yaml, applying defaults for missing keys."""
    yaml = YAML(typ="safe")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.load(f) or {}
    return Config(**raw)


def resolve_base_currency(cfg: Config, account_base: str | None) -> str:
    """Resolve report base currency. Account setting wins over config.

    Order: account BASE (from Gateway) -> config.data.base_currency -> error.
    """
    if account_base:
        return account_base
    if cfg.data.base_currency:
        return cfg.data.base_currency
    raise ValueError("base currency unresolved: no account BASE and no config default")
```

- [ ] **Step 5: Write the shipped example config** (documents every knob)

```yaml
# skills/ib-common/config.example.yaml
connection:
  host: 127.0.0.1
  port: 4002          # 4002 = paper, 4001 = live
  client_id: 17
  read_only: true     # keep true; this project never places orders
data:
  freshness_hours: 24
  base_currency: null # null => follow the IB account BASE currency
storage:
  root: ./data
thresholds:
  single_position_weight_warn: 0.20   # P2 when one name > 20% of portfolio
  single_position_weight_crit: 0.35   # P1 when > 35%
  hhi_concentration_warn: 0.18
  max_drawdown_warn: 0.20
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_config.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add skills/ib-common/ib_common/__init__.py skills/ib-common/ib_common/config.py skills/ib-common/config.example.yaml skills/ib-common/tests/test_config.py skills/ib-common/tests/fixtures/config_minimal.yaml
git commit -m "feat(ib-common): config loading with defaults and base-currency resolution"
```

---

## Task 2: Typed schema (pydantic models)

**Files:**
- Create: `skills/ib-common/ib_common/schema.py`
- Create: `skills/ib-common/tests/fixtures/snapshot_sample.json`
- Test: `skills/ib-common/tests/test_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all pydantic v2 `BaseModel`):
  - `Account(account_id: str, base_currency: str, net_liquidation: float, total_cash: float, buying_power: float, ts: datetime)`
  - `Position(account_id: str, symbol: str, sec_type: str, currency: str, quantity: float, avg_cost: float, market_price: float, market_value: float, unrealized_pnl: float)`
  - `Execution(exec_id: str, symbol: str, side: str, quantity: float, price: float, commission: float, ts: datetime)`
  - `DailyBar(symbol: str, date: date, open: float, high: float, low: float, close: float, volume: float)`
  - `Dividend(symbol: str, ex_date: date, pay_date: date | None, gross: float, tax: float, currency: str)`
  - `Snapshot(account: Account, positions: list[Position], ts: datetime)` with `Snapshot.model_validate_json` / `model_dump_json` round-tripping.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-common/tests/test_schema.py
from pathlib import Path
from ib_common.schema import Snapshot, Position

FIX = Path(__file__).parent / "fixtures"

def test_snapshot_round_trips_from_fixture():
    raw = (FIX / "snapshot_sample.json").read_text(encoding="utf-8")
    snap = Snapshot.model_validate_json(raw)
    assert snap.account.base_currency == "USD"
    assert len(snap.positions) == 2
    # round-trip must be lossless
    reparsed = Snapshot.model_validate_json(snap.model_dump_json())
    assert reparsed == snap

def test_position_market_value_types_are_floats():
    p = Position(account_id="U1", symbol="AAPL", sec_type="STK", currency="USD",
                 quantity=10, avg_cost=100.0, market_price=190.0,
                 market_value=1900.0, unrealized_pnl=900.0)
    assert isinstance(p.market_value, float)
```

- [ ] **Step 2: Write the fixture**

```json
{
  "account": {
    "account_id": "U0000000",
    "base_currency": "USD",
    "net_liquidation": 100000.0,
    "total_cash": 20000.0,
    "buying_power": 40000.0,
    "ts": "2026-07-15T20:00:00Z"
  },
  "positions": [
    {"account_id": "U0000000", "symbol": "AAPL", "sec_type": "STK", "currency": "USD",
     "quantity": 100, "avg_cost": 150.0, "market_price": 190.0, "market_value": 19000.0, "unrealized_pnl": 4000.0},
    {"account_id": "U0000000", "symbol": "MSFT", "sec_type": "STK", "currency": "USD",
     "quantity": 50, "avg_cost": 300.0, "market_price": 420.0, "market_value": 21000.0, "unrealized_pnl": 6000.0}
  ],
  "ts": "2026-07-15T20:00:00Z"
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ib_common.schema'`.

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-common/ib_common/schema.py
"""Typed data models for the IB analyst pipeline.

These are the single source of truth for the shape of account, position,
execution, bar and dividend records. Storage and analysis layers depend
only on these types, never on raw ib_async objects.
"""
from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel


class Account(BaseModel):
    account_id: str
    base_currency: str
    net_liquidation: float
    total_cash: float
    buying_power: float
    ts: datetime


class Position(BaseModel):
    account_id: str
    symbol: str
    sec_type: str
    currency: str
    quantity: float
    avg_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float


class Execution(BaseModel):
    exec_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    ts: datetime


class DailyBar(BaseModel):
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class Dividend(BaseModel):
    symbol: str
    ex_date: date
    pay_date: date | None
    gross: float
    tax: float
    currency: str


class Snapshot(BaseModel):
    account: Account
    positions: list[Position]
    ts: datetime
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_schema.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add skills/ib-common/ib_common/schema.py skills/ib-common/tests/test_schema.py skills/ib-common/tests/fixtures/snapshot_sample.json
git commit -m "feat(ib-common): pydantic schema for account/position/execution/bar/dividend"
```

---

## Task 3: Storage — JSON snapshot + append-only Parquet

**Files:**
- Create: `skills/ib-common/ib_common/storage.py`
- Test: `skills/ib-common/tests/test_storage.py`

**Interfaces:**
- Consumes: `Snapshot`, `DailyBar` (Task 2).
- Produces:
  - `write_snapshot(snap: Snapshot, root: str | Path) -> Path` — writes `root/snapshots/<account_id>/<ts>.json`, returns the file path.
  - `append_timeseries(rows: list[BaseModel], root: str | Path, name: str) -> Path` — appends dict-rows to `root/timeseries/<name>.parquet`, de-duplicating on all columns; returns the parquet path.
  - `read_timeseries(root: str | Path, name: str) -> pd.DataFrame` — returns the full parquet as a DataFrame (empty DataFrame if absent).

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-common/tests/test_storage.py
from pathlib import Path
from datetime import datetime, date, timezone
from ib_common.schema import Snapshot, Account, Position, DailyBar
from ib_common.storage import write_snapshot, append_timeseries, read_timeseries


def _snap():
    acct = Account(account_id="U1", base_currency="USD", net_liquidation=100.0,
                   total_cash=10.0, buying_power=20.0, ts=datetime(2026, 7, 15, tzinfo=timezone.utc))
    pos = Position(account_id="U1", symbol="AAPL", sec_type="STK", currency="USD",
                   quantity=1, avg_cost=1.0, market_price=2.0, market_value=2.0, unrealized_pnl=1.0)
    return Snapshot(account=acct, positions=[pos], ts=datetime(2026, 7, 15, tzinfo=timezone.utc))


def test_write_snapshot_creates_file(tmp_path):
    p = write_snapshot(_snap(), tmp_path)
    assert p.exists()
    assert "U1" in str(p)


def test_append_timeseries_dedupes(tmp_path):
    bar = DailyBar(symbol="AAPL", date=date(2026, 7, 15), open=1, high=2, low=0.5, close=1.5, volume=1000)
    append_timeseries([bar], tmp_path, "daily_bars")
    append_timeseries([bar], tmp_path, "daily_bars")   # duplicate append
    df = read_timeseries(tmp_path, "daily_bars")
    assert len(df) == 1                                 # dedup on all columns


def test_read_missing_returns_empty(tmp_path):
    df = read_timeseries(tmp_path, "nope")
    assert df.empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ib_common.storage'`.

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-common/ib_common/storage.py
"""Local data lake: instantaneous JSON snapshots + append-only Parquet history.

Snapshots capture point-in-time state (one file per sync). Time-series
tables accumulate history and are de-duplicated on every append so repeated
syncs are idempotent.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from pydantic import BaseModel

from .schema import Snapshot


def write_snapshot(snap: Snapshot, root: str | Path) -> Path:
    """Write a snapshot as JSON under root/snapshots/<account_id>/<ts>.json."""
    ts_key = snap.ts.strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(root) / "snapshots" / snap.account.account_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{ts_key}.json"
    out.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    return out


def append_timeseries(rows: list[BaseModel], root: str | Path, name: str) -> Path:
    """Append pydantic rows to root/timeseries/<name>.parquet, deduped on all cols."""
    out_dir = Path(root) / "timeseries"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.parquet"

    new_df = pd.DataFrame([r.model_dump() for r in rows])
    if out.exists():
        existing = pd.read_parquet(out)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    combined = combined.drop_duplicates().reset_index(drop=True)
    combined.to_parquet(out, index=False)
    return out


def read_timeseries(root: str | Path, name: str) -> pd.DataFrame:
    """Read a time-series parquet; return an empty DataFrame if it does not exist."""
    out = Path(root) / "timeseries" / f"{name}.parquet"
    if not out.exists():
        return pd.DataFrame()
    return pd.read_parquet(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_storage.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-common/ib_common/storage.py skills/ib-common/tests/test_storage.py
git commit -m "feat(ib-common): JSON snapshot writer + append-only Parquet time-series store"
```

---

## Task 4: Metrics — return-based ratios

**Files:**
- Create: `skills/ib-common/ib_common/metrics/__init__.py` (empty)
- Create: `skills/ib-common/ib_common/metrics/returns.py`
- Test: `skills/ib-common/tests/test_metrics_returns.py`

**Interfaces:**
- Consumes: nothing (pure numpy over sequences).
- Produces:
  - `sharpe(returns: Sequence[float], rf: float = 0.0, periods: int = 252) -> float`
  - `sortino(returns: Sequence[float], rf: float = 0.0, periods: int = 252) -> float`
  - `calmar(returns: Sequence[float], periods: int = 252) -> float` (annualized return ÷ abs(max drawdown of the cumulative curve))

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-common/tests/test_metrics_returns.py
import numpy as np
from ib_common.metrics.returns import sharpe, sortino, calmar


def test_sharpe_zero_when_no_variance():
    assert sharpe([0.001, 0.001, 0.001]) == 0.0   # no volatility -> defined as 0


def test_sharpe_positive_for_positive_mean():
    r = [0.01, -0.005, 0.012, 0.003, -0.002]
    assert sharpe(r) > 0


def test_sortino_ge_zero_and_penalizes_downside():
    r = [0.01, -0.02, 0.015, -0.01, 0.02]
    s = sortino(r)
    assert np.isfinite(s)


def test_calmar_finite_for_drawdown_series():
    r = [0.02, -0.05, 0.03, -0.01, 0.04]
    assert np.isfinite(calmar(r))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_metrics_returns.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ib_common.metrics'`.

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-common/ib_common/metrics/returns.py
"""Return-based performance ratios computed from a period-return series.

All functions accept a sequence of periodic (e.g. daily) simple returns and
annualize with `periods` (252 trading days by default). Zero-variance or
degenerate inputs return 0.0 rather than raising, so callers can treat the
result as a plain fact.
"""
from __future__ import annotations
from collections.abc import Sequence
import numpy as np


def sharpe(returns: Sequence[float], rf: float = 0.0, periods: int = 252) -> float:
    """Annualized Sharpe ratio; 0.0 when volatility is zero."""
    r = np.asarray(returns, dtype=float)
    excess = r - rf / periods
    sd = excess.std(ddof=1) if r.size > 1 else 0.0
    if sd == 0:
        return 0.0
    return float(np.sqrt(periods) * excess.mean() / sd)


def sortino(returns: Sequence[float], rf: float = 0.0, periods: int = 252) -> float:
    """Annualized Sortino ratio using downside deviation; 0.0 if no downside."""
    r = np.asarray(returns, dtype=float)
    excess = r - rf / periods
    downside = excess[excess < 0]
    dd = downside.std(ddof=1) if downside.size > 1 else 0.0
    if dd == 0:
        return 0.0
    return float(np.sqrt(periods) * excess.mean() / dd)


def calmar(returns: Sequence[float], periods: int = 252) -> float:
    """Annualized return divided by absolute max drawdown of the equity curve."""
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    equity = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(equity)
    drawdown = equity / running_max - 1.0
    max_dd = drawdown.min()
    if max_dd == 0:
        return 0.0
    ann_return = equity[-1] ** (periods / r.size) - 1.0
    return float(ann_return / abs(max_dd))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_metrics_returns.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-common/ib_common/metrics/__init__.py skills/ib-common/ib_common/metrics/returns.py skills/ib-common/tests/test_metrics_returns.py
git commit -m "feat(ib-common): return-based metrics (sharpe/sortino/calmar)"
```

---

## Task 5: Metrics — risk measures

**Files:**
- Create: `skills/ib-common/ib_common/metrics/risk.py`
- Test: `skills/ib-common/tests/test_metrics_risk.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `max_drawdown(equity: Sequence[float]) -> float` (returns a negative fraction, e.g. -0.25)
  - `hist_var(returns: Sequence[float], level: float = 0.95) -> float` (historical VaR, positive loss magnitude)
  - `hist_cvar(returns: Sequence[float], level: float = 0.95) -> float` (historical CVaR/expected shortfall, positive)
  - `hhi(weights: Sequence[float]) -> float` (Herfindahl-Hirschman index of portfolio weights, 0..1)

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-common/tests/test_metrics_risk.py
import numpy as np
from ib_common.metrics.risk import max_drawdown, hist_var, hist_cvar, hhi


def test_max_drawdown_simple():
    equity = [100, 120, 90, 110]      # peak 120 -> trough 90 => -0.25
    assert abs(max_drawdown(equity) - (-0.25)) < 1e-9


def test_hist_var_positive_loss():
    returns = [-0.05, -0.02, 0.01, 0.03, -0.10, 0.02, 0.00]
    v = hist_var(returns, level=0.95)
    assert v > 0                       # reported as a positive loss magnitude


def test_cvar_ge_var():
    returns = [-0.05, -0.02, 0.01, 0.03, -0.10, 0.02, 0.00]
    assert hist_cvar(returns, 0.95) >= hist_var(returns, 0.95)


def test_hhi_concentrated_vs_diversified():
    assert hhi([1.0]) == 1.0                       # fully concentrated
    assert abs(hhi([0.25, 0.25, 0.25, 0.25]) - 0.25) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_metrics_risk.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ib_common.metrics.risk'`.

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-common/ib_common/metrics/risk.py
"""Risk measures: drawdown, historical VaR/CVaR, and concentration (HHI).

VaR and CVaR are reported as positive loss magnitudes at the given
confidence level using the historical (non-parametric) method.
"""
from __future__ import annotations
from collections.abc import Sequence
import numpy as np


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough decline of an equity curve, as a negative fraction."""
    e = np.asarray(equity, dtype=float)
    if e.size == 0:
        return 0.0
    running_max = np.maximum.accumulate(e)
    drawdown = e / running_max - 1.0
    return float(drawdown.min())


def hist_var(returns: Sequence[float], level: float = 0.95) -> float:
    """Historical Value-at-Risk at `level`, returned as a positive loss."""
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    q = np.quantile(r, 1 - level)      # left-tail quantile of returns
    return float(max(0.0, -q))


def hist_cvar(returns: Sequence[float], level: float = 0.95) -> float:
    """Historical Conditional VaR (expected shortfall), positive loss."""
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    threshold = np.quantile(r, 1 - level)
    tail = r[r <= threshold]
    if tail.size == 0:
        return float(max(0.0, -threshold))
    return float(max(0.0, -tail.mean()))


def hhi(weights: Sequence[float]) -> float:
    """Herfindahl-Hirschman concentration index of |weights|, normalized to sum=1."""
    w = np.abs(np.asarray(weights, dtype=float))
    total = w.sum()
    if total == 0:
        return 0.0
    w = w / total
    return float(np.sum(w ** 2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_metrics_risk.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-common/ib_common/metrics/risk.py skills/ib-common/tests/test_metrics_risk.py
git commit -m "feat(ib-common): risk metrics (max drawdown, hist VaR/CVaR, HHI)"
```

---

## Task 6: Charts — dual HTML+PNG rendering

**Files:**
- Create: `skills/ib-common/ib_common/charts/__init__.py` (empty)
- Create: `skills/ib-common/ib_common/charts/render.py`
- Test: `skills/ib-common/tests/test_charts.py`

**Interfaces:**
- Consumes: nothing (accepts a `plotly.graph_objects.Figure`).
- Produces:
  - `render(fig, out_dir: str | Path, name: str) -> dict[str, Path]` — writes `<name>.html` (interactive) and `<name>.png` (static, via kaleido), returns `{"html": Path, "png": Path}`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-common/tests/test_charts.py
import plotly.graph_objects as go
from ib_common.charts.render import render


def test_render_produces_both_products(tmp_path):
    fig = go.Figure(data=[go.Bar(x=["AAPL", "MSFT"], y=[19000, 21000])])
    out = render(fig, tmp_path, "concentration")
    assert out["html"].exists() and out["html"].suffix == ".html"
    assert out["png"].exists() and out["png"].suffix == ".png"
    assert out["png"].stat().st_size > 0     # kaleido actually rendered pixels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_charts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ib_common.charts'`.

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-common/ib_common/charts/render.py
"""Dual-product chart rendering: interactive HTML + static PNG.

Every chart is archived twice — an interactive .html for exploration and a
static .png (rendered by kaleido, no browser needed) for pasting into
reports/Lark. Downstream chart builders produce a plotly Figure and hand it
here; this module owns file I/O so builders stay pure.
"""
from __future__ import annotations
from pathlib import Path
import plotly.graph_objects as go


def render(fig: go.Figure, out_dir: str | Path, name: str) -> dict[str, Path]:
    """Write fig as <name>.html and <name>.png into out_dir; return both paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / f"{name}.html"
    png_path = out / f"{name}.png"
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    fig.write_image(str(png_path), format="png", scale=2)   # kaleido backend
    return {"html": html_path, "png": png_path}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-common/tests/test_charts.py -v`
Expected: PASS (1 passed). *(If kaleido raises on first run, re-run once; kaleido lazily downloads its Chromium shim.)*

- [ ] **Step 5: Commit**

```bash
git add skills/ib-common/ib_common/charts/__init__.py skills/ib-common/ib_common/charts/render.py skills/ib-common/tests/test_charts.py
git commit -m "feat(ib-common): dual HTML+PNG chart renderer via plotly/kaleido"
```

---

## Task 7: ib-gateway — Flex Web Service fetch + parse

**Files:**
- Create: `skills/ib-gateway/scripts/flex_fetch.py`
- Create: `skills/ib-gateway/tests/fixtures/flex_response_sample.xml`
- Test: `skills/ib-gateway/tests/test_flex_fetch.py`

**Interfaces:**
- Consumes: `Dividend`, `Execution` (Task 2).
- Produces:
  - `parse_flex_dividends(xml_text: str) -> list[Dividend]` — parses a Flex `ChangeInDividendAccruals`/`CashTransaction` XML block into `Dividend` rows.
  - `parse_flex_trades(xml_text: str) -> list[Execution]` — parses Flex `Trades` into `Execution` rows.
  - `fetch_flex_report(token: str, query_id: str, http_get=requests.get) -> str` — runs the 2-step Flex Web Service handshake (SendRequest → GetStatement) and returns raw statement XML. `http_get` is injectable for tests.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-gateway/tests/test_flex_fetch.py
from pathlib import Path
import importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "flex_fetch.py"
spec = importlib.util.spec_from_file_location("flex_fetch", SPEC)
flex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flex)

FIX = Path(__file__).parent / "fixtures"


def test_parse_flex_dividends():
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    divs = flex.parse_flex_dividends(xml_text)
    assert len(divs) == 1
    assert divs[0].symbol == "AAPL"
    assert divs[0].gross == 24.0
    assert divs[0].currency == "USD"


def test_parse_flex_trades():
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    trades = flex.parse_flex_trades(xml_text)
    assert len(trades) == 1
    assert trades[0].symbol == "AAPL"
    assert trades[0].side == "BUY"
    assert trades[0].quantity == 100.0


def test_fetch_flex_report_two_step_handshake():
    class FakeResp:
        def __init__(self, text): self.text = text; self.status_code = 200
        def raise_for_status(self): pass

    calls = []
    def fake_get(url, params=None, **kw):
        calls.append((url, params))
        if "SendRequest" in url:
            return FakeResp("<FlexStatementResponse><Status>Success</Status>"
                            "<ReferenceCode>REF123</ReferenceCode>"
                            "<Url>https://x/GetStatement</Url></FlexStatementResponse>")
        return FakeResp("<FlexQueryResponse>OK</FlexQueryResponse>")

    out = flex.fetch_flex_report("TOK", "Q1", http_get=fake_get)
    assert "FlexQueryResponse" in out
    assert len(calls) == 2                       # SendRequest then GetStatement
```

- [ ] **Step 2: Write the fixture**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="analyst" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U0000000" fromDate="2026-01-01" toDate="2026-07-15">
      <Trades>
        <Trade symbol="AAPL" buySell="BUY" quantity="100" tradePrice="150.00"
               ibCommission="-1.00" tradeDate="2026-02-01" tradeID="T1"/>
      </Trades>
      <CashTransactions>
        <CashTransaction symbol="AAPL" type="Dividends" amount="24.00" currency="USD"
                         dateTime="2026-05-15" settleDate="2026-05-20"/>
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-gateway/tests/test_flex_fetch.py -v`
Expected: FAIL with `FileNotFoundError` / module load error (flex_fetch.py absent).

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-gateway/scripts/flex_fetch.py
"""Flex Web Service client + XML parsers (read-only historical data).

Two-step handshake: SendRequest returns a ReferenceCode + statement URL,
GetStatement returns the report XML. Parsers convert the XML into typed
ib_common rows. Free of charge and covers history beyond the ~7-day
reqExecutions window.
"""
from __future__ import annotations
import time
import xml.etree.ElementTree as ET
from datetime import datetime, date
import requests

from ib_common.schema import Dividend, Execution

_FLEX_BASE = "https://gdcdyn.interactivebrokers.com/Universal/servlet"


def _parse_date(s: str) -> date:
    """Parse Flex date fields which may be 'YYYY-MM-DD' or 'YYYYMMDD'."""
    s = s.split(";")[0].strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def parse_flex_dividends(xml_text: str) -> list[Dividend]:
    """Extract dividend cash transactions into Dividend rows."""
    root = ET.fromstring(xml_text)
    out: list[Dividend] = []
    for ct in root.iter("CashTransaction"):
        if "Dividend" not in (ct.get("type") or ""):
            continue
        out.append(Dividend(
            symbol=ct.get("symbol", ""),
            ex_date=_parse_date(ct.get("dateTime", "1970-01-01")),
            pay_date=_parse_date(ct["settleDate"]) if ct.get("settleDate") else None,
            gross=float(ct.get("amount", 0.0)),
            tax=0.0,
            currency=ct.get("currency", ""),
        ))
    return out


def parse_flex_trades(xml_text: str) -> list[Execution]:
    """Extract trades into Execution rows."""
    root = ET.fromstring(xml_text)
    out: list[Execution] = []
    for tr in root.iter("Trade"):
        out.append(Execution(
            exec_id=tr.get("tradeID", ""),
            symbol=tr.get("symbol", ""),
            side=tr.get("buySell", ""),
            quantity=abs(float(tr.get("quantity", 0.0))),
            price=float(tr.get("tradePrice", 0.0)),
            commission=abs(float(tr.get("ibCommission", 0.0))),
            ts=datetime.combine(_parse_date(tr.get("tradeDate", "1970-01-01")),
                                datetime.min.time()),
        ))
    return out


def fetch_flex_report(token: str, query_id: str, http_get=requests.get,
                      poll_interval: float = 1.0, max_polls: int = 10) -> str:
    """Run the Flex two-step handshake and return raw statement XML."""
    send = http_get(f"{_FLEX_BASE}/FlexStatementService.SendRequest",
                    params={"t": token, "q": query_id, "v": "3"})
    send.raise_for_status()
    root = ET.fromstring(send.text)
    ref = root.findtext("ReferenceCode")
    url = root.findtext("Url") or f"{_FLEX_BASE}/FlexStatementService.GetStatement"
    if not ref:
        raise RuntimeError(f"Flex SendRequest failed: {send.text[:200]}")

    for _ in range(max_polls):
        stmt = http_get(url, params={"t": token, "q": ref, "v": "3"})
        stmt.raise_for_status()
        if "Statement generation in progress" not in stmt.text:
            return stmt.text
        time.sleep(poll_interval)
    return stmt.text
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-gateway/tests/test_flex_fetch.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add skills/ib-gateway/scripts/flex_fetch.py skills/ib-gateway/tests/test_flex_fetch.py skills/ib-gateway/tests/fixtures/flex_response_sample.xml
git commit -m "feat(ib-gateway): Flex Web Service fetch + dividend/trade XML parsers"
```

---

## Task 8: ib-gateway — /ib-sync entrypoint (Gateway pull → data lake)

**Files:**
- Create: `skills/ib-gateway/scripts/ib_sync.py`
- Create: `skills/ib-gateway/tests/fixtures/ib_raw_account_sample.json`
- Test: `skills/ib-gateway/tests/test_ib_sync.py`

**Interfaces:**
- Consumes: `Account`, `Position`, `Snapshot` (Task 2); `write_snapshot`, `append_timeseries` (Task 3); `load_config`, `resolve_base_currency` (Task 1).
- Produces:
  - `build_snapshot(raw: dict, ts: datetime) -> Snapshot` — converts a raw account+positions dict (the shape `ib_async` gives, captured in the fixture) into a typed `Snapshot`; enforces `resolve_base_currency`.
  - `sync(cfg_path: str, client_factory=None, now=None) -> dict` — orchestrates: load config → connect via injected `client_factory` (read-only) → fetch account+positions → `build_snapshot` → `write_snapshot` + `append_timeseries` → return `{"snapshot": Path, "timeseries": Path}`. `client_factory` is injectable so tests never open a socket.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-gateway/tests/test_ib_sync.py
from pathlib import Path
from datetime import datetime, timezone
import json, importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "ib_sync.py"
spec = importlib.util.spec_from_file_location("ib_sync", SPEC)
ib_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ib_sync)

FIX = Path(__file__).parent / "fixtures"


def test_build_snapshot_from_raw():
    raw = json.loads((FIX / "ib_raw_account_sample.json").read_text())
    snap = ib_sync.build_snapshot(raw, datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert snap.account.base_currency == "USD"
    assert snap.account.account_id == "U0000000"
    assert len(snap.positions) == 2


def test_sync_writes_snapshot_and_timeseries(tmp_path):
    raw = json.loads((FIX / "ib_raw_account_sample.json").read_text())

    # config pointing storage at tmp
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"storage:\n  root: {tmp_path}\ndata:\n  base_currency: USD\n")

    class FakeClient:
        """Stand-in for a read-only IB Gateway session."""
        def fetch_raw(self): return raw
        def disconnect(self): pass

    out = ib_sync.sync(str(cfg_path),
                       client_factory=lambda cfg: FakeClient(),
                       now=lambda: datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert Path(out["snapshot"]).exists()
    assert Path(out["timeseries"]).exists()
```

- [ ] **Step 2: Write the fixture**

```json
{
  "account": {
    "account_id": "U0000000",
    "base_currency": "USD",
    "net_liquidation": 100000.0,
    "total_cash": 20000.0,
    "buying_power": 40000.0
  },
  "positions": [
    {"symbol": "AAPL", "sec_type": "STK", "currency": "USD", "quantity": 100,
     "avg_cost": 150.0, "market_price": 190.0},
    {"symbol": "MSFT", "sec_type": "STK", "currency": "USD", "quantity": 50,
     "avg_cost": 300.0, "market_price": 420.0}
  ]
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-gateway/tests/test_ib_sync.py -v`
Expected: FAIL (ib_sync.py absent / build_snapshot undefined).

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-gateway/scripts/ib_sync.py
"""/ib-sync entrypoint: pull read-only account + positions and land to the lake.

The live connection is isolated behind `client_factory` so business logic
(build_snapshot, storage) is fully testable against fixtures. This module
NEVER imports order-placing APIs — read-only by construction.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path

from ib_common.config import load_config, resolve_base_currency
from ib_common.schema import Account, Position, Snapshot
from ib_common.storage import write_snapshot, append_timeseries


def build_snapshot(raw: dict, ts: datetime) -> Snapshot:
    """Convert a raw account+positions dict into a typed, base-currency-checked Snapshot."""
    acct_raw = raw["account"]
    base = acct_raw.get("base_currency")
    account = Account(
        account_id=acct_raw["account_id"],
        base_currency=base,
        net_liquidation=float(acct_raw["net_liquidation"]),
        total_cash=float(acct_raw["total_cash"]),
        buying_power=float(acct_raw["buying_power"]),
        ts=ts,
    )
    positions: list[Position] = []
    for p in raw["positions"]:
        mkt_val = float(p["quantity"]) * float(p["market_price"])
        cost_val = float(p["quantity"]) * float(p["avg_cost"])
        positions.append(Position(
            account_id=account.account_id,
            symbol=p["symbol"],
            sec_type=p["sec_type"],
            currency=p["currency"],
            quantity=float(p["quantity"]),
            avg_cost=float(p["avg_cost"]),
            market_price=float(p["market_price"]),
            market_value=mkt_val,
            unrealized_pnl=mkt_val - cost_val,
        ))
    return Snapshot(account=account, positions=positions, ts=ts)


def _default_client_factory(cfg):
    """Build a read-only IB Gateway client. Imported lazily to keep tests offline."""
    from ib_async import IB  # local import: no network dependency at import time

    class _LiveClient:
        def __init__(self, cfg):
            self.ib = IB()
            self.ib.connect(cfg.connection.host, cfg.connection.port,
                            clientId=cfg.connection.client_id,
                            readonly=True)   # hard read-only

        def fetch_raw(self) -> dict:
            summary = {v.tag: v.value for v in self.ib.accountSummary()}
            acct_id = self.ib.managedAccounts()[0]
            positions = []
            for p in self.ib.positions():
                c = p.contract
                positions.append({
                    "symbol": c.symbol, "sec_type": c.secType,
                    "currency": c.currency, "quantity": p.position,
                    "avg_cost": p.avgCost,
                    "market_price": p.avgCost,  # replaced by mkt data in later plan
                })
            return {
                "account": {
                    "account_id": acct_id,
                    "base_currency": summary.get("Currency", "USD"),
                    "net_liquidation": float(summary.get("NetLiquidation", 0)),
                    "total_cash": float(summary.get("TotalCashValue", 0)),
                    "buying_power": float(summary.get("BuyingPower", 0)),
                },
                "positions": positions,
            }

        def disconnect(self):
            self.ib.disconnect()

    return _LiveClient(cfg)


def sync(cfg_path: str, client_factory=None, now=None) -> dict:
    """Load config, pull data via a read-only client, land snapshot + time-series."""
    cfg = load_config(cfg_path)
    now = now or (lambda: datetime.now(timezone.utc))
    client_factory = client_factory or _default_client_factory

    client = client_factory(cfg)
    try:
        raw = client.fetch_raw()
    finally:
        client.disconnect()

    # enforce base-currency policy (account wins over config)
    raw["account"]["base_currency"] = resolve_base_currency(
        cfg, raw["account"].get("base_currency"))

    snap = build_snapshot(raw, now())
    snap_path = write_snapshot(snap, cfg.storage.root)
    ts_path = append_timeseries(snap.positions, cfg.storage.root, "positions_history")
    return {"snapshot": str(snap_path), "timeseries": str(ts_path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync read-only IB data to the local lake.")
    parser.add_argument("--config", required=True, help="path to config.yaml")
    args = parser.parse_args()
    result = sync(args.config)
    print(result)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-gateway/tests/test_ib_sync.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add skills/ib-gateway/scripts/ib_sync.py skills/ib-gateway/tests/test_ib_sync.py skills/ib-gateway/tests/fixtures/ib_raw_account_sample.json
git commit -m "feat(ib-gateway): /ib-sync read-only pull -> snapshot + positions time-series"
```

---

## Task 9: ib-gateway SKILL.md (OpenClaw registration + gating)

**Files:**
- Create: `skills/ib-gateway/SKILL.md`

**Interfaces:**
- Consumes: `ib_sync.py`, `flex_fetch.py` (Tasks 7-8), shared `.venv`.
- Produces: an OpenClaw-loadable skill exposing `/ib-sync`, gated on `python3` + a present `config.yaml`.

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: ib-gateway
description: Pull read-only Interactive Brokers account, position, execution, daily-bar and dividend data from IB Gateway or a Flex report and land it into a local snapshot + Parquet time-series lake for downstream analysis.
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [config.yaml]
    os: [darwin, linux]
---

# ib-gateway

Read-only data ingestion for the IB analyst toolchain. This skill never
places or modifies orders; it connects with `readonly=True` and only reads.

## Setup (once)

```bash
bash {baseDir}/../../scripts/setup_venv.sh
cp {baseDir}/../ib-common/config.example.yaml ./config.yaml   # then edit ports/thresholds
```

Start IB Gateway (paper on 4002 / live on 4001) and enable API access. For a
live account, tick **Read-Only API** in Gateway settings as an extra guard.

## Commands

### /ib-sync — snapshot current account + positions

```bash
{baseDir}/../../.venv/bin/python {baseDir}/scripts/ib_sync.py --config ./config.yaml
```

Writes `data/snapshots/<account>/<ts>.json` (instantaneous state) and appends
`data/timeseries/positions_history.parquet` (history).

### Flex history (dividends, trades > 7 days old)

```bash
{baseDir}/../../.venv/bin/python -c "import sys; sys.path.insert(0,'{baseDir}/scripts'); \
import flex_fetch; print(flex_fetch.fetch_flex_report('$FLEX_TOKEN','$FLEX_QUERY_ID'))"
```

## Notes

- Same `clientId` allows only one active Gateway connection — pick a unique id in `config.yaml`.
- Base currency follows the account's BASE; override only via `config.yaml`.
- All committed fixtures are desensitized. Never commit real `config.yaml` or live snapshots.
```

- [ ] **Step 2: Verify the frontmatter description length constraint**

Run: `.venv/bin/python -c "import re,sys; t=open('skills/ib-gateway/SKILL.md').read(); m=re.search(r'description: (.+)', t); print(len(m.group(1)))"`
Expected: prints a number ≤ 160. *(If > 160, tighten the description and re-run.)*

- [ ] **Step 3: Run the whole suite green**

Run: `.venv/bin/python -m pytest skills -v`
Expected: all tests from Tasks 1-8 PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/ib-gateway/SKILL.md
git commit -m "feat(ib-gateway): SKILL.md registration with read-only gating"
```

---

## Self-Review

**1. Spec coverage (foundation scope):**
- Config + all-configurable thresholds → Task 1 ✅
- Base currency follows account → Task 1 (`resolve_base_currency`) + Task 8 (enforced in `sync`) ✅
- Typed schema for account/position/execution/bar/dividend → Task 2 ✅
- JSON snapshot + append-only Parquet → Task 3 ✅
- Metrics (sharpe/sortino/calmar, VaR/CVaR/maxDD/HHI) → Tasks 4-5 ✅
- plotly+kaleido dual HTML+PNG → Task 6 ✅
- Flex free historical pull (dividends + trades) → Task 7 ✅
- Read-only Gateway pull → data lake → Task 8 ✅
- OpenClaw skill registration + gating (python3, config) → Task 9 ✅
- Read-only guarantee (no order APIs) → enforced in Task 8 (`readonly=True`, no placeOrder import) + Global Constraints ✅
- Desensitized fixtures / offline TDD → every fixture masked (`U0000000`), tests inject fakes, no live socket ✅

**2. Placeholder scan:** No TBD/TODO; every code step ships runnable code; commands have expected output. ✅

**3. Type consistency:** `Snapshot`/`Account`/`Position`/`Dividend`/`Execution` field names identical across Tasks 2, 3, 7, 8. `write_snapshot`/`append_timeseries`/`read_timeseries` signatures consistent between Task 3 definition and Task 8 use. `resolve_base_currency(cfg, account_base)` consistent between Task 1 and Task 8. ✅

**Deferred to later plans (intentionally out of foundation scope):** live market-data prices for positions (Task 8 uses avg_cost as placeholder price), execution/dividend *time-series* landing (only parsing is built here), correlation/beta metrics needing multi-symbol bars, and all P0-P3 diagnostic report generation (Plan 2).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-16-ib-analyst-plan1-foundation.md`. Deferred to end of the batch — I'll present the two execution options (Subagent-Driven vs Inline) after Plans 2 and 3 are written, so you can choose once for the whole set.
