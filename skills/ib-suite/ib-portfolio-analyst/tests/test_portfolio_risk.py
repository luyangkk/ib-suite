import sys, json
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot, DailyBar
from ib_analyst import portfolio_risk
from ib_analyst.findings import Priority

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


def _losing_bars():
    """Build a sharply losing daily series for both snapshot symbols.

    Closes fall ~20% every day, producing several large negative daily
    returns and a deep peak-to-trough drop, so both VaR(95%) and max
    drawdown clear the crit cutoffs in TH and should grade to P1.
    """
    dates = [date(2026, 7, d) for d in (8, 9, 10, 11, 14, 15)]
    closes = [100.0, 80.0, 64.0, 51.2, 40.96, 32.77]  # ~-20% each step
    bars: list[DailyBar] = []
    for sym in ("AAPL", "MSFT"):
        for d, c in zip(dates, closes):
            # OHLCV wrapping the close; only close feeds the return series.
            bars.append(DailyBar(symbol=sym, date=d, open=c, high=c,
                                 low=c, close=c, volume=1000.0))
    return bars


def test_var_and_drawdown_sign_and_grading_direction():
    """Regression guard: pin VaR/drawdown sign convention and P1 direction.

    A steep loss series must yield a positive VaR and a non-negative max
    drawdown, and both metrics must cross their crit thresholds -> P1. If
    the sign convention ever flipped (e.g. VaR returned negative), the
    positivity asserts and/or the grading direction would fail here.
    """
    findings = portfolio_risk.analyze(_snap(), _losing_bars(), TH)
    var_f = next(f for f in findings if f.evidence["metric"] == "var95")
    mdd_f = next(f for f in findings if f.evidence["metric"] == "max_drawdown")

    # Grading direction: losses this deep are top-severity.
    assert var_f.priority == Priority.P1
    assert mdd_f.priority == Priority.P1

    # Sign convention: both metrics are reported as positive magnitudes.
    assert var_f.evidence["var95"] > 0
    assert mdd_f.evidence["max_drawdown"] >= 0
