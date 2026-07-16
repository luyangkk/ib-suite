# IB Analyst — Plan 2: Account Diagnostics (ib-portfolio-analyst) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `ib-portfolio-analyst` skill: six read-only diagnostic modules (account health, concentration, P&L attribution, trade review, portfolio risk, pre-trade check) that turn the Plan 1 data lake into P0–P3 structured findings plus a Markdown report with plotly/kaleido charts.

**Architecture:** Each diagnostic dimension is a pure module: `analyze(...) -> list[Finding]` computes facts and grades them via configurable thresholds; an optional `build_chart(...) -> Figure` produces the visual. A `report` layer assembles all findings into one structured Markdown document and renders every chart to HTML+PNG. The `/ib-analyze` entrypoint orchestrates: load snapshot/history from the lake → run modules → emit report. No live network, no order APIs — it reads only what Plan 1 landed.

**Tech Stack:** Python 3.11+, `ib_common` (Plan 1: schema, storage, metrics, charts), `pydantic` v2 (Finding model), `pandas`/`numpy` (computation), `plotly` (figures), `pytest` (TDD).

## Global Constraints

- **Read-only:** This skill reads the local lake only; it imports no IB order APIs and opens no sockets. — decision ⑥.
- **Facts vs wording:** Modules compute *facts* and assign priority by *rules*; LLM phrasing happens outside these deterministic functions. Every finding is diagnosis + direction only, never a return promise. — decision ⑧.
- **Finding structure:** Every finding carries `priority, dimension, finding, evidence, impact, suggestion, trigger_condition, confidence, data_limitations`. — decision ⑧.
- **Priority scale:** P0 (act now / hard risk), P1 (high), P2 (medium), P3 (info). — decision ⑧.
- **All thresholds configurable:** Every numeric cutoff comes from `config.yaml` `thresholds` with a documented default. — decision ⑩.
- **Currency base:** Weights and values use the snapshot's `account.base_currency`; never hard-code USD. — currency decision.
- **Charts:** plotly + kaleido dual HTML+PNG via `ib_common.charts.render`. — decision ⑬.
- **v1 scope:** account diagnostics 6 items; pre-trade check ships as a v1 local-simulation stub that lists the v2 WhatIf plan. — decision ⑥ + "6+3 精简范围".
- **Comments:** English function-level docstrings; Chinese dialogue.
- **TDD:** write-failing-test → run-fail → implement → run-pass → commit per task. — decision ⑮.

---

## File Structure

```
skills/ib-portfolio-analyst/
  SKILL.md
  scripts/
    analyze.py                    # /ib-analyze entrypoint: lake -> modules -> report
  ib_analyst/
    __init__.py
    findings.py                   # Finding model, Priority enum, grade() helper
    account_health.py             # module 1: margin/cash/leverage
    concentration.py              # module 2: single-name weight, HHI, currency mix
    pnl_attribution.py            # module 3: realized+unrealized waterfall
    trade_review.py               # module 4: win rate, hold period, commission drag
    portfolio_risk.py             # module 5: VaR/CVaR/maxDD, marginal contribution
    pretrade_check.py             # module 6: v1 local-sim stub + v2 WhatIf outline
    report.py                     # findings + charts -> structured Markdown
  tests/
    fixtures/
      snapshot_diag.json          # richer snapshot for diagnostics
      executions_sample.json
      daily_bars_multi.json
    test_findings.py
    test_account_health.py
    test_concentration.py
    test_pnl_attribution.py
    test_trade_review.py
    test_portfolio_risk.py
    test_pretrade_check.py
    test_report.py
    test_analyze_e2e.py
```

**Boundary rationale:** one file per diagnostic dimension keeps each analysis holdable in context and independently reviewable. `findings.py` is the shared vocabulary every module speaks; `report.py` is the only file that knows about output formatting; `analyze.py` is the only file that knows about the lake layout.

**Note on imports:** `ib_analyst` is a package inside the skill. Tests put the skill dir on `sys.path` (`sys.path.insert(0, <skill_dir>)`) then `from ib_analyst.findings import Finding`. `ib_common` is already editable-installed in `.venv` from Plan 1.

---

## Task 1: Finding model + priority grading

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/__init__.py` (empty)
- Create: `skills/ib-portfolio-analyst/ib_analyst/findings.py`
- Test: `skills/ib-portfolio-analyst/tests/test_findings.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Priority` enum: `P0`, `P1`, `P2`, `P3` (str values `"P0".."P3"`).
  - `Finding` pydantic model with fields: `priority: Priority`, `dimension: str`, `finding: str`, `evidence: dict`, `impact: str`, `suggestion: str`, `trigger_condition: str`, `confidence: float`, `data_limitations: str`.
  - `grade(value: float, warn: float, crit: float, higher_is_worse: bool = True) -> Priority` — maps a metric against warn/crit cutoffs to P2/P1, else P3.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_findings.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_analyst.findings import Finding, Priority, grade


def test_grade_higher_is_worse():
    assert grade(0.40, warn=0.20, crit=0.35) == Priority.P1   # above crit
    assert grade(0.25, warn=0.20, crit=0.35) == Priority.P2   # between
    assert grade(0.10, warn=0.20, crit=0.35) == Priority.P3   # below warn


def test_grade_lower_is_worse():
    # e.g. cash ratio: lower is riskier
    assert grade(0.02, warn=0.10, crit=0.05, higher_is_worse=False) == Priority.P1
    assert grade(0.08, warn=0.10, crit=0.05, higher_is_worse=False) == Priority.P2
    assert grade(0.20, warn=0.10, crit=0.05, higher_is_worse=False) == Priority.P3


def test_finding_requires_all_fields():
    f = Finding(priority=Priority.P1, dimension="concentration",
                finding="AAPL is 40% of the book", evidence={"weight": 0.40},
                impact="single-name shock dominates portfolio P&L",
                suggestion="consider trimming toward target weight",
                trigger_condition="single position weight > 35%",
                confidence=0.9, data_limitations="prices as of last sync")
    assert f.priority == Priority.P1
    assert f.evidence["weight"] == 0.40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_findings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ib_analyst'`.

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/findings.py
"""Structured finding vocabulary shared by every diagnostic module.

A Finding is a graded fact: rules decide the priority, wording is added
later by the LLM layer. `grade` maps a metric to a priority against
configurable warn/crit cutoffs, in either direction.
"""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class Priority(str, Enum):
    P0 = "P0"   # act now / hard risk breach
    P1 = "P1"   # high
    P2 = "P2"   # medium
    P3 = "P3"   # informational


