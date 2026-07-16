import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_analyst.findings import Finding, Priority
from ib_analyst import report
import plotly.graph_objects as go


def _findings():
    return [
        Finding(priority=Priority.P2, dimension="d", finding="f2", evidence={},
                impact="i", suggestion="s", trigger_condition="t", confidence=0.8,
                data_limitations="l"),
        Finding(priority=Priority.P0, dimension="d", finding="f0", evidence={},
                impact="i", suggestion="s", trigger_condition="t", confidence=0.9,
                data_limitations="l"),
    ]


def test_sort_by_priority_p0_first():
    ordered = report.sort_findings(_findings())
    assert ordered[0].priority == Priority.P0


def test_markdown_contains_all_fields_and_summary():
    md = report.to_markdown(_findings(), {"concentration": "concentration.png"})
    assert "P0" in md and "P2" in md
    for label in ("Finding", "Evidence", "Impact", "Suggestion",
                  "Trigger", "Confidence", "Data limitations"):
        assert label in md
    assert "concentration.png" in md          # chart embedded


def test_build_report_writes_files(tmp_path):
    fig = go.Figure(data=[go.Bar(x=["a"], y=[1])])
    out = report.build_report(_findings(), {"demo": fig}, tmp_path)
    assert Path(out["report"]).exists()
    assert Path(out["charts"]["demo"]["png"]).exists()
