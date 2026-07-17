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