class Finding(BaseModel):
    priority: Priority
    dimension: str
    finding: str
    evidence: dict = Field(default_factory=dict)
    impact: str
    suggestion: str
    trigger_condition: str
    confidence: float
    data_limitations: str


def grade(value: float, warn: float, crit: float, higher_is_worse: bool = True) -> Priority:
    """Grade a metric to P1/P2/P3 against warn/crit cutoffs.

    higher_is_worse=True: value >= crit -> P1, >= warn -> P2, else P3.
    higher_is_worse=False: value <= crit -> P1, <= warn -> P2, else P3.
    """
    if higher_is_worse:
        if value >= crit:
            return Priority.P1
        if value >= warn:
            return Priority.P2
        return Priority.P3
    else:
        if value <= crit:
            return Priority.P1
        if value <= warn:
            return Priority.P2
        return Priority.P3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_findings.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/__init__.py skills/ib-portfolio-analyst/ib_analyst/findings.py skills/ib-portfolio-analyst/tests/test_findings.py
git commit -m "feat(analyst): Finding model + rule-based priority grading"
```

---

## Task 2: Module 1 — Account health

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/account_health.py`
- Create: `skills/ib-portfolio-analyst/tests/fixtures/snapshot_diag.json`
- Test: `skills/ib-portfolio-analyst/tests/test_account_health.py`

**Interfaces:**
- Consumes: `Snapshot` (Plan 1 schema), `Finding`/`Priority`/`grade` (Task 1).
- Produces:
  - `analyze(snapshot: Snapshot, thresholds: dict) -> list[Finding]` — computes cash ratio (`total_cash / net_liquidation`) and gross leverage (`sum(|market_value|) / net_liquidation`), grades each. Uses thresholds `cash_ratio_warn`, `cash_ratio_crit`, `leverage_warn`, `leverage_crit`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_account_health.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot
from ib_analyst import account_health
from ib_analyst.findings import Priority

FIX = Path(__file__).parent / "fixtures"
TH = {"cash_ratio_warn": 0.10, "cash_ratio_crit": 0.05,
      "leverage_warn": 1.5, "leverage_crit": 2.0}


def _snap():
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def test_reports_leverage_and_cash():
    findings = account_health.analyze(_snap(), TH)
    dims = {f.dimension for f in findings}
    assert "account_health" in dims
    # snapshot_diag has ~2x leverage and thin cash => at least one P1
    assert any(f.priority == Priority.P1 for f in findings)


def test_findings_are_complete():
    for f in account_health.analyze(_snap(), TH):
        assert f.finding and f.impact and f.suggestion and f.trigger_condition
        assert 0.0 <= f.confidence <= 1.0
