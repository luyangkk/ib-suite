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
    assert yoc["AAPL"] == 0.0004               # guards against cost-basis miscalc
    assert "MSFT" in yoc                       # MSFT held: 300 @ 300 = 90000 basis
    assert "TSM" not in yoc                    # TSM not held in snapshot


def test_analyze_flags_withholding_drag():
    findings = dividend_analysis.analyze(_divs(), _snap(), TH)
    assert any(f.dimension == "dividends" for f in findings)
    # total tax 10.5 / gross 111.5 = ~9.4% -> BELOW warn 0.10 -> P3
    drag_findings = [f for f in findings
                     if "withholding" in f.finding.lower() or "tax" in f.finding.lower()]
    assert drag_findings
    assert drag_findings[0].priority == Priority.P3
    # best held Yield-on-Cost is MSFT (37.5/90000 > AAPL 24/60000);
    # 0.000417 <= crit 0.01 under higher_is_worse=False -> P1
    yoc_findings = [f for f in findings if "yield on cost" in f.finding.lower()]
    assert yoc_findings
    assert yoc_findings[0].evidence["symbol"] == "MSFT"
    assert yoc_findings[0].priority == Priority.P1


def test_analyze_empty_returns_empty():
    assert dividend_analysis.analyze([], _snap(), TH) == []
