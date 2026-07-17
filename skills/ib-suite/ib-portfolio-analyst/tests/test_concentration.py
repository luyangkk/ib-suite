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


def _pos(symbol: str, sec_type: str, market_value: float, currency: str = "USD") -> dict:
    """Minimal position row; only symbol/sec_type/market_value/currency matter here."""
    return {
        "account_id": "U0", "symbol": symbol, "sec_type": sec_type,
        "currency": currency, "quantity": 1.0, "avg_cost": 0.0,
        "market_price": 0.0, "market_value": market_value, "unrealized_pnl": 0.0,
    }


def _multi_row_snap() -> Snapshot:
    """Snapshot where AAA spans a stock leg + an option leg (same symbol, two rows)."""
    return Snapshot.model_validate({
        "account": {"account_id": "U0", "base_currency": "USD",
                    "net_liquidation": 100000.0, "total_cash": 0.0,
                    "buying_power": 0.0, "ts": "2026-07-15T20:00:00Z"},
        "positions": [
            _pos("AAA", "STK", 60000.0),
            _pos("AAA", "OPT", -100.0),   # short option hedges the stock leg
            _pos("BBB", "STK", 40000.0),
        ],
        "ts": "2026-07-15T20:00:00Z",
    })


def test_flags_top_name_concentration():
    findings = concentration.analyze(_snap(), TH)
    # MSFT ~62% of book -> P1
    assert any(f.priority == Priority.P1 and "MSFT" in f.finding for f in findings)


def test_aggregates_same_symbol_rows_by_net_exposure():
    # AAA net = 60000 stock - 100 option = 59900, the largest name (~60% of 99900 gross).
    # The buggy dict-comprehension kept only AAA's last row (-100) and mis-reported BBB as top.
    findings = concentration.analyze(_multi_row_snap(), TH)
    top = findings[0]
    assert top.evidence["symbol"] == "AAA"
    assert abs(top.evidence["weight"] - (59900.0 / 99900.0)) < 1e-4


def test_build_chart_returns_figure():
    fig = concentration.build_chart(_snap())
    assert isinstance(fig, go.Figure)


def _fx_snap() -> Snapshot:
    """USD stock + SGD stock; the SGD row must be converted before weighting."""
    usd = _pos("USDX", "STK", 10000.0, currency="USD")           # fx_rate defaults 1.0
    sgd = {**_pos("D05", "STK", 10000.0, currency="SGD"), "fx_rate": 0.5}
    return Snapshot.model_validate({
        "account": {"account_id": "U0", "base_currency": "USD",
                    "net_liquidation": 100000.0, "total_cash": 0.0,
                    "buying_power": 0.0, "ts": "2026-07-17T00:00:00Z"},
        "positions": [usd, sgd],
        "ts": "2026-07-17T00:00:00Z",
    })


def test_weights_convert_non_base_currency():
    """SGD market_value (10000 @ 0.5) is 5000 USD; USD weight must be 10000/15000."""
    findings = concentration.analyze(_fx_snap(), TH)
    top = findings[0]
    assert top.evidence["symbol"] == "USDX"
    # base gross = 10000 (USD) + 5000 (SGD->USD) = 15000
    assert abs(top.evidence["weight"] - (10000.0 / 15000.0)) < 1e-4