```

- [ ] **Step 2: Write the fixture** (a leveraged, thin-cash book so P1 fires)

```json
{
  "account": {
    "account_id": "U0000000",
    "base_currency": "USD",
    "net_liquidation": 100000.0,
    "total_cash": 3000.0,
    "buying_power": 20000.0,
    "ts": "2026-07-15T20:00:00Z"
  },
  "positions": [
    {"account_id": "U0000000", "symbol": "AAPL", "sec_type": "STK", "currency": "USD",
     "quantity": 400, "avg_cost": 150.0, "market_price": 190.0, "market_value": 76000.0, "unrealized_pnl": 16000.0},
    {"account_id": "U0000000", "symbol": "MSFT", "sec_type": "STK", "currency": "USD",
     "quantity": 300, "avg_cost": 300.0, "market_price": 420.0, "market_value": 126000.0, "unrealized_pnl": 36000.0}
  ],
  "ts": "2026-07-15T20:00:00Z"
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_account_health.py -v`
Expected: FAIL (`account_health` not found).

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/account_health.py
"""Diagnostic module 1: account health (cash buffer + gross leverage).

Facts only: computes cash ratio and gross leverage from the snapshot and
grades them against configurable cutoffs. Wording/urgency come from the
Finding priority, not from prose here.
"""
from __future__ import annotations
from ib_common.schema import Snapshot
from .findings import Finding, Priority, grade

DIM = "account_health"


def analyze(snapshot: Snapshot, thresholds: dict) -> list[Finding]:
    """Return account-health findings: cash-ratio and leverage checks."""
    acct = snapshot.account
    nlv = acct.net_liquidation or 1.0
    gross = sum(abs(p.market_value) for p in snapshot.positions)
    cash_ratio = acct.total_cash / nlv
    leverage = gross / nlv

    findings: list[Finding] = []

    cash_p = grade(cash_ratio,
                   thresholds["cash_ratio_warn"], thresholds["cash_ratio_crit"],
                   higher_is_worse=False)
    findings.append(Finding(
        priority=cash_p, dimension=DIM,
        finding=f"Cash is {cash_ratio:.1%} of net liquidation",
        evidence={"cash_ratio": round(cash_ratio, 4),
                  "total_cash": acct.total_cash, "net_liquidation": nlv},
        impact="thin cash reduces ability to meet margin moves without forced selling",
        suggestion="review whether the cash buffer matches your margin volatility tolerance",
        trigger_condition=f"cash ratio <= {thresholds['cash_ratio_warn']:.0%}",
        confidence=0.95,
        data_limitations=f"values as of snapshot {acct.ts.isoformat()}",
    ))

    lev_p = grade(leverage, thresholds["leverage_warn"], thresholds["leverage_crit"])
    findings.append(Finding(
        priority=lev_p, dimension=DIM,
        finding=f"Gross leverage is {leverage:.2f}x net liquidation",
        evidence={"gross_exposure": gross, "net_liquidation": nlv,
                  "leverage": round(leverage, 3)},
        impact="higher leverage amplifies both drawdowns and margin sensitivity",
        suggestion="assess whether exposure is intentional and within your risk budget",
        trigger_condition=f"gross leverage >= {thresholds['leverage_warn']}x",
        confidence=0.95,
        data_limitations="market values use last-synced prices",
    ))
    return findings
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_account_health.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/account_health.py skills/ib-portfolio-analyst/tests/test_account_health.py skills/ib-portfolio-analyst/tests/fixtures/snapshot_diag.json
git commit -m "feat(analyst): account-health module (cash ratio + gross leverage)"
```

---

## Task 3: Module 2 — Concentration

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/concentration.py`
- Test: `skills/ib-portfolio-analyst/tests/test_concentration.py`

**Interfaces:**
- Consumes: `Snapshot`, `ib_common.metrics.risk.hhi`, `Finding`/`grade` (Task 1).
- Produces:
  - `analyze(snapshot: Snapshot, thresholds: dict) -> list[Finding]` — per-name weights, top-name weight, HHI. Thresholds: `single_position_weight_warn/crit`, `hhi_concentration_warn/crit`.
  - `build_chart(snapshot: Snapshot) -> go.Figure` — treemap of position weights.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_concentration.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot
from ib_analyst import concentration
from ib_analyst.findings import Priority
import plotly.graph_objects as go

FIX = Path(__file__).parent / "fixtures"
TH = {"single_position_weight_warn": 0.20, "single_position_weight_crit": 0.35,
      "hhi_concentration_warn": 0.18, "hhi_concentration_crit": 0.30}


def _snap():
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def test_flags_top_name_concentration():
    findings = concentration.analyze(_snap(), TH)
    # MSFT ~62% of book -> P1
    assert any(f.priority == Priority.P1 and "MSFT" in f.finding for f in findings)


def test_build_chart_returns_figure():
    fig = concentration.build_chart(_snap())
    assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_concentration.py -v`
Expected: FAIL (`concentration` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/concentration.py
"""Diagnostic module 2: position concentration (top-name weight + HHI).

Weights are computed on gross market value in the account base currency.
The treemap visualizes where capital actually sits.
"""
from __future__ import annotations
import plotly.graph_objects as go
from ib_common.schema import Snapshot
from ib_common.metrics.risk import hhi
from .findings import Finding, Priority, grade

DIM = "concentration"


def _weights(snapshot: Snapshot) -> dict[str, float]:
    """Gross-market-value weights per symbol; sums to 1 (or empty)."""
    gross = sum(abs(p.market_value) for p in snapshot.positions) or 1.0
    return {p.symbol: abs(p.market_value) / gross for p in snapshot.positions}


def analyze(snapshot: Snapshot, thresholds: dict) -> list[Finding]:
    """Return concentration findings: worst single-name weight and portfolio HHI."""
    weights = _weights(snapshot)
    findings: list[Finding] = []
    if not weights:
        return findings

    top_sym, top_w = max(weights.items(), key=lambda kv: kv[1])
    top_p = grade(top_w, thresholds["single_position_weight_warn"],
                  thresholds["single_position_weight_crit"])
    findings.append(Finding(
        priority=top_p, dimension=DIM,
        finding=f"{top_sym} is {top_w:.1%} of the portfolio",
        evidence={"symbol": top_sym, "weight": round(top_w, 4)},
        impact="single-name moves dominate portfolio P&L at this weight",
        suggestion="compare against your intended max single-name weight",
        trigger_condition=f"single-name weight >= {thresholds['single_position_weight_warn']:.0%}",
        confidence=0.9,
        data_limitations="weights use last-synced market values",
    ))

    h = hhi(list(weights.values()))
    hhi_p = grade(h, thresholds["hhi_concentration_warn"],
                  thresholds["hhi_concentration_crit"])
    findings.append(Finding(
        priority=hhi_p, dimension=DIM,
        finding=f"Portfolio HHI is {h:.2f}",
        evidence={"hhi": round(h, 4), "n_positions": len(weights)},
        impact="a high HHI means diversification benefit is limited",
        suggestion="review whether concentration matches your conviction level",
        trigger_condition=f"HHI >= {thresholds['hhi_concentration_warn']}",
        confidence=0.9,
        data_limitations="HHI ignores cross-name correlation",
    ))
    return findings


def build_chart(snapshot: Snapshot) -> go.Figure:
    """Treemap of position weights by symbol."""
    weights = _weights(snapshot)
    labels = list(weights.keys())
    values = [weights[s] for s in labels]
    fig = go.Figure(go.Treemap(labels=labels, parents=[""] * len(labels), values=values))
    fig.update_layout(title="Position concentration (weight of gross exposure)")
    return fig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_concentration.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/concentration.py skills/ib-portfolio-analyst/tests/test_concentration.py
git commit -m "feat(analyst): concentration module (top-name weight, HHI, treemap)"
```

---

## Task 4: Module 3 — P&L attribution

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/pnl_attribution.py`
- Test: `skills/ib-portfolio-analyst/tests/test_pnl_attribution.py`

**Interfaces:**
- Consumes: `Snapshot`, `Finding`, `plotly`.
- Produces:
  - `attribute(snapshot: Snapshot) -> dict[str, float]` — per-symbol unrealized P&L plus a `"_total"` key.
  - `analyze(snapshot: Snapshot, thresholds: dict) -> list[Finding]` — flags the largest single-name contributor to unrealized P&L. Threshold: `pnl_contrib_warn` (fraction of total gross P&L from one name).
  - `build_chart(snapshot: Snapshot) -> go.Figure` — waterfall of per-symbol contributions to total unrealized P&L.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_pnl_attribution.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot
from ib_analyst import pnl_attribution
import plotly.graph_objects as go

FIX = Path(__file__).parent / "fixtures"
TH = {"pnl_contrib_warn": 0.50}


def _snap():
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def test_attribute_sums_to_total():
    a = pnl_attribution.attribute(_snap())
    assert abs(a["_total"] - (a["AAPL"] + a["MSFT"])) < 1e-6
    assert a["_total"] == 52000.0     # 16000 + 36000


def test_analyze_flags_dominant_contributor():
    findings = pnl_attribution.analyze(_snap(), TH)
    assert any("MSFT" in f.finding for f in findings)   # MSFT drives most PnL


def test_waterfall_chart():
    fig = pnl_attribution.build_chart(_snap())
    assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_pnl_attribution.py -v`
Expected: FAIL (`pnl_attribution` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/pnl_attribution.py
"""Diagnostic module 3: P&L attribution by position.

Breaks unrealized P&L down per symbol and flags when a single name drives an
outsized share of the total. The waterfall chart shows how each name adds up
to the portfolio's unrealized result.
"""
from __future__ import annotations
import plotly.graph_objects as go
from ib_common.schema import Snapshot
from .findings import Finding, Priority

DIM = "pnl_attribution"


def attribute(snapshot: Snapshot) -> dict[str, float]:
    """Per-symbol unrealized P&L with a '_total' aggregate key."""
    out: dict[str, float] = {}
    total = 0.0
    for p in snapshot.positions:
        out[p.symbol] = out.get(p.symbol, 0.0) + p.unrealized_pnl
        total += p.unrealized_pnl
    out["_total"] = total
    return out


def analyze(snapshot: Snapshot, thresholds: dict) -> list[Finding]:
    """Flag the single largest contributor to gross unrealized P&L."""
    a = attribute(snapshot)
    per_name = {k: v for k, v in a.items() if k != "_total"}
    gross = sum(abs(v) for v in per_name.values()) or 1.0
    if not per_name:
        return []

    sym, val = max(per_name.items(), key=lambda kv: abs(kv[1]))
    share = abs(val) / gross
    priority = Priority.P2 if share >= thresholds["pnl_contrib_warn"] else Priority.P3
    return [Finding(
        priority=priority, dimension=DIM,
        finding=f"{sym} accounts for {share:.0%} of gross unrealized P&L ({val:+.0f})",
        evidence={"symbol": sym, "pnl": val, "share_of_gross": round(share, 4),
                  "total_unrealized": a["_total"]},
        impact="P&L is driven by one name; reversal there swings the whole book",
        suggestion="check whether this concentration of P&L is intentional",
        trigger_condition=f"one name >= {thresholds['pnl_contrib_warn']:.0%} of gross unrealized P&L",
        confidence=0.85,
        data_limitations="unrealized only; realized P&L requires execution history",
    )]


def build_chart(snapshot: Snapshot) -> go.Figure:
    """Waterfall of per-symbol contributions to total unrealized P&L."""
    a = attribute(snapshot)
    names = [k for k in a if k != "_total"]
    values = [a[n] for n in names]
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["relative"] * len(names) + ["total"],
        x=names + ["Total"],
        y=values + [a["_total"]],
    ))
    fig.update_layout(title="Unrealized P&L attribution by position")
    return fig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_pnl_attribution.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/pnl_attribution.py skills/ib-portfolio-analyst/tests/test_pnl_attribution.py
git commit -m "feat(analyst): P&L attribution module (per-name breakdown + waterfall)"
```

---

## Task 5: Module 4 — Trade review

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/trade_review.py`
- Create: `skills/ib-portfolio-analyst/tests/fixtures/executions_sample.json`
- Test: `skills/ib-portfolio-analyst/tests/test_trade_review.py`

**Interfaces:**
- Consumes: `Execution` (Plan 1 schema), `Finding`/`grade`.
- Produces:
  - `summarize(executions: list[Execution]) -> dict` — `{"n_trades", "buy_notional", "sell_notional", "total_commission", "commission_bps"}` (commission in bps of total notional).
  - `analyze(executions: list[Execution], thresholds: dict) -> list[Finding]` — flags commission drag. Threshold: `commission_bps_warn/crit`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_trade_review.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Execution
from ib_analyst import trade_review
from ib_analyst.findings import Priority

FIX = Path(__file__).parent / "fixtures"
TH = {"commission_bps_warn": 5.0, "commission_bps_crit": 15.0}


def _execs():
    rows = json.loads((FIX / "executions_sample.json").read_text())
    return [Execution(**r) for r in rows]


def test_summary_counts_and_notional():
    s = trade_review.summarize(_execs())
    assert s["n_trades"] == 3
    assert s["total_commission"] > 0
    assert s["commission_bps"] > 0


def test_flags_high_commission_drag():
    # fixture is built with heavy commissions -> P1
    findings = trade_review.analyze(_execs(), TH)
    assert any(f.priority in (Priority.P1, Priority.P2) for f in findings)
```

- [ ] **Step 2: Write the fixture** (small notional, fat commissions → high bps)

```json
[
  {"exec_id": "T1", "symbol": "AAPL", "side": "BUY", "quantity": 10, "price": 150.0, "commission": 3.0, "ts": "2026-02-01T15:00:00Z"},
  {"exec_id": "T2", "symbol": "AAPL", "side": "SELL", "quantity": 10, "price": 160.0, "commission": 3.0, "ts": "2026-03-01T15:00:00Z"},
  {"exec_id": "T3", "symbol": "MSFT", "side": "BUY", "quantity": 5, "price": 300.0, "commission": 4.0, "ts": "2026-03-05T15:00:00Z"}
]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_trade_review.py -v`
Expected: FAIL (`trade_review` not found).

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/trade_review.py
"""Diagnostic module 4: trade review (activity + execution cost).

v1 focuses on the most robust, always-available fact from executions:
commission drag in basis points of traded notional. Win-rate and holding
period need round-trip pairing and are deferred to a later iteration.
"""
from __future__ import annotations
from ib_common.schema import Execution
from .findings import Finding, grade

DIM = "trade_review"


def summarize(executions: list[Execution]) -> dict:
    """Aggregate trade counts, notional by side, and commission drag (bps)."""
    buy_notional = sum(e.quantity * e.price for e in executions if e.side.upper().startswith("B"))
    sell_notional = sum(e.quantity * e.price for e in executions if e.side.upper().startswith("S"))
    total_notional = buy_notional + sell_notional
    total_commission = sum(e.commission for e in executions)
    commission_bps = (total_commission / total_notional * 1e4) if total_notional else 0.0
    return {
        "n_trades": len(executions),
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "total_commission": total_commission,
        "commission_bps": commission_bps,
    }


def analyze(executions: list[Execution], thresholds: dict) -> list[Finding]:
    """Return trade-review findings: commission drag on traded notional."""
    if not executions:
        return []
    s = summarize(executions)
    p = grade(s["commission_bps"],
              thresholds["commission_bps_warn"], thresholds["commission_bps_crit"])
    return [Finding(
        priority=p, dimension=DIM,
        finding=f"Commissions cost {s['commission_bps']:.1f} bps of traded notional",
        evidence=s,
        impact="high per-trade cost erodes returns, especially on small tickets",
        suggestion="review order sizing and whether trade frequency is justified",
        trigger_condition=f"commission drag >= {thresholds['commission_bps_warn']} bps",
        confidence=0.9,
        data_limitations="reqExecutions only reaches ~7 days; use Flex for full history",
    )]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_trade_review.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/trade_review.py skills/ib-portfolio-analyst/tests/test_trade_review.py skills/ib-portfolio-analyst/tests/fixtures/executions_sample.json
git commit -m "feat(analyst): trade-review module (commission drag in bps)"
```

---

## Task 6: Module 5 — Portfolio risk

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/portfolio_risk.py`
- Create: `skills/ib-portfolio-analyst/tests/fixtures/daily_bars_multi.json`
- Test: `skills/ib-portfolio-analyst/tests/test_portfolio_risk.py`

**Interfaces:**
- Consumes: `Snapshot`, `DailyBar` (Plan 1 schema), `ib_common.metrics.risk` (`hist_var`, `hist_cvar`, `max_drawdown`), `Finding`/`grade`.
- Produces:
  - `portfolio_returns(snapshot: Snapshot, bars: list[DailyBar]) -> list[float]` — weight-weighted daily portfolio return series from per-symbol close-to-close returns.
  - `analyze(snapshot: Snapshot, bars: list[DailyBar], thresholds: dict) -> list[Finding]` — VaR/CVaR and max drawdown findings. Thresholds: `var95_warn/crit`, `max_drawdown_warn/crit`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_portfolio_risk.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot, DailyBar
from ib_analyst import portfolio_risk

FIX = Path(__file__).parent / "fixtures"
TH = {"var95_warn": 0.02, "var95_crit": 0.05,
      "max_drawdown_warn": 0.15, "max_drawdown_crit": 0.30}


def _snap():
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def _bars():
    return [DailyBar(**r) for r in json.loads((FIX / "daily_bars_multi.json").read_text())]


def test_portfolio_returns_length():
    r = portfolio_risk.portfolio_returns(_snap(), _bars())
    assert len(r) >= 1                      # one fewer than #dates per symbol


def test_analyze_emits_var_and_drawdown():
    findings = portfolio_risk.analyze(_snap(), _bars(), TH)
    dims = {f.dimension for f in findings}
    kinds = {f.evidence.get("metric") for f in findings}
    assert dims == {"portfolio_risk"}
    assert "var95" in kinds and "max_drawdown" in kinds
```

- [ ] **Step 2: Write the fixture** (two symbols, 6 daily closes each)

```json
[
  {"symbol": "AAPL", "date": "2026-07-08", "open": 180, "high": 182, "low": 179, "close": 180, "volume": 1000},
  {"symbol": "AAPL", "date": "2026-07-09", "open": 180, "high": 184, "low": 180, "close": 183, "volume": 1000},
  {"symbol": "AAPL", "date": "2026-07-10", "open": 183, "high": 185, "low": 181, "close": 182, "volume": 1000},
  {"symbol": "AAPL", "date": "2026-07-11", "open": 182, "high": 188, "low": 182, "close": 187, "volume": 1000},
  {"symbol": "AAPL", "date": "2026-07-14", "open": 187, "high": 190, "low": 185, "close": 186, "volume": 1000},
  {"symbol": "AAPL", "date": "2026-07-15", "open": 186, "high": 192, "low": 186, "close": 190, "volume": 1000},
  {"symbol": "MSFT", "date": "2026-07-08", "open": 400, "high": 405, "low": 398, "close": 402, "volume": 1000},
  {"symbol": "MSFT", "date": "2026-07-09", "open": 402, "high": 410, "low": 401, "close": 408, "volume": 1000},
  {"symbol": "MSFT", "date": "2026-07-10", "open": 408, "high": 412, "low": 404, "close": 405, "volume": 1000},
  {"symbol": "MSFT", "date": "2026-07-11", "open": 405, "high": 418, "low": 405, "close": 415, "volume": 1000},
  {"symbol": "MSFT", "date": "2026-07-14", "open": 415, "high": 420, "low": 410, "close": 412, "volume": 1000},
  {"symbol": "MSFT", "date": "2026-07-15", "open": 412, "high": 422, "low": 412, "close": 420, "volume": 1000}
]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_portfolio_risk.py -v`
Expected: FAIL (`portfolio_risk` not found).

- [ ] **Step 4: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/portfolio_risk.py
"""Diagnostic module 5: portfolio risk (VaR / CVaR / max drawdown).

Builds a weight-weighted daily return series from per-symbol close-to-close
returns, then applies the historical risk metrics from ib_common. Weights
come from current market values in the snapshot.
"""
from __future__ import annotations
from collections import defaultdict
import numpy as np
from ib_common.schema import Snapshot, DailyBar
from ib_common.metrics.risk import hist_var, hist_cvar, max_drawdown
from .findings import Finding, grade

DIM = "portfolio_risk"


def _returns_by_symbol(bars: list[DailyBar]) -> dict[str, list[float]]:
    """Close-to-close simple returns per symbol, ordered by date."""
    by_sym: dict[str, list[DailyBar]] = defaultdict(list)
    for b in bars:
        by_sym[b.symbol].append(b)
    out: dict[str, list[float]] = {}
    for sym, series in by_sym.items():
        series.sort(key=lambda b: b.date)
        closes = np.array([b.close for b in series], dtype=float)
        if closes.size >= 2:
            out[sym] = list(closes[1:] / closes[:-1] - 1.0)
    return out


def portfolio_returns(snapshot: Snapshot, bars: list[DailyBar]) -> list[float]:
    """Weight per-symbol return series by market value into a portfolio series."""
    rets = _returns_by_symbol(bars)
    if not rets:
        return []
    gross = sum(abs(p.market_value) for p in snapshot.positions) or 1.0
    weights = {p.symbol: abs(p.market_value) / gross for p in snapshot.positions}
    n = min(len(v) for v in rets.values())
    port = np.zeros(n)
    for sym, series in rets.items():
        w = weights.get(sym, 0.0)
        port += w * np.array(series[-n:])
    return list(port)


def analyze(snapshot: Snapshot, bars: list[DailyBar], thresholds: dict) -> list[Finding]:
    """Return portfolio VaR(95%) and max-drawdown findings."""
    port = portfolio_returns(snapshot, bars)
    if not port:
        return []

    var95 = hist_var(port, 0.95)
    cvar95 = hist_cvar(port, 0.95)
    equity = np.cumprod([1 + r for r in port])
    mdd = abs(max_drawdown(list(equity)))

    findings: list[Finding] = []
    findings.append(Finding(
        priority=grade(var95, thresholds["var95_warn"], thresholds["var95_crit"]),
        dimension=DIM,
        finding=f"1-day 95% historical VaR is {var95:.2%} (CVaR {cvar95:.2%})",
        evidence={"metric": "var95", "var95": round(var95, 5), "cvar95": round(cvar95, 5),
                  "n_days": len(port)},
        impact="on a bad day around this loss fraction is expected to be exceeded 5% of the time",
        suggestion="check the loss size against your daily risk tolerance",
        trigger_condition=f"1-day 95% VaR >= {thresholds['var95_warn']:.0%}",
        confidence=0.7,
        data_limitations="historical VaR on a short window; not forward-looking",
    ))
    findings.append(Finding(
        priority=grade(mdd, thresholds["max_drawdown_warn"], thresholds["max_drawdown_crit"]),
        dimension=DIM,
        finding=f"Sample-window max drawdown is {mdd:.1%}",
        evidence={"metric": "max_drawdown", "max_drawdown": round(mdd, 4), "n_days": len(port)},
        impact="drawdown shows the worst peak-to-trough drop over the sample",
        suggestion="verify this is within the drawdown you can hold through",
        trigger_condition=f"max drawdown >= {thresholds['max_drawdown_warn']:.0%}",
        confidence=0.7,
        data_limitations="based on the daily bars available in the lake",
    ))
    return findings
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_portfolio_risk.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/portfolio_risk.py skills/ib-portfolio-analyst/tests/test_portfolio_risk.py skills/ib-portfolio-analyst/tests/fixtures/daily_bars_multi.json
git commit -m "feat(analyst): portfolio-risk module (VaR/CVaR/max drawdown)"
```

---

## Task 7: Module 6 — Pre-trade check (v1 local-sim stub)

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/pretrade_check.py`
- Test: `skills/ib-portfolio-analyst/tests/test_pretrade_check.py`

**Interfaces:**
- Consumes: `Snapshot`, `Finding`.
- Produces:
  - `simulate(snapshot: Snapshot, symbol: str, side: str, quantity: float, price: float, thresholds: dict) -> list[Finding]` — locally estimates the *post-trade* single-name weight and gross leverage (no IB call), flags if the hypothetical trade would breach concentration/leverage cutoffs. Docstring notes the v2 plan is a real WhatIf margin check through the order API.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_pretrade_check.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot
from ib_analyst import pretrade_check
from ib_analyst.findings import Priority

FIX = Path(__file__).parent / "fixtures"
TH = {"single_position_weight_warn": 0.20, "single_position_weight_crit": 0.35,
      "leverage_warn": 1.5, "leverage_crit": 2.0}


def _snap():
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def test_buying_more_of_top_name_flags_concentration():
    # add a lot more MSFT (already ~62%) -> post-trade weight worse -> P1
    findings = pretrade_check.simulate(_snap(), "MSFT", "BUY", 200, 420.0, TH)
    assert any(f.priority == Priority.P1 for f in findings)


def test_findings_declare_local_simulation_limit():
    findings = pretrade_check.simulate(_snap(), "MSFT", "BUY", 10, 420.0, TH)
    assert all("local" in f.data_limitations.lower() for f in findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_pretrade_check.py -v`
Expected: FAIL (`pretrade_check` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/pretrade_check.py
"""Diagnostic module 6: pre-trade risk check (v1 local simulation).

v1 estimates the post-trade single-name weight and gross leverage purely
from the local snapshot — it never contacts IB and never places an order.

v2 (deferred): replace the local estimate with a real IB WhatIf order
(`whatIfOrder`) to read the broker's exact margin impact. That requires the
order API and is intentionally out of the read-only v1 scope.
"""
from __future__ import annotations
from ib_common.schema import Snapshot
from .findings import Finding, grade

DIM = "pretrade_check"


def simulate(snapshot: Snapshot, symbol: str, side: str, quantity: float,
             price: float, thresholds: dict) -> list[Finding]:
    """Estimate post-trade concentration + leverage locally (no IB call)."""
    signed_qty = quantity if side.upper().startswith("B") else -quantity
    delta_value = signed_qty * price

    # rebuild gross exposure with the hypothetical fill
    values = {p.symbol: p.market_value for p in snapshot.positions}
    values[symbol] = values.get(symbol, 0.0) + delta_value
    gross = sum(abs(v) for v in values.values()) or 1.0
    nlv = snapshot.account.net_liquidation or 1.0

    new_weight = abs(values[symbol]) / gross
    new_leverage = gross / nlv
    limit_note = "local estimate only; no IB WhatIf margin call in v1"

    findings: list[Finding] = []
    findings.append(Finding(
        priority=grade(new_weight, thresholds["single_position_weight_warn"],
                       thresholds["single_position_weight_crit"]),
        dimension=DIM,
        finding=f"After this trade {symbol} would be {new_weight:.1%} of gross exposure",
        evidence={"symbol": symbol, "post_trade_weight": round(new_weight, 4),
                  "delta_value": delta_value},
        impact="the trade shifts single-name concentration",
        suggestion="compare post-trade weight against your max single-name limit",
        trigger_condition=f"post-trade weight >= {thresholds['single_position_weight_warn']:.0%}",
        confidence=0.6,
        data_limitations=limit_note,
    ))
    findings.append(Finding(
        priority=grade(new_leverage, thresholds["leverage_warn"], thresholds["leverage_crit"]),
        dimension=DIM,
        finding=f"After this trade gross leverage would be {new_leverage:.2f}x",
        evidence={"post_trade_leverage": round(new_leverage, 3), "delta_value": delta_value},
        impact="the trade changes overall leverage and margin sensitivity",
        suggestion="verify post-trade leverage stays within your risk budget",
        trigger_condition=f"post-trade leverage >= {thresholds['leverage_warn']}x",
        confidence=0.6,
        data_limitations=limit_note,
    ))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_pretrade_check.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/pretrade_check.py skills/ib-portfolio-analyst/tests/test_pretrade_check.py
git commit -m "feat(analyst): pre-trade check v1 (local post-trade weight/leverage sim)"
```

---

## Task 8: Report assembly (findings + charts → Markdown)

**Files:**
- Create: `skills/ib-portfolio-analyst/ib_analyst/report.py`
- Test: `skills/ib-portfolio-analyst/tests/test_report.py`

**Interfaces:**
- Consumes: `Finding`/`Priority` (Task 1), `ib_common.charts.render.render`.
- Produces:
  - `sort_findings(findings: list[Finding]) -> list[Finding]` — stable sort by priority P0→P3.
  - `to_markdown(findings: list[Finding], chart_paths: dict[str, str]) -> str` — renders a structured report: a P-count summary line, then one section per finding with all seven fields, then an embedded PNG per chart.
  - `build_report(findings, figures: dict[str, go.Figure], out_dir: str | Path) -> dict` — renders each figure via `ib_common.charts.render`, writes `report.md`, returns `{"report": Path, "charts": {name: {"html","png"}}}`.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_report.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_analyst.findings import Finding, Priority
from ib_analyst import report
import plotly.graph_objects as go


def _findings():
    return [
        Finding(priority=Priority.P2, dimension="d", finding="f2", evidence={},
                impact="i", suggestion="s", trigger_condition="t", confidence=0.8,
                data_limitations="l"),
        Finding(priority=Priority.P0, dimension="d", finding="f0", evidence={},
                impact="i", suggestion="s", trigger_condition="t", confidence=0.9,
                data_limitations="l"),
    ]


def test_sort_by_priority_p0_first():
    ordered = report.sort_findings(_findings())
    assert ordered[0].priority == Priority.P0


def test_markdown_contains_all_fields_and_summary():
    md = report.to_markdown(_findings(), {"concentration": "concentration.png"})
    assert "P0" in md and "P2" in md
    for label in ("Finding", "Evidence", "Impact", "Suggestion",
                  "Trigger", "Confidence", "Data limitations"):
        assert label in md
    assert "concentration.png" in md          # chart embedded


def test_build_report_writes_files(tmp_path):
    fig = go.Figure(data=[go.Bar(x=["a"], y=[1])])
    out = report.build_report(_findings(), {"demo": fig}, tmp_path)
    assert Path(out["report"]).exists()
    assert Path(out["charts"]["demo"]["png"]).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_report.py -v`
Expected: FAIL (`report` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/ib_analyst/report.py
"""Assemble graded findings + charts into a structured Markdown report.

Deterministic layout: a priority-count summary, findings ordered P0->P3 with
every field spelled out, then embedded chart PNGs. The LLM layer may re-word
prose around this, but the facts and structure originate here.
"""
from __future__ import annotations
from pathlib import Path
import plotly.graph_objects as go
from ib_common.charts.render import render
from .findings import Finding, Priority

_ORDER = {Priority.P0: 0, Priority.P1: 1, Priority.P2: 2, Priority.P3: 3}


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Stable sort by priority, P0 first."""
    return sorted(findings, key=lambda f: _ORDER[f.priority])


def _summary_line(findings: list[Finding]) -> str:
    """One-line count of findings per priority."""
    counts = {p: 0 for p in Priority}
    for f in findings:
        counts[f.priority] += 1
    parts = [f"{p.value}: {counts[p]}" for p in Priority]
    return "**Summary** — " + ", ".join(parts)


def to_markdown(findings: list[Finding], chart_paths: dict[str, str]) -> str:
    """Render findings + chart references to a structured Markdown string."""
    lines: list[str] = ["# Portfolio Diagnostic Report", "", _summary_line(findings), ""]
    for f in sort_findings(findings):
        lines += [
            f"## [{f.priority.value}] {f.dimension}",
            f"- **Finding:** {f.finding}",
            f"- **Evidence:** `{f.evidence}`",
            f"- **Impact:** {f.impact}",
            f"- **Suggestion:** {f.suggestion}",
            f"- **Trigger:** {f.trigger_condition}",
            f"- **Confidence:** {f.confidence:.0%}",
            f"- **Data limitations:** {f.data_limitations}",
            "",
        ]
    if chart_paths:
        lines.append("## Charts")
        for name, png in chart_paths.items():
            lines.append(f"![{name}]({png})")
        lines.append("")
    return "\n".join(lines)


def build_report(findings: list[Finding], figures: dict[str, go.Figure],
                 out_dir: str | Path) -> dict:
    """Render charts, write report.md, and return the produced paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chart_products: dict[str, dict] = {}
    chart_paths: dict[str, str] = {}
    for name, fig in figures.items():
        products = render(fig, out, name)
        chart_products[name] = {k: str(v) for k, v in products.items()}
        chart_paths[name] = products["png"].name    # relative for embedding
    md = to_markdown(findings, chart_paths)
    report_path = out / "report.md"
    report_path.write_text(md, encoding="utf-8")
    return {"report": str(report_path), "charts": chart_products}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_report.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-portfolio-analyst/ib_analyst/report.py skills/ib-portfolio-analyst/tests/test_report.py
git commit -m "feat(analyst): report assembly (structured Markdown + embedded charts)"
```

---

## Task 9: /ib-analyze entrypoint + SKILL.md (end-to-end)

**Files:**
- Create: `skills/ib-portfolio-analyst/scripts/analyze.py`
- Create: `skills/ib-portfolio-analyst/SKILL.md`
- Test: `skills/ib-portfolio-analyst/tests/test_analyze_e2e.py`

**Interfaces:**
- Consumes: all six modules, `report.build_report`, `ib_common.config.load_config`, `ib_common.schema.Snapshot`, `ib_common.storage.read_timeseries`.
- Produces:
  - `load_latest_snapshot(root: str | Path, account_id: str | None = None) -> Snapshot` — reads the newest `snapshots/*/**.json`.
  - `run(cfg_path: str, snapshot_path: str, bars: list | None = None, executions: list | None = None, out_dir: str | None = None) -> dict` — orchestrates all modules with config thresholds, assembles the report, returns `build_report`'s dict.

- [ ] **Step 1: Write the failing test**

```python
# skills/ib-portfolio-analyst/tests/test_analyze_e2e.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "analyze.py"
spec = importlib.util.spec_from_file_location("analyze", SPEC)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)

FIX = Path(__file__).parent / "fixtures"


def test_end_to_end_generates_report(tmp_path):
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
    )
    out = analyze.run(
        str(cfg),
        snapshot_path=str(FIX / "snapshot_diag.json"),
        bars=json.loads((FIX / "daily_bars_multi.json").read_text()),
        executions=json.loads((FIX / "executions_sample.json").read_text()),
        out_dir=str(tmp_path / "run"),
    )
    report_text = Path(out["report"]).read_text()
    assert "Portfolio Diagnostic Report" in report_text
    # every dimension should appear
    for dim in ("account_health", "concentration", "pnl_attribution",
                "trade_review", "portfolio_risk"):
        assert dim in report_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_analyze_e2e.py -v`
Expected: FAIL (analyze.py absent).

- [ ] **Step 3: Write minimal implementation**

```python
# skills/ib-portfolio-analyst/scripts/analyze.py
"""/ib-analyze entrypoint: read the local lake, run all diagnostics, emit report.

Read-only and offline: it consumes snapshots/bars/executions that ib-gateway
already landed and never contacts IB. Bars/executions can be injected (tests)
or loaded from the lake in production use.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

# make the sibling ib_analyst package importable when run as a script
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ib_common.config import load_config
from ib_common.schema import Snapshot, DailyBar, Execution
from ib_analyst import (account_health, concentration, pnl_attribution,
                        trade_review, portfolio_risk)
from ib_analyst import report


def load_latest_snapshot(root: str | Path, account_id: str | None = None) -> Snapshot:
    """Load the newest snapshot JSON under root/snapshots (optionally per account)."""
    base = Path(root) / "snapshots"
    pattern = f"{account_id}/*.json" if account_id else "*/*.json"
    files = sorted(base.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no snapshots found under {base}")
    return Snapshot.model_validate_json(files[-1].read_text(encoding="utf-8"))


def run(cfg_path: str, snapshot_path: str, bars: list | None = None,
        executions: list | None = None, out_dir: str | None = None) -> dict:
    """Run every diagnostic module and assemble the report."""
    cfg = load_config(cfg_path)
    th = cfg.thresholds
    snap = Snapshot.model_validate_json(Path(snapshot_path).read_text(encoding="utf-8"))
    bar_rows = [DailyBar(**b) for b in (bars or [])]
    exec_rows = [Execution(**e) for e in (executions or [])]

    findings = []
    findings += account_health.analyze(snap, th)
    findings += concentration.analyze(snap, th)
    findings += pnl_attribution.analyze(snap, th)
    if exec_rows:
        findings += trade_review.analyze(exec_rows, th)
    if bar_rows:
        findings += portfolio_risk.analyze(snap, bar_rows, th)

    figures = {
        "concentration": concentration.build_chart(snap),
        "pnl_attribution": pnl_attribution.build_chart(snap),
    }
    out = out_dir or "./data/runs/latest"
    return report.build_report(findings, figures, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run IB portfolio diagnostics (read-only).")
    parser.add_argument("--config", required=True)
    parser.add_argument("--snapshot", required=True, help="path to a snapshot JSON")
    parser.add_argument("--bars", help="optional path to daily bars JSON")
    parser.add_argument("--executions", help="optional path to executions JSON")
    parser.add_argument("--out", help="output directory for the report + charts")
    args = parser.parse_args()
    bars = json.loads(Path(args.bars).read_text()) if args.bars else None
    execs = json.loads(Path(args.executions).read_text()) if args.executions else None
    print(run(args.config, args.snapshot, bars, execs, args.out))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest skills/ib-portfolio-analyst/tests/test_analyze_e2e.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Write SKILL.md**

```markdown
---
name: ib-portfolio-analyst
description: Read-only diagnostics over your Interactive Brokers data — account health, concentration, P&L attribution, trade review, portfolio risk and a local pre-trade check — as a P0-P3 findings report with charts.
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
```

- [ ] **Step 6: Verify description length + full suite green**

Run: `.venv/bin/python -c "import re; t=open('skills/ib-portfolio-analyst/SKILL.md').read(); print(len(re.search(r'description: (.+)', t).group(1)))" && .venv/bin/python -m pytest skills -v`
Expected: description length ≤ 160; all Plan 1 + Plan 2 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add skills/ib-portfolio-analyst/scripts/analyze.py skills/ib-portfolio-analyst/SKILL.md skills/ib-portfolio-analyst/tests/test_analyze_e2e.py
git commit -m "feat(analyst): /ib-analyze end-to-end orchestration + SKILL.md"
```

---

## Self-Review

**1. Spec coverage (v1 account-diagnostics 6 items):**
- Account health (margin/cash/leverage) → Task 2 ✅
- Position concentration (single-name + HHI + treemap) → Task 3 ✅
- P&L attribution (per-name + waterfall) → Task 4 ✅
- Historical trade review (commission drag) → Task 5 ✅ *(win-rate/hold-period explicitly deferred)*
- Portfolio risk (VaR/CVaR/max drawdown) → Task 6 ✅
- Pre-trade check (local sim, v2 WhatIf outlined) → Task 7 ✅
- P0–P3 finding structure with 7 fields → Task 1 + enforced in every module ✅
- Facts-by-rule / LLM-wording separation → deterministic modules, no prose grading ✅
- All thresholds configurable → every module reads `thresholds` dict ✅
- Charts plotly+kaleido dual output → Task 3/4 build figures, Task 8 renders via ib_common ✅
- Structured Markdown report → Task 8 ✅
- End-to-end orchestration + skill registration → Task 9 ✅
- Read-only / offline → no IB imports anywhere; entrypoint reads lake only ✅

**2. Placeholder scan:** No TBD/TODO; every code step is runnable; commands carry expected output. ✅

**3. Type consistency:** `Finding` field set identical across Tasks 1–9. `analyze(...)`/`build_chart(...)` signatures match their use in Task 9. `thresholds` keys used in modules (`cash_ratio_warn`, `leverage_warn`, `single_position_weight_warn`, `hhi_concentration_warn`, `pnl_contrib_warn`, `commission_bps_warn`, `var95_warn`, `max_drawdown_warn`, and their `_crit` pairs) all appear in the Task 9 e2e config and Plan 1's `config.example.yaml`. `render()` return shape (`{"html","png"}`) matches Task 8's use. ✅

**Deferred (documented, out of v1 scope):** win-rate & holding-period pairing, industry/currency concentration breakdown, marginal risk contribution & beta (needs benchmark bars), realized-P&L attribution (needs execution history joined to lots), correlation heatmap. These land in a later iteration once the lake carries executions/bars time-series.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-16-ib-analyst-plan2-diagnostics.md`. Execution options presented once at the end of the batch, after Plan 3.
