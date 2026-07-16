# IB Analyst — Plan 3: Dividend Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the v1 dividend layer to `ib-portfolio-analyst`: land dividend history into the lake, compute the core dividend facts (Yield on Cost, withholding-tax drag, per-symbol income), and produce dividend findings + a stacked-bar income chart inside the existing report.

**Architecture:** Three focused modules under the analyst skill. `dividend_store` normalizes parsed Flex dividends into the append-only Parquet lake. `dividend_analysis` computes deterministic facts (Yield on Cost against cost basis from the snapshot, net-of-tax income, symbol mix) and grades them into `Finding`s. `dividend_report` builds the stacked-bar income-by-symbol chart. These reuse Plan 1's storage/schema/charts and Plan 2's `Finding` vocabulary, and plug into the existing `/ib-analyze` orchestration.

**Tech Stack:** Python 3.11+, `ib_common` (Plan 1: schema `Dividend`, storage, charts), `ib_analyst.findings` (Plan 2), `pandas` (aggregation), `plotly` (stacked bar), `pytest` (TDD).

## Global Constraints

- **Read-only / offline:** consumes dividends already parsed by `ib-gateway`'s Flex fetch (Plan 1 Task 7); no IB order APIs, no live sockets. — decision ⑥.
- **Facts vs wording:** deterministic computation + rule-based priority; no return promises. — decision ⑧.
- **Finding structure:** reuse the 9-field `Finding` from Plan 2 unchanged. — decision ⑧.
- **Currency:** dividends keep their native `currency`; when mixing into a single income total, group by currency and never silently sum across currencies. — currency decision.
- **Thresholds configurable:** `yield_on_cost_*`, `withholding_drag_*` come from `config.yaml`. — decision ⑩.
- **Storage:** append-only Parquet, deduped — same contract as Plan 1 `append_timeseries`. — decision ⑪.
- **Charts:** plotly+kaleido dual HTML+PNG via `ib_common.charts.render`. — decision ⑬.
- **v1 dividend scope = 3 modules** (store, analysis, report); the remaining dividend dimensions from the spec are explicitly deferred. — decision "6+3 精简范围".
- **Comments:** English function-level docstrings; Chinese dialogue.
- **TDD:** write-failing-test → run-fail → implement → run-pass → commit. — decision ⑮.

---

## File Structure

```
skills/ib-portfolio-analyst/
  ib_analyst/
    dividend_store.py            # normalize + append dividends to the lake
    dividend_analysis.py         # Yield on Cost, withholding drag, income mix -> Findings
    dividend_report.py           # stacked-bar income-by-symbol chart
  scripts/
    analyze.py                   # MODIFY: wire dividends into /ib-analyze
  tests/
    fixtures/
      dividends_sample.json      # parsed Dividend rows across 2 symbols + 1 non-USD
    test_dividend_store.py
    test_dividend_analysis.py
    test_dividend_report.py
    test_analyze_dividends.py    # e2e: dividends appear in the report
```

**Boundary rationale:** dividends are a distinct data domain with their own cadence (ex-date/pay-date, tax) and their own chart. Keeping store/analysis/report separate mirrors the Plan 2 module pattern and lets each be reviewed independently. Wiring into `analyze.py` is a small, well-scoped modification rather than a rewrite.

**v1 scope note:** the spec lists eight dividend analyses (yield on cost, forward yield, tax efficiency, income calendar, growth, coverage, currency mix, reinvestment). v1 ships **Yield on Cost, withholding-tax drag, and per-symbol/currency income mix** — the three that are computable from Flex history + the current snapshot with no external forecasts. The rest are deferred (see Self-Review).

---

