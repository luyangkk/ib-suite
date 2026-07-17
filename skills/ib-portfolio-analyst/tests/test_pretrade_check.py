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
