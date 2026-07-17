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
