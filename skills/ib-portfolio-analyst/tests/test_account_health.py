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