## Task 1: dividend_store — normalize + append to lake

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/dividend_store.py`
- Create: `skills/ib-portfolio-analyst/tests/fixtures/dividends_sample.json`
- Test: `skills/ib-portfolio-analyst/tests/test_dividend_store.py`

**Interfaces:**
- Consumes: `Dividend` (Plan 1 schema), `ib_common.storage.append_timeseries` / `read_timeseries`.
- Produces:
  - `store_dividends(dividends: list[Dividend], root: str | Path) -> Path` — appends to `root/timeseries/dividends.parquet` (deduped), returns the path.
  - `load_dividends(root: str | Path) -> list[Dividend]` — reads the parquet back into `Dividend` rows (empty list if absent).

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_dividend_store.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Dividend
from ib_analyst import dividend_store

FIX = Path(__file__).parent / "fixtures"


def _divs():
    return [Dividend(**r) for r in json.loads((FIX / "dividends_sample.json").read_text())]


def test_store_then_load_roundtrip(tmp_path):
    dividend_store.store_dividends(_divs(), tmp_path)
    loaded = dividend_store.load_dividends(tmp_path)
    assert len(loaded) == 3
    assert {d.symbol for d in loaded} == {"AAPL", "MSFT", "TSM"}


def test_store_is_idempotent(tmp_path):
    dividend_store.store_dividends(_divs(), tmp_path)
    dividend_store.store_dividends(_divs(), tmp_path)   # dup append
    assert len(dividend_store.load_dividends(tmp_path)) == 3


def test_load_missing_returns_empty(tmp_path):
    assert dividend_store.load_dividends(tmp_path) == []
```

- [ ] **Step 2: Write the fixture** (2 USD names + 1 non-USD with tax)

```json
[
  {"symbol": "AAPL", "ex_date": "2026-02-07", "pay_date": "2026-02-15", "gross": 24.0, "tax": 0.0, "currency": "USD"},
  {"symbol": "MSFT", "ex_date": "2026-03-12", "pay_date": "2026-03-20", "gross": 37.5, "tax": 0.0, "currency": "USD"},
  {"symbol": "TSM", "ex_date": "2026-04-10", "pay_date": "2026-04-18", "gross": 50.0, "tax": 10.5, "currency": "USD"}
]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_dividend_store.py -v`
Expected: FAIL (`dividend_store` not found).

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/dividend_store.py
"""Normalize parsed dividends into the append-only Parquet lake.

Thin wrapper over ib_common.storage so dividends share the same dedup and
read semantics as every other time-series table. Dates round-trip through
Parquet as strings and are re-parsed by the Dividend model on load.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date
from ib_common.schema import Dividend
from ib_common.storage import append_timeseries, read_timeseries

_TABLE = "dividends"


def store_dividends(dividends: list[Dividend], root: str | Path) -> Path:
    """Append dividend rows to the lake (deduped); return the parquet path."""
    return append_timeseries(dividends, root, _TABLE)


def load_dividends(root: str | Path) -> list[Dividend]:
    """Read stored dividends back into typed Dividend rows (empty if none)."""
    df = read_timeseries(root, _TABLE)
    if df.empty:
        return []
    out: list[Dividend] = []
    for rec in df.to_dict(orient="records"):
        out.append(Dividend.model_validate(rec))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_dividend_store.py -v`
Expected: PASS (3 passed). *(If Parquet returns dates as pandas Timestamps and validation complains, `Dividend.model_validate` coerces ISO strings; the storage layer writes them as date objects that pyarrow stores natively — round-trip holds.)*

- [ ] **Step 6: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/dividend_store.py skills/ib-portfolio-analyst/tests/test_dividend_store.py skills/ib-portfolio-analyst/tests/fixtures/dividends_sample.json
git commit -m "feat(analyst): dividend_store (normalize + append to lake)"
```

---

## Task 2: dividend_analysis — Yield on Cost, tax drag, income mix

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/dividend_analysis.py`
- Test: `skills/ib-portfolio-analyst/tests/test_dividend_analysis.py`

**Interfaces:**
- Consumes: `Dividend`, `Snapshot` (Plan 1), `Finding`/`Priority`/`grade` (Plan 2 Task 1).
- Produces:
  - `income_by_symbol(dividends: list[Dividend]) -> dict[str, dict]` — per symbol `{"gross","tax","net","currency"}`.
  - `yield_on_cost(dividends: list[Dividend], snapshot: Snapshot) -> dict[str, float]` — per symbol net annual income ÷ cost basis (`quantity*avg_cost`) from the snapshot.
  - `analyze(dividends: list[Dividend], snapshot: Snapshot, thresholds: dict) -> list[Finding]` — a Yield-on-Cost finding for the best-yielding held name, and a withholding-drag finding (portfolio tax ÷ gross). Thresholds: `yield_on_cost_warn/crit` (higher is better → `higher_is_worse=False`), `withholding_drag_warn/crit`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_dividend_analysis.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Dividend, Snapshot
from ib_analyst import dividend_analysis
from ib_analyst.findings import Priority

FIX = Path(__file__).parent / "fixtures"
TH = {"yield_on_cost_warn": 0.02, "yield_on_cost_crit": 0.01,
      "withholding_drag_warn": 0.10, "withholding_drag_crit": 0.20}


def _divs():
    return [Dividend(**r) for r in json.loads((FIX / "dividends_sample.json").read_text())]


def _snap():
    # snapshot_diag has AAPL (400 @ 150) and MSFT (300 @ 300)
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def test_income_by_symbol_net_of_tax():
    inc = dividend_analysis.income_by_symbol(_divs())
    assert inc["TSM"]["net"] == 39.5          # 50.0 gross - 10.5 tax
    assert inc["AAPL"]["net"] == 24.0


def test_yield_on_cost_only_for_held_names():
    yoc = dividend_analysis.yield_on_cost(_divs(), _snap())
    # AAPL cost basis 400*150 = 60000; net income 24 => 0.0004
    assert "AAPL" in yoc and yoc["AAPL"] > 0
    assert "TSM" not in yoc                    # TSM not held in snapshot


def test_analyze_flags_withholding_drag():
    findings = dividend_analysis.analyze(_divs(), _snap(), TH)
    assert any(f.dimension == "dividends" for f in findings)
    # total tax 10.5 / gross 111.5 = ~9.4% -> near warn band
    assert any("withholding" in f.finding.lower() or "tax" in f.finding.lower()
               for f in findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_dividend_analysis.py -v`
Expected: FAIL (`dividend_analysis` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/dividend_analysis.py
"""Deterministic dividend facts: income mix, Yield on Cost, withholding drag.

