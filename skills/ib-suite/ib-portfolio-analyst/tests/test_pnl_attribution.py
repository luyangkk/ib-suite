# skills/ib-portfolio-analyst/tests/test_pnl_attribution.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot
from ib_analyst import pnl_attribution
from ib_analyst.findings import Priority
import plotly.graph_objects as go

FIX = Path(__file__).parent / "fixtures"
TH = {"pnl_contrib_warn": 0.50}


def _snap():
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def _zero_pnl_snap() -> Snapshot:
    """Snapshot where market_price == avg_cost, so every unrealized_pnl is 0.

    This mirrors ib_sync v1, which lands avg_cost as a market_price placeholder.
    """
    return Snapshot.model_validate({
        "account": {"account_id": "U0", "base_currency": "USD",
                    "net_liquidation": 100000.0, "total_cash": 0.0,
                    "buying_power": 0.0, "ts": "2026-07-15T20:00:00Z"},
        "positions": [
            {"account_id": "U0", "symbol": "AAA", "sec_type": "STK", "currency": "USD",
             "quantity": 10, "avg_cost": 100.0, "market_price": 100.0,
             "market_value": 1000.0, "unrealized_pnl": 0.0},
            {"account_id": "U0", "symbol": "BBB", "sec_type": "STK", "currency": "USD",
             "quantity": 5, "avg_cost": 200.0, "market_price": 200.0,
             "market_value": 1000.0, "unrealized_pnl": 0.0},
        ],
        "ts": "2026-07-15T20:00:00Z",
    })


def test_attribute_sums_to_total():
    a = pnl_attribution.attribute(_snap())
    assert abs(a["_total"] - (a["AAPL"] + a["MSFT"])) < 1e-6
    assert a["_total"] == 52000.0     # 16000 + 36000


def test_analyze_flags_dominant_contributor():
    findings = pnl_attribution.analyze(_snap(), TH)
    assert any("MSFT" in f.finding for f in findings)   # MSFT drives most PnL
    # 抓取被标记的 MSFT finding，做回归性断言，防止优先级逻辑被反转仍然通过
    f = next(x for x in findings if "MSFT" in x.finding)
    # MSFT 占比 = 36000/52000 ≈ 0.692 >= 0.50 warn 阈值，应判定为 P2
    assert f.priority == Priority.P2
    # 证据中的 gross 占比应约等于 0.6923
    assert abs(f.evidence["share_of_gross"] - 0.6923) < 1e-3


def test_waterfall_chart():
    fig = pnl_attribution.build_chart(_snap())
    assert isinstance(fig, go.Figure)


def test_zero_unrealized_pnl_returns_data_unavailable_not_attribution():
    # ib_sync v1 lands avg_cost as market_price, so all unrealized_pnl == 0.
    # Attribution is meaningless here; do not emit a misleading "X = 0% of P&L".
    findings = pnl_attribution.analyze(_zero_pnl_snap(), TH)
    assert len(findings) == 1
    f = findings[0]
    assert f.priority == Priority.P3
    # The finding must say attribution is unavailable, not name a dominant symbol.
    assert "unavailable" in f.finding.lower()
    assert "no unrealized" in f.data_limitations.lower()


def test_attribute_converts_non_base_currency():
    """A SGD position's unrealized P&L must be converted to base before summing."""
    snap = Snapshot.model_validate({
        "account": {"account_id": "U0", "base_currency": "USD",
                    "net_liquidation": 100000.0, "total_cash": 0.0,
                    "buying_power": 0.0, "ts": "2026-07-17T00:00:00Z"},
        "positions": [
            {"account_id": "U0", "symbol": "AAA", "sec_type": "STK", "currency": "USD",
             "quantity": 1, "avg_cost": 0.0, "market_price": 0.0,
             "market_value": 0.0, "unrealized_pnl": 1000.0},
            {"account_id": "U0", "symbol": "D05", "sec_type": "STK", "currency": "SGD",
             "quantity": 1, "avg_cost": 0.0, "market_price": 0.0,
             "market_value": 0.0, "unrealized_pnl": 2000.0, "fx_rate": 0.5},
        ],
        "ts": "2026-07-17T00:00:00Z",
    })
    a = pnl_attribution.attribute(snap)
    assert a["D05"] == 1000.0          # 2000 SGD @ 0.5
    assert a["_total"] == 2000.0       # 1000 USD + 1000 (SGD->USD)
