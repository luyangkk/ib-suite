# skills/ib-portfolio-analyst/tests/test_findings.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_analyst.findings import Finding, Priority, grade


def test_grade_higher_is_worse():
    assert grade(0.40, warn=0.20, crit=0.35) == Priority.P1   # above crit
    assert grade(0.25, warn=0.20, crit=0.35) == Priority.P2   # between
    assert grade(0.10, warn=0.20, crit=0.35) == Priority.P3   # below warn


def test_grade_lower_is_worse():
    # e.g. cash ratio: lower is riskier
    assert grade(0.02, warn=0.10, crit=0.05, higher_is_worse=False) == Priority.P1
    assert grade(0.08, warn=0.10, crit=0.05, higher_is_worse=False) == Priority.P2
    assert grade(0.20, warn=0.10, crit=0.05, higher_is_worse=False) == Priority.P3


def test_finding_requires_all_fields():
    f = Finding(priority=Priority.P1, dimension="concentration",
                finding="AAPL is 40% of the book", evidence={"weight": 0.40},
                impact="single-name shock dominates portfolio P&L",
                suggestion="consider trimming toward target weight",
                trigger_condition="single position weight > 35%",
                confidence=0.9, data_limitations="prices as of last sync")
    assert f.priority == Priority.P1
    assert f.evidence["weight"] == 0.40
