import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Dividend
from ib_analyst import dividend_report
import plotly.graph_objects as go

FIX = Path(__file__).parent / "fixtures"


def _divs():
    return [Dividend(**r) for r in json.loads((FIX / "dividends_sample.json").read_text())]


def test_build_chart_is_stacked_bar():
    fig = dividend_report.build_chart(_divs())
    assert isinstance(fig, go.Figure)
    assert fig.layout.barmode == "stack"
    # two traces: net income + tax
    assert len(fig.data) == 2


def test_empty_dividends_yield_empty_figure():
    fig = dividend_report.build_chart([])
    assert isinstance(fig, go.Figure)
