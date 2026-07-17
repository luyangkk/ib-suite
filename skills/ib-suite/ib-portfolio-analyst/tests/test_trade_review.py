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