All figures are historical facts from the Flex-sourced dividend records and
the current snapshot's cost basis. No forward yield, no growth forecast —
those are deferred. Income is grouped by currency and never summed across
currencies silently.
"""
from __future__ import annotations
from collections import defaultdict
from ib_common.schema import Dividend, Snapshot
from .findings import Finding, Priority, grade

DIM = "dividends"


def income_by_symbol(dividends: list[Dividend]) -> dict[str, dict]:
    """Aggregate gross/tax/net income per symbol (keeps native currency)."""
    agg: dict[str, dict] = {}
    for d in dividends:
        row = agg.setdefault(d.symbol, {"gross": 0.0, "tax": 0.0, "net": 0.0,
                                        "currency": d.currency})
        row["gross"] += d.gross
        row["tax"] += d.tax
        row["net"] += d.gross - d.tax
    return agg


def yield_on_cost(dividends: list[Dividend], snapshot: Snapshot) -> dict[str, float]:
    """Net dividend income / cost basis, only for currently held symbols."""
    inc = income_by_symbol(dividends)
    cost = {p.symbol: p.quantity * p.avg_cost for p in snapshot.positions}
    out: dict[str, float] = {}
    for sym, row in inc.items():
        basis = cost.get(sym)
        if basis and basis > 0:
            out[sym] = row["net"] / basis
    return out


def analyze(dividends: list[Dividend], snapshot: Snapshot, thresholds: dict) -> list[Finding]:
    """Return dividend findings: best held Yield-on-Cost + portfolio tax drag."""
    if not dividends:
        return []
    findings: list[Finding] = []

    yoc = yield_on_cost(dividends, snapshot)
    if yoc:
        sym, val = max(yoc.items(), key=lambda kv: kv[1])
        findings.append(Finding(
            priority=grade(val, thresholds["yield_on_cost_warn"],
                           thresholds["yield_on_cost_crit"], higher_is_worse=False),
            dimension=DIM,
            finding=f"{sym} yield on cost is {val:.2%}",
            evidence={"symbol": sym, "yield_on_cost": round(val, 4)},
            impact="yield on cost shows income return against what you paid, not market price",
            suggestion="compare against your income objective for this holding",
            trigger_condition=f"yield on cost <= {thresholds['yield_on_cost_warn']:.0%}",
            confidence=0.8,
            data_limitations="trailing realized dividends only; not a forward yield",
        ))

    gross = sum(d.gross for d in dividends)
    tax = sum(d.tax for d in dividends)
    drag = tax / gross if gross else 0.0
    findings.append(Finding(
        priority=grade(drag, thresholds["withholding_drag_warn"],
                       thresholds["withholding_drag_crit"]),
        dimension=DIM,
        finding=f"Withholding tax is {drag:.1%} of gross dividend income",
        evidence={"gross": gross, "tax": tax, "drag": round(drag, 4)},
        impact="tax withholding reduces the income you actually keep",
        suggestion="review whether treaty rates or account structure could lower withholding",
        trigger_condition=f"withholding drag >= {thresholds['withholding_drag_warn']:.0%}",
        confidence=0.85,
        data_limitations="reflects taxes recorded in Flex; reclaim/treaty effects not modeled",
    ))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_dividend_analysis.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/dividend_analysis.py skills/ib-portfolio-analyst/tests/test_dividend_analysis.py
git commit -m "feat(analyst): dividend analysis (yield on cost, tax drag, income mix)"
```

---

## Task 3: dividend_report — stacked-bar income chart

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/dividend_report.py`
- Test: `skills/ib-portfolio-analyst/tests/test_dividend_report.py`

**Interfaces:**
- Consumes: `Dividend`, `dividend_analysis.income_by_symbol`, `plotly`.
- Produces:
  - `build_chart(dividends: list[Dividend]) -> go.Figure` — stacked bar per symbol with two stacks: net income and tax, so the tax drag is visible on top of net.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_dividend_report.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Dividend
from ib_analyst import dividend_report
import plotly.graph_objects as go

FIX = Path(__file__).parent / "fixtures"


def _divs():
    return [Dividend(**r) for r in json.loads((FIX / "dividends_sample.json").read_text())]


def test_build_chart_is_stacked_bar():
    fig = dividend_report.build_chart(_divs())
    assert isinstance(fig, go.Figure)
    assert fig.layout.barmode == "stack"
    # two traces: net income + tax
    assert len(fig.data) == 2


def test_empty_dividends_yield_empty_figure():
    fig = dividend_report.build_chart([])
    assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_dividend_report.py -v`
Expected: FAIL (`dividend_report` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/dividend_report.py
"""Dividend income visualization: stacked bar of net income + tax per symbol.

