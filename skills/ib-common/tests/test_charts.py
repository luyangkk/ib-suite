import plotly.graph_objects as go
from ib_common.charts.render import render


def test_render_produces_both_products(tmp_path):
    fig = go.Figure(data=[go.Bar(x=["AAPL", "MSFT"], y=[19000, 21000])])
    out = render(fig, tmp_path, "concentration")
    assert out["html"].exists() and out["html"].suffix == ".html"
    assert out["png"].exists() and out["png"].suffix == ".png"
    assert out["png"].stat().st_size > 0     # kaleido actually rendered pixels
