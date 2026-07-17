# skills/ib-portfolio-analyst/tests/test_account_health.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Snapshot
from ib_analyst import account_health
from ib_analyst.findings import Priority

FIX = Path(__file__).parent / "fixtures"
TH = {"cash_ratio_warn": 0.10, "cash_ratio_crit": 0.05,
      "leverage_warn": 1.5, "leverage_crit": 2.0}


def _snap():
    return Snapshot.model_validate_json((FIX / "snapshot_diag.json").read_text())


def test_reports_leverage_and_cash():
    findings = account_health.analyze(_snap(), TH)
    dims = {f.dimension for f in findings}
    assert "account_health" in dims
    # snapshot_diag has ~2x leverage and thin cash => at least one P1
    assert any(f.priority == Priority.P1 for f in findings)


def test_findings_are_complete():
    for f in account_health.analyze(_snap(), TH):
        assert f.finding and f.impact and f.suggestion and f.trigger_condition
        assert 0.0 <= f.confidence <= 1.0


def test_leverage_converts_non_base_currency():
    """Gross leverage must use base-currency values, not raw mixed-currency sums."""
    snap = Snapshot.model_validate({
        "account": {"account_id": "U0", "base_currency": "USD",
                    "net_liquidation": 10000.0, "total_cash": 0.0,
                    "buying_power": 0.0, "ts": "2026-07-17T00:00:00Z"},
        "positions": [
            {"account_id": "U0", "symbol": "D05", "sec_type": "STK",
             "currency": "SGD", "quantity": 1.0, "avg_cost": 0.0,
             "market_price": 0.0, "market_value": 20000.0,
             "unrealized_pnl": 0.0, "fx_rate": 0.5},
        ],
        "ts": "2026-07-17T00:00:00Z",
    })
    lev = next(f for f in account_health.analyze(snap, TH)
               if "leverage" in f.finding.lower())
    # 20000 SGD @ 0.5 = 10000 USD gross / 10000 NLV = 1.0x, not 2.0x
    assert abs(lev.evidence["leverage"] - 1.0) < 1e-6
