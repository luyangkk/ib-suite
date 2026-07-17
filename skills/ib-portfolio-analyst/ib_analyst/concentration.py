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
