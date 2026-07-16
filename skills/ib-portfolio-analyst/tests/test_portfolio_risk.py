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