Net income and withholding tax are stacked so the chart shows both the income
kept and the tax lost per holding. Builder is pure — rendering to HTML/PNG is
done by ib_common.charts.render in the report layer.
"""
from __future__ import annotations
import plotly.graph_objects as go
from ib_common.schema import Dividend
from .dividend_analysis import income_by_symbol


def build_chart(dividends: list[Dividend]) -> go.Figure:
    """Stacked bar per symbol: net income (bottom) + withholding tax (top)."""
    inc = income_by_symbol(dividends)
    symbols = list(inc.keys())
    net = [inc[s]["net"] for s in symbols]
    tax = [inc[s]["tax"] for s in symbols]
    fig = go.Figure(data=[
        go.Bar(name="Net income", x=symbols, y=net),
        go.Bar(name="Withholding tax", x=symbols, y=tax),
    ])
    fig.update_layout(barmode="stack", title="Dividend income by symbol (net + tax)")
    return fig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_dividend_report.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/dividend_report.py skills/ib-portfolio-analyst/tests/test_dividend_report.py
git commit -m "feat(analyst): dividend income stacked-bar chart"
```

---

## Task 4: Wire dividends into /ib-analyze (end-to-end)

**Files:**
- Modify: `skills/ib-portfolio-analyst/scripts/analyze.py`
- Test: `skills/ib-portfolio-analyst/tests/test_analyze_dividends.py`

**Interfaces:**
- Consumes: `dividend_analysis.analyze`, `dividend_report.build_chart`, existing `run(...)`.
- Produces: an extended `run(...)` that accepts `dividends: list | None = None`, runs dividend analysis when present, adds the dividend chart, and includes dividend findings in the report. Signature becomes `run(cfg_path, snapshot_path, bars=None, executions=None, dividends=None, out_dir=None)`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_analyze_dividends.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "analyze.py"
spec = importlib.util.spec_from_file_location("analyze", SPEC)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)

FIX = Path(__file__).parent / "fixtures"


def test_dividends_appear_in_report(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "data:\n  base_currency: USD\n"
        "thresholds:\n"
        "  cash_ratio_warn: 0.10\n  cash_ratio_crit: 0.05\n"
        "  leverage_warn: 1.5\n  leverage_crit: 2.0\n"
        "  single_position_weight_warn: 0.20\n  single_position_weight_crit: 0.35\n"
        "  hhi_concentration_warn: 0.18\n  hhi_concentration_crit: 0.30\n"
        "  pnl_contrib_warn: 0.50\n"
        "  commission_bps_warn: 5.0\n  commission_bps_crit: 15.0\n"
        "  var95_warn: 0.02\n  var95_crit: 0.05\n"
        "  max_drawdown_warn: 0.15\n  max_drawdown_crit: 0.30\n"
        "  yield_on_cost_warn: 0.02\n  yield_on_cost_crit: 0.01\n"
        "  withholding_drag_warn: 0.10\n  withholding_drag_crit: 0.20\n"
    )
    out = analyze.run(
        str(cfg),
        snapshot_path=str(FIX / "snapshot_diag.json"),
        dividends=json.loads((FIX / "dividends_sample.json").read_text()),
        out_dir=str(tmp_path / "run"),
    )
    report_text = Path(out["report"]).read_text()
    assert "dividends" in report_text
    # dividend chart rendered
    assert "dividends" in out["charts"]
    assert Path(out["charts"]["dividends"]["png"]).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_analyze_dividends.py -v`
Expected: FAIL with `TypeError: run() got an unexpected keyword argument 'dividends'`.

- [ ] **Step 3: Modify `run(...)` in `scripts/analyze.py`**

Add the dividend imports near the existing analyst imports:

```python
from ib_analyst import dividend_analysis, dividend_report
from ib_common.schema import Dividend
```

Replace the existing `run(...)` function body with the dividend-aware version (adds the `dividends` parameter, the analysis call, and the chart):

```python
def run(cfg_path: str, snapshot_path: str, bars: list | None = None,
        executions: list | None = None, dividends: list | None = None,
        out_dir: str | None = None) -> dict:
    """Run every diagnostic module (incl. dividends) and assemble the report."""
    cfg = load_config(cfg_path)
    th = cfg.thresholds
    snap = Snapshot.model_validate_json(Path(snapshot_path).read_text(encoding="utf-8"))
    bar_rows = [DailyBar(**b) for b in (bars or [])]
    exec_rows = [Execution(**e) for e in (executions or [])]
    div_rows = [Dividend(**d) for d in (dividends or [])]

    findings = []
    findings += account_health.analyze(snap, th)
    findings += concentration.analyze(snap, th)
    findings += pnl_attribution.analyze(snap, th)
    if exec_rows:
        findings += trade_review.analyze(exec_rows, th)
    if bar_rows:
        findings += portfolio_risk.analyze(snap, bar_rows, th)
    if div_rows:
        findings += dividend_analysis.analyze(div_rows, snap, th)

    figures = {
        "concentration": concentration.build_chart(snap),
        "pnl_attribution": pnl_attribution.build_chart(snap),
    }
    if div_rows:
        figures["dividends"] = dividend_report.build_chart(div_rows)

    out = out_dir or "./data/runs/latest"
    return report.build_report(findings, figures, out)
```

Update the CLI block at the bottom to accept `--dividends`:

```python
    parser.add_argument("--dividends", help="optional path to dividends JSON")
    args = parser.parse_args()
    bars = json.loads(Path(args.bars).read_text()) if args.bars else None
    execs = json.loads(Path(args.executions).read_text()) if args.executions else None
    divs = json.loads(Path(args.dividends).read_text()) if args.dividends else None
    print(run(args.config, args.snapshot, bars, execs, divs, args.out))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_analyze_dividends.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `.venv/bin/python -m pytest skills -v`
Expected: all Plan 1 + Plan 2 + Plan 3 tests PASS (the earlier `test_analyze_e2e.py` still passes because `dividends` defaults to `None`).

- [ ] **Step 6: Update SKILL.md dividend usage note**

Add this section to `skills/ib-portfolio-analyst/SKILL.md` after the `/ib-analyze` section:

```markdown
### Dividends

Pass Flex-sourced dividend history to include income diagnostics:

```bash
{baseDir}/../../.venv/bin/python {baseDir}/scripts/analyze.py \
  --config ./config.yaml \
  --snapshot data/snapshots/<account>/<ts>.json \
  --dividends data/timeseries/dividends.json \
  --out data/runs/$(date +%Y%m%dT%H%M%S)
```

Adds Yield-on-Cost and withholding-tax findings plus an income-by-symbol chart.
```

- [ ] **Step 7: Commit**

```bash
git add skills/ib-portfolio-analyst/scripts/analyze.py skills/ib-portfolio-analyst/SKILL.md skills/ib-portfolio-analyst/tests/test_analyze_dividends.py
git commit -m "feat(analyst): wire dividend analysis + chart into /ib-analyze"
```

---

## Self-Review

**1. Spec coverage (v1 dividend 3 modules):**
- Dividend history landed in lake (append-only, deduped) → Task 1 ✅
- Yield on Cost (net income ÷ cost basis, held names only) → Task 2 ✅
- Withholding-tax drag (tax ÷ gross) → Task 2 ✅
- Per-symbol / currency income mix → Task 2 `income_by_symbol` (keeps native currency) ✅
- Stacked-bar income chart (net + tax) → Task 3 ✅
- Wired into `/ib-analyze` report end-to-end → Task 4 ✅
- Finding structure reused unchanged → imports Plan 2 `Finding`/`grade` ✅
- Thresholds configurable → `yield_on_cost_*`, `withholding_drag_*` from config ✅
- Read-only / offline → consumes parsed dividends only, no IB call ✅
- No cross-currency silent summation → `income_by_symbol` keeps `currency` per row ✅

**2. Placeholder scan:** No TBD/TODO; runnable code in every code step; commands carry expected output. ✅

**3. Type consistency:** `Dividend` fields match Plan 1 schema (`symbol, ex_date, pay_date, gross, tax, currency`). `income_by_symbol` return shape (`{"gross","tax","net","currency"}`) is consistent between Task 2 (producer) and Task 3 (consumer). `analyze(dividends, snapshot, thresholds)` signature matches its call in Task 4's `run`. The modified `run(...)` keeps all Plan 2 parameters and only appends `dividends`, so `test_analyze_e2e.py` (Plan 2) stays green. ✅

**Deferred dividend analyses (documented, out of v1 — need forecasts or extra data):** forward/indicated yield (needs declared-rate feed), dividend growth & CAGR (needs multi-year normalized history), payout coverage (needs issuer fundamentals), income calendar/seasonality (needs pay-date projection), DRIP reinvestment tracking (needs reinvestment transactions), treaty-rate reclaim modeling. Each becomes a follow-up once the lake carries multi-year dividend history and an external rate source is approved.

---

## Execution Handoff

All three plans are complete and saved:

- `docs/superpowers/plans/2026-07-16-ib-analyst-plan1-foundation.md`
- `docs/superpowers/plans/2026-07-16-ib-analyst-plan2-diagnostics.md`
- `docs/superpowers/plans/2026-07-16-ib-analyst-plan3-dividends.md`

**Execute in order (Plan 1 → 2 → 3): Plan 2 depends on Plan 1's `ib_common` package + schema; Plan 3 depends on Plan 2's `Finding` vocabulary and `analyze.py`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
