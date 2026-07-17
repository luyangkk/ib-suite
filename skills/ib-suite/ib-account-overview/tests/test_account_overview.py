# skills/ib-suite/ib-account-overview/tests/test_account_overview.py
"""Tests for the /ib-account-overview entrypoint.

Mirrors ib-gateway's test style: load the script by path, exercise the pure
build_overview() plus the offline orchestration via an injected FakeClient so
no network/IB access is needed. The live client is never constructed here.
"""
from pathlib import Path
from datetime import datetime, timezone
import json, importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "account_overview.py"
spec = importlib.util.spec_from_file_location("account_overview", SPEC)
account_overview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(account_overview)

FIX = Path(__file__).parent / "fixtures"


def test_build_overview_maps_all_account_fields():
    """All 10 requested account-level fields survive the raw -> typed mapping."""
    raw = json.loads((FIX / "ib_raw_overview_sample.json").read_text())
    ov = account_overview.build_overview(raw, datetime(2026, 7, 17, tzinfo=timezone.utc))

    assert ov.account_id == "U0000000"
    assert ov.base_currency == "USD"
    assert ov.net_liquidation == 408308.99
    assert ov.total_cash == 44752.56
    assert ov.buying_power == 1210892.38
    assert ov.margin_used == 111778.74
    assert ov.init_margin_req == 111778.74
    assert ov.maint_margin_req == 109414.84
    assert ov.excess_liquidity == 305094.72
    assert ov.daily_pnl == -4580.17
    assert ov.unrealized_pnl == -6946.92
    assert ov.realized_pnl == 0.0
    assert ov.ts == datetime(2026, 7, 17, tzinfo=timezone.utc)


def test_currency_balances_convert_to_base():
    """A non-base (SGD) balance is converted into base via its exchange_rate."""
    raw = json.loads((FIX / "ib_raw_overview_sample.json").read_text())
    ov = account_overview.build_overview(raw, datetime(2026, 7, 17, tzinfo=timezone.utc))

    by_ccy = {b.currency: b for b in ov.currency_balances}
    assert set(by_ccy) == {"USD", "SGD"}

    sgd = by_ccy["SGD"]
    assert sgd.exchange_rate == 0.7747392
    # 27.15 SGD cash -> USD
    assert sgd.base_cash_balance == 27.15 * 0.7747392
    # 7223.15 SGD net-liq -> USD
    assert sgd.base_net_liquidation == 7223.15 * 0.7747392

    usd = by_ccy["USD"]
    assert usd.exchange_rate == 1.0
    assert usd.base_cash_balance == 44731.52


def test_overview_orchestration_uses_injected_client():
    """overview() runs fully offline against a fake read-only client and
    returns a plain dict (parseable stdout) carrying every field."""
    raw = json.loads((FIX / "ib_raw_overview_sample.json").read_text())

    class FakeClient:
        """Stand-in for a read-only IB Gateway session."""
        disconnected = False
        def fetch_raw(self):
            return raw
        def disconnect(self):
            FakeClient.disconnected = True

    # minimal config: base currency comes from the account, storage unused here
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        cfg_path = os.path.join(d, "config.yaml")
        Path(cfg_path).write_text("data:\n  base_currency: USD\n")
        out = account_overview.overview(
            cfg_path,
            client_factory=lambda cfg: FakeClient(),
            now=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
        )

    assert FakeClient.disconnected is True          # connection always closed
    assert out["account_id"] == "U0000000"
    assert out["net_liquidation"] == 408308.99
    assert out["excess_liquidity"] == 305094.72
    assert out["daily_pnl"] == -4580.17
    assert out["base_currency"] == "USD"
    # multi-currency section present and base-converted
    ccys = {c["currency"] for c in out["currency_balances"]}
    assert ccys == {"USD", "SGD"}


def test_module_never_imports_order_apis():
    """Read-only guarantee: the module source must not touch any order path."""
    src = SPEC.read_text()
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
        assert forbidden not in src, f"order API {forbidden!r} must never appear"
