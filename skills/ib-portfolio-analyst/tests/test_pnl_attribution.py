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
