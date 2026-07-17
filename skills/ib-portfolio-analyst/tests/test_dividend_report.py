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
    # 按 trace 名称建立 {symbol: value} 查找表，锁定绘制的数值，
    # 防止 net<->tax 互换或数值错误仍能通过测试
    by_name = {t.name: dict(zip(t.x, t.y)) for t in fig.data}
    assert by_name["Net income"] == {"AAPL": 24.0, "MSFT": 37.5, "TSM": 39.5}
    assert by_name["Withholding tax"] == {"AAPL": 0.0, "MSFT": 0.0, "TSM": 10.5}


def test_empty_dividends_yield_empty_figure():
    fig = dividend_report.build_chart([])
    assert isinstance(fig, go.Figure)
    assert fig.layout.barmode == "stack"
