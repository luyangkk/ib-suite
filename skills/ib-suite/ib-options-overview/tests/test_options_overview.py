"""Tests for pure option position mapping and risk aggregation."""
from __future__ import annotations

from datetime import date, datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from ib_common.config import load_config


SPEC = Path(__file__).parent.parent / "scripts" / "options_overview.py"
spec = importlib.util.spec_from_file_location("options_overview", SPEC)
options_overview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(options_overview)

FIX = Path(__file__).parent / "fixtures"
REPORT_DATE = date(2026, 7, 18)
TS = datetime(2026, 7, 18, tzinfo=timezone.utc)


def _raw() -> dict:
    """Load the deterministic option fixture."""
    return json.loads((FIX / "ib_raw_options_sample.json").read_text())


def test_build_options_maps_contract_fields_and_inclusive_dte():
    """The mapper preserves contract fields and counts both DTE endpoints."""
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    call = overview.options[0]
    assert call.underlying_symbol == "AAPL"
    assert call.right == "CALL"
    assert call.position_side == "LONG"
    assert call.days_to_expiry == 35
    assert call.moneyness == "ITM"


def test_build_options_scales_signed_greeks_and_daily_theta():
    """Greek totals use signed quantity, multiplier, and FX."""
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    assert overview.summary.total_delta == 140.0
    assert overview.summary.total_gamma == 4.0
    assert overview.summary.total_theta == -24.0
    assert overview.summary.total_vega == 60.0
    assert overview.summary.daily_time_value_decay == 24.0
    assert overview.summary.greek_coverage["delta"].contributing_contracts == 2
    excluded = overview.summary.greek_coverage["delta"].excluded_contracts
    assert len(excluded) == 1
    assert "MSFT" in excluded[0]


def test_missing_greeks_are_null_and_excluded_with_limitations():
    """Unavailable model data is preserved as null and described explicitly."""
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    msft = next(row for row in overview.options if row.underlying_symbol == "MSFT")
    assert msft.delta is None
    assert msft.moneyness is None
    assert any("MSFT" in item for item in overview.data_limitations)


def test_absolute_value_concentration_does_not_net_long_short_legs():
    """Concentration sums absolute base market value across offsetting positions."""
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    aapl = overview.summary.underlying_concentration[0]
    assert aapl.underlying_symbol == "AAPL"
    assert aapl.absolute_base_market_value == 3500.0
    assert aapl.weight == 3500.0 / 4000.0


def test_expiration_distribution_is_chronological():
    """Expiration buckets are ordered by their date regardless of input order."""
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)

    assert [bucket.expiry_date for bucket in overview.summary.expiration_distribution] == [
        date(2026, 8, 21),
        date(2026, 9, 18),
    ]


def test_empty_option_book_has_empty_distributions_and_null_greek_totals():
    """An empty options list is a valid book with no aggregate Greek values."""
    raw = _raw()
    raw["options"] = []

    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)

    assert overview.options == []
    assert overview.summary.total_delta is None
    assert overview.summary.total_gamma is None
    assert overview.summary.total_theta is None
    assert overview.summary.total_vega is None
    assert overview.summary.daily_time_value_decay is None
    assert overview.summary.expiration_distribution == []
    assert overview.summary.underlying_concentration == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expiry_date", "not-a-date"),
        ("multiplier", "1.5"),
    ],
)
def test_malformed_contract_field_names_the_contract_and_field(field, value):
    """Invalid contract fields are rejected with actionable contract diagnostics."""
    raw = _raw()
    raw["options"][0][field] = value

    with pytest.raises(ValueError, match=rf"AAPL-20260821-C-200.*{field}"):
        options_overview.build_options_overview(raw, REPORT_DATE, TS)


def test_missing_fx_rate_leaves_foreign_currency_base_fields_null():
    """A foreign-currency position without FX remains unconverted and disclosed."""
    raw = _raw()
    foreign = raw["options"][0]
    foreign["currency"] = "EUR"
    foreign["fx_rate"] = None

    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)

    position = overview.options[0]
    assert position.base_market_value is None
    assert position.base_unrealized_pnl is None
    assert any("missing FX rate" in item for item in overview.data_limitations)


def test_partial_fx_coverage_keeps_convertible_expiry_and_underlying_exposure():
    """One missing FX rate does not erase convertible exposure in its groups."""
    raw = _raw()
    missing_fx = raw["options"][1]
    missing_fx["currency"] = "EUR"
    missing_fx["fx_rate"] = None

    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)

    expiry = overview.summary.expiration_distribution[0]
    aapl = overview.summary.underlying_concentration[0]
    assert expiry.absolute_base_market_value == 2500.0
    assert expiry.base_market_value_coverage == 0.5
    assert aapl.underlying_symbol == "AAPL"
    assert aapl.absolute_base_market_value == 2500.0
    assert aapl.base_market_value_coverage == 0.5
    assert aapl.weight == 2500.0 / 3000.0
    assert any(
        "AAPL" in limitation and "partial base market value coverage" in limitation
        for limitation in overview.data_limitations
    )


def test_invalid_right_names_contract_and_right_field():
    """Unsupported option rights fail before a misleading moneyness is emitted."""
    raw = _raw()
    raw["options"][0]["right"] = "STRADDLE"
    raw["options"][0]["underlying_price"] = None

    with pytest.raises(ValueError, match=r"AAPL-20260821-C-200.*right"):
        options_overview.build_options_overview(raw, REPORT_DATE, TS)


def test_missing_option_market_price_stays_null_with_limitation():
    """An unavailable option quote is preserved rather than coercively converted."""
    raw = _raw()
    raw["options"][0]["market_price"] = None

    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)

    position = overview.options[0]
    assert position.market_price is None
    assert any(
        "AAPL" in limitation and "missing market price" in limitation
        for limitation in overview.data_limitations
    )


def test_nan_option_market_price_stays_null_with_limitation():
    """IB's unavailable market-price sentinel does not leak into JSON output."""
    raw = _raw()
    raw["options"][0]["market_price"] = math.nan

    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)
    position = overview.options[0]

    assert position.market_price is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (210.5, 210.5),
        ("210.5", 210.5),
        (None, None),
        (math.nan, None),
        (math.inf, None),
        (0.0, None),
        (-1.0, None),
    ],
)
def test_usable_underlying_price_rejects_ib_sentinels(value, expected):
    assert options_overview._usable_underlying_price(value) == expected


def test_wait_until_stops_as_soon_as_data_is_ready():
    class FakeIB:
        elapsed = 0.0

        def sleep(self, seconds):
            self.elapsed += seconds

    ib = FakeIB()
    options_overview._wait_until(
        ib,
        lambda: ib.elapsed >= 0.5,
        timeout_s=20.0,
        poll_s=0.25,
    )
    assert ib.elapsed == 0.5


def test_wait_until_stops_at_timeout_when_data_never_arrives():
    class FakeIB:
        elapsed = 0.0

        def sleep(self, seconds):
            self.elapsed += seconds

    ib = FakeIB()
    options_overview._wait_until(
        ib,
        lambda: False,
        timeout_s=20.0,
        poll_s=0.25,
    )
    assert ib.elapsed == 20.0


def test_orchestration_uses_injected_client_and_disconnects(tmp_path):
    """The Gateway orchestration emits JSON-safe data and closes its client."""
    class FakeClient:
        """Offline stand-in for a read-only IB Gateway session."""

        disconnected = False

        def fetch_raw(self):
            """Return the deterministic option-book fixture."""
            return _raw()

        def disconnect(self):
            """Record that the session was closed."""
            FakeClient.disconnected = True

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("data:\n  base_currency: USD\n")

    out = options_overview.options_overview(
        str(cfg_path),
        client_factory=lambda cfg: FakeClient(),
        now=lambda: TS,
    )

    assert FakeClient.disconnected is True
    assert out["account_id"] == "U0000000"
    assert out["summary"]["daily_time_value_decay"] == 24.0


def test_orchestration_disconnects_when_gateway_fetch_fails(tmp_path):
    """The Gateway session closes even when fetching the option book fails."""
    class FailingClient:
        """Offline client that fails during acquisition."""

        disconnected = False

        def fetch_raw(self):
            """Simulate an IB Gateway acquisition failure."""
            raise RuntimeError("Gateway unavailable")

        def disconnect(self):
            """Record that the session was closed."""
            FailingClient.disconnected = True

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("data:\n  base_currency: USD\n")

    with pytest.raises(RuntimeError, match="Gateway unavailable"):
        options_overview.options_overview(
            str(cfg_path),
            client_factory=lambda cfg: FailingClient(),
            now=lambda: TS,
        )

    assert FailingClient.disconnected is True


def test_live_client_collects_option_greeks_and_cancels_market_data(
    monkeypatch, tmp_path
):
    """The read-only Gateway client maps option data and closes every quote."""
    contract = SimpleNamespace(
        conId=1,
        symbol="AAPL",
        secType="OPT",
        currency="USD",
        lastTradeDateOrContractMonth="20260821",
        right="C",
        strike=200.0,
        multiplier="100",
    )
    ticker = SimpleNamespace(
        contract=contract,
        modelGreeks=SimpleNamespace(
            impliedVol=0.25,
            delta=0.5,
            gamma=0.03,
            theta=-0.14,
            vega=0.4,
            undPrice=210.0,
        ),
        marketPrice=lambda: 12.5,
    )

    class FakeIB:
        """Record the read-only operations made by the live client."""

        instance = None

        def __init__(self):
            """Create an inspectable fake Gateway connection."""
            FakeIB.instance = self
            self.connect_kwargs = None
            self.market_data_types = []
            self.cancelled = []
            self.disconnected = False

        def connect(self, *args, **kwargs):
            """Record the connection arguments."""
            self.connect_kwargs = (args, kwargs)

        def reqMarketDataType(self, market_data_type):
            """Record the requested market-data tier."""
            self.market_data_types.append(market_data_type)

        def managedAccounts(self):
            """Return one deterministic account."""
            return ["U0000000"]

        def accountValues(self, account_id=None):
            """Return account base currency and local-to-base FX."""
            return [
                SimpleNamespace(tag="Currency", value="USD", currency="BASE"),
                SimpleNamespace(
                    tag="$LEDGER-ExchangeRate", value="1.0", currency="USD"
                ),
            ]

        def portfolio(self, account_id):
            """Return one IB-valued option position."""
            return [
                SimpleNamespace(
                    contract=contract,
                    position=2,
                    averageCost=1000.0,
                    marketValue=2500.0,
                    unrealizedPNL=500.0,
                )
            ]

        def reqMktData(self, requested_contract, generic_tick_list, snapshot, regulatory_snapshot):
            """Return the deterministic option ticker."""
            assert requested_contract is contract
            assert (generic_tick_list, snapshot, regulatory_snapshot) == ("", False, False)
            return ticker

        def sleep(self, seconds):
            """Accept the bounded collection-window wait."""
            assert seconds == 4.0

        def cancelMktData(self, requested_contract):
            """Record the closed market-data subscription."""
            self.cancelled.append(requested_contract)

        def disconnect(self):
            """Record connection cleanup."""
            self.disconnected = True

    class FakeStock:
        """Record any unexpected fallback underlying contract construction."""

        constructed = []

        def __init__(self, symbol, exchange, currency):
            FakeStock.constructed.append((symbol, exchange, currency))

    monkeypatch.setitem(
        sys.modules,
        "ib_async",
        SimpleNamespace(IB=FakeIB, Stock=FakeStock),
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("connection:\n  market_data_type: delayed\n")

    client = options_overview._default_client_factory(load_config(cfg_path))
    raw = client.fetch_raw()
    client.disconnect()

    fake = FakeIB.instance
    assert fake.connect_kwargs[1]["readonly"] is True
    assert fake.market_data_types == [3]
    assert fake.cancelled == [contract]
    assert fake.disconnected is True
    assert FakeStock.constructed == []
    assert raw["options"] == [
        {
            "contract_id": "AAPL-20260821-C-200",
            "underlying_symbol": "AAPL",
            "right": "CALL",
            "strike": 200.0,
            "expiry_date": "20260821",
            "multiplier": "100",
            "quantity": 2,
            "avg_cost": 1000.0,
            "market_price": 12.5,
            "market_value": 2500.0,
            "unrealized_pnl": 500.0,
            "currency": "USD",
            "fx_rate": 1.0,
            "implied_volatility": 0.25,
            "delta": 0.5,
            "gamma": 0.03,
            "theta": -0.14,
            "vega": 0.4,
            "underlying_price": 210.0,
        }
    ]


def test_live_client_reuses_shared_model_price_without_fallback_wait(
    monkeypatch, tmp_path
):
    """One option model price resolves every matching row without quote waiting."""
    option_contracts = [
        SimpleNamespace(
            conId=index,
            symbol="AAPL",
            secType="OPT",
            currency="USD",
            lastTradeDateOrContractMonth="20260821",
            right="C",
            strike=strike,
            multiplier="100",
        )
        for index, strike in ((1, 200.0), (2, 205.0))
    ]
    option_tickers = {
        1: SimpleNamespace(
            modelGreeks=SimpleNamespace(
                impliedVol=0.25,
                delta=0.5,
                gamma=0.03,
                theta=-0.14,
                vega=0.4,
                undPrice=210.0,
            ),
            marketPrice=lambda: 12.5,
        ),
        2: SimpleNamespace(
            modelGreeks=None,
            marketPrice=lambda: 12.5,
        ),
    }

    class FakeStock:
        """Record any unnecessary independent underlying construction."""

        constructed = []

        def __init__(self, symbol, exchange, currency):
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.secType = "STK"
            FakeStock.constructed.append(self)

    class FakeIB:
        """Keep an independent quote unavailable if one is requested."""

        instance = None

        def __init__(self):
            FakeIB.instance = self
            self.cancelled = []
            self.qualified = []
            self.underlying_subscribed = False
            self.underlying_elapsed = 0.0

        def connect(self, *args, **kwargs):
            pass

        def reqMarketDataType(self, market_data_type):
            pass

        def managedAccounts(self):
            return ["U0000000"]

        def accountValues(self, account_id=None):
            return [
                SimpleNamespace(tag="Currency", value="USD", currency="BASE"),
                SimpleNamespace(
                    tag="$LEDGER-ExchangeRate", value="1.0", currency="USD"
                ),
            ]

        def portfolio(self, account_id):
            return [
                SimpleNamespace(
                    contract=contract,
                    position=1,
                    averageCost=1000.0,
                    marketValue=2500.0,
                    unrealizedPNL=500.0,
                )
                for contract in option_contracts
            ]

        def qualifyContracts(self, *contracts):
            self.qualified.extend(contracts)
            return list(contracts)

        def reqMktData(self, contract, generic_tick_list, snapshot, regulatory_snapshot):
            if contract.secType == "OPT":
                return option_tickers[contract.conId]
            self.underlying_subscribed = True
            return SimpleNamespace(close=None, marketPrice=lambda: math.nan)

        def sleep(self, seconds):
            if self.underlying_subscribed:
                self.underlying_elapsed += seconds

        def cancelMktData(self, contract):
            self.cancelled.append(contract)

        def disconnect(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "ib_async",
        SimpleNamespace(IB=FakeIB, Stock=FakeStock),
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("connection:\n  market_data_type: delayed\n")

    raw = options_overview._default_client_factory(load_config(cfg_path)).fetch_raw()

    fake = FakeIB.instance
    assert FakeStock.constructed == []
    assert fake.qualified == []
    assert fake.underlying_elapsed == 0.0
    assert [row["underlying_price"] for row in raw["options"]] == [210.0, 210.0]
    assert fake.cancelled == option_contracts
    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)
    assert [row.moneyness for row in overview.options] == ["ITM", "ITM"]


def test_live_client_deduplicates_quote_when_all_matching_models_are_missing(
    monkeypatch, tmp_path
):
    """Two matching missing models share one qualified underlying quote."""
    option_contracts = [
        SimpleNamespace(
            conId=index,
            symbol="AAPL",
            secType="OPT",
            currency="USD",
            lastTradeDateOrContractMonth="20260821",
            right="C",
            strike=strike,
            multiplier="100",
        )
        for index, strike in ((1, 200.0), (2, 205.0))
    ]

    class FakeStock:
        """Build and record the single requested underlying contract."""

        constructed = []

        def __init__(self, symbol, exchange, currency):
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.secType = "STK"
            FakeStock.constructed.append(self)

    class FakeIB:
        """Publish the shared underlying quote after half a second."""

        instance = None

        def __init__(self):
            FakeIB.instance = self
            self.cancelled = []
            self.qualify_calls = []
            self.underlying_requests = []
            self.fallback_elapsed = 0.0
            self.underlying_ticker = SimpleNamespace(
                close=None,
                marketPrice=lambda: math.nan,
            )

        def connect(self, *args, **kwargs):
            pass

        def reqMarketDataType(self, market_data_type):
            pass

        def managedAccounts(self):
            return ["U0000000"]

        def accountValues(self, account_id=None):
            return [SimpleNamespace(tag="Currency", value="USD", currency="BASE")]

        def portfolio(self, account_id):
            return [
                SimpleNamespace(
                    contract=contract,
                    position=1,
                    averageCost=1000.0,
                    marketValue=2500.0,
                    unrealizedPNL=500.0,
                )
                for contract in option_contracts
            ]

        def qualifyContracts(self, *contracts):
            self.qualify_calls.append(contracts)
            return list(contracts)

        def reqMktData(self, contract, generic_tick_list, snapshot, regulatory_snapshot):
            if contract.secType == "OPT":
                return SimpleNamespace(modelGreeks=None, marketPrice=lambda: 12.5)
            self.underlying_requests.append(contract)
            return self.underlying_ticker

        def sleep(self, seconds):
            if self.underlying_requests:
                self.fallback_elapsed += seconds
                if self.fallback_elapsed >= 0.5:
                    self.underlying_ticker.marketPrice = lambda: 210.0

        def cancelMktData(self, contract):
            self.cancelled.append(contract)

        def disconnect(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "ib_async",
        SimpleNamespace(IB=FakeIB, Stock=FakeStock),
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("connection:\n  market_data_type: delayed\n")

    raw = options_overview._default_client_factory(load_config(cfg_path)).fetch_raw()

    fake = FakeIB.instance
    assert [
        (stock.symbol, stock.exchange, stock.currency)
        for stock in FakeStock.constructed
    ] == [("AAPL", "SMART", "USD")]
    assert fake.qualify_calls == [tuple(FakeStock.constructed)]
    assert fake.underlying_requests == FakeStock.constructed
    assert fake.fallback_elapsed == 0.5
    assert [row["underlying_price"] for row in raw["options"]] == [210.0, 210.0]
    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)
    assert [row.moneyness for row in overview.options] == ["ITM", "ITM"]
    assert {id(contract) for contract in fake.cancelled} == {
        id(contract) for contract in [*option_contracts, FakeStock.constructed[0]]
    }


@pytest.mark.parametrize("failed_symbol", ["AAPL", "MSFT"])
def test_live_client_preserves_identity_when_qualification_omits_a_contract(
    monkeypatch, tmp_path, failed_symbol
):
    """A shortened qualification result maps its quote by contract identity."""
    option_contracts = [
        SimpleNamespace(
            conId=index,
            symbol=symbol,
            secType="OPT",
            currency="USD",
            lastTradeDateOrContractMonth="20260821",
            right="C",
            strike=200.0,
            multiplier="100",
        )
        for index, symbol in ((1, "AAPL"), (2, "MSFT"))
    ]

    class FakeStock:
        """Build identity-bearing underlying contracts."""

        def __init__(self, symbol, exchange, currency):
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.secType = "STK"

    class FakeIB:
        """Omit the first requested qualification as ib_async 1.x may do."""

        instance = None

        def __init__(self):
            FakeIB.instance = self
            self.cancelled = []
            self.omitted = None
            self.returned = None

        def connect(self, *args, **kwargs):
            pass

        def reqMarketDataType(self, market_data_type):
            pass

        def managedAccounts(self):
            return ["U0000000"]

        def accountValues(self, account_id=None):
            return [SimpleNamespace(tag="Currency", value="USD", currency="BASE")]

        def portfolio(self, account_id):
            return [
                SimpleNamespace(
                    contract=contract,
                    position=1,
                    averageCost=1000.0,
                    marketValue=2500.0,
                    unrealizedPNL=500.0,
                )
                for contract in option_contracts
            ]

        def qualifyContracts(self, *contracts):
            contracts_by_symbol = {contract.symbol: contract for contract in contracts}
            self.omitted = contracts_by_symbol[failed_symbol]
            self.returned = next(
                contract
                for symbol, contract in contracts_by_symbol.items()
                if symbol != failed_symbol
            )
            return [self.returned]

        def reqMktData(self, contract, generic_tick_list, snapshot, regulatory_snapshot):
            if contract.secType == "OPT":
                return SimpleNamespace(modelGreeks=None, marketPrice=lambda: 12.5)
            return SimpleNamespace(close=None, marketPrice=lambda: 210.0)

        def sleep(self, seconds):
            pass

        def cancelMktData(self, contract):
            self.cancelled.append(contract)

        def disconnect(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "ib_async",
        SimpleNamespace(IB=FakeIB, Stock=FakeStock),
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("connection:\n  market_data_type: delayed\n")

    raw = options_overview._default_client_factory(load_config(cfg_path)).fetch_raw()

    fake = FakeIB.instance
    prices = {row["underlying_symbol"]: row["underlying_price"] for row in raw["options"]}
    assert prices[fake.omitted.symbol] is None
    assert prices[fake.returned.symbol] == 210.0
    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)
    moneyness = {row.underlying_symbol: row.moneyness for row in overview.options}
    assert moneyness[fake.omitted.symbol] is None
    assert moneyness[fake.returned.symbol] == "ITM"
    assert {id(contract) for contract in fake.cancelled} == {
        id(contract) for contract in [*option_contracts, fake.returned]
    }


def test_quoted_underlying_price_prefers_market_price_and_then_close():
    """A valid quote wins; an IB NaN sentinel falls back to the prior close."""
    ticker = SimpleNamespace(close=205.0, marketPrice=lambda: 210.0)
    assert options_overview._quoted_underlying_price(ticker) == 210.0

    ticker.marketPrice = lambda: math.nan
    assert options_overview._quoted_underlying_price(ticker) == 205.0


def test_live_client_skips_none_qualified_underlying_contract(monkeypatch, tmp_path):
    """A missing qualification keeps only that underlying unclassified."""
    option_contracts = [
        SimpleNamespace(
            conId=index,
            symbol=symbol,
            secType="OPT",
            currency="USD",
            lastTradeDateOrContractMonth="20260821",
            right="C",
            strike=200.0,
            multiplier="100",
        )
        for index, symbol in ((1, "AAPL"), (2, "MSFT"))
    ]

    class FakeStock:
        """Build a stock contract directly from the requested underlying key."""

        constructed = []

        def __init__(self, symbol, exchange, currency):
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.secType = "STK"
            FakeStock.constructed.append(self)

    class FakeIB:
        """Return one MSFT quote while AAPL qualification fails."""

        instance = None

        def __init__(self):
            FakeIB.instance = self
            self.cancelled = []

        def connect(self, *args, **kwargs):
            pass

        def reqMarketDataType(self, market_data_type):
            pass

        def managedAccounts(self):
            return ["U0000000"]

        def accountValues(self, account_id=None):
            return [SimpleNamespace(tag="Currency", value="USD", currency="BASE")]

        def portfolio(self, account_id):
            return [
                SimpleNamespace(
                    contract=contract,
                    position=1,
                    averageCost=1000.0,
                    marketValue=2500.0,
                    unrealizedPNL=500.0,
                )
                for contract in option_contracts
            ]

        def qualifyContracts(self, *contracts):
            return [None if contract.symbol == "AAPL" else contract for contract in contracts]

        def reqMktData(self, contract, generic_tick_list, snapshot, regulatory_snapshot):
            assert contract is not None
            if contract.secType == "OPT":
                return SimpleNamespace(modelGreeks=None, marketPrice=lambda: 12.5)
            return SimpleNamespace(
                close=None,
                marketPrice=(lambda: 210.0) if contract.symbol == "MSFT" else (lambda: math.nan),
            )

        def sleep(self, seconds):
            pass

        def cancelMktData(self, contract):
            self.cancelled.append(contract)

        def disconnect(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "ib_async",
        SimpleNamespace(IB=FakeIB, Stock=FakeStock),
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("connection:\n  market_data_type: delayed\n")

    raw = options_overview._default_client_factory(load_config(cfg_path)).fetch_raw()

    assert [row["underlying_price"] for row in raw["options"]] == [None, 210.0]
    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)
    assert [row.moneyness for row in overview.options] == [None, "ITM"]
    assert any(
        "AAPL" in limitation and "missing underlying price" in limitation
        for limitation in overview.data_limitations
    )
    assert {id(contract) for contract in FakeIB.instance.cancelled} == {
        id(contract)
        for contract in [
            *option_contracts,
            next(stock for stock in FakeStock.constructed if stock.symbol == "MSFT"),
        ]
    }


def test_live_client_waits_full_timeout_for_only_unavailable_underlying(
    monkeypatch, tmp_path
):
    """One unavailable quote waits 20 seconds without hiding a ready symbol."""
    option_contracts = [
        SimpleNamespace(
            conId=index,
            symbol=symbol,
            secType="OPT",
            currency="USD",
            lastTradeDateOrContractMonth="20260821",
            right="C",
            strike=200.0,
            multiplier="100",
        )
        for index, symbol in ((1, "AAPL"), (2, "MSFT"))
    ]

    class FakeStock:
        """Build and record each independent underlying contract."""

        constructed = []

        def __init__(self, symbol, exchange, currency):
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.secType = "STK"
            FakeStock.constructed.append(self)

    class FakeIB:
        """Keep only MSFT unavailable for the entire bounded fallback wait."""

        instance = None

        def __init__(self):
            FakeIB.instance = self
            self.cancelled = []
            self.underlying_requests = []
            self.fallback_elapsed = 0.0

        def connect(self, *args, **kwargs):
            pass

        def reqMarketDataType(self, market_data_type):
            pass

        def managedAccounts(self):
            return ["U0000000"]

        def accountValues(self, account_id=None):
            return [SimpleNamespace(tag="Currency", value="USD", currency="BASE")]

        def portfolio(self, account_id):
            return [
                SimpleNamespace(
                    contract=contract,
                    position=1,
                    averageCost=1000.0,
                    marketValue=2500.0,
                    unrealizedPNL=500.0,
                )
                for contract in option_contracts
            ]

        def qualifyContracts(self, *contracts):
            return list(contracts)

        def reqMktData(self, contract, generic_tick_list, snapshot, regulatory_snapshot):
            if contract.secType == "OPT":
                return SimpleNamespace(modelGreeks=None, marketPrice=lambda: 12.5)
            self.underlying_requests.append(contract)
            return SimpleNamespace(
                close=None,
                marketPrice=(
                    (lambda: 210.0)
                    if contract.symbol == "AAPL"
                    else (lambda: math.nan)
                ),
            )

        def sleep(self, seconds):
            if self.underlying_requests:
                self.fallback_elapsed += seconds

        def cancelMktData(self, contract):
            self.cancelled.append(contract)

        def disconnect(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "ib_async",
        SimpleNamespace(IB=FakeIB, Stock=FakeStock),
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("connection:\n  market_data_type: delayed\n")

    raw = options_overview._default_client_factory(load_config(cfg_path)).fetch_raw()

    fake = FakeIB.instance
    assert fake.fallback_elapsed == 20.0
    assert {contract.symbol for contract in fake.underlying_requests} == {
        "AAPL",
        "MSFT",
    }
    assert [row["underlying_price"] for row in raw["options"]] == [210.0, None]
    overview = options_overview.build_options_overview(raw, REPORT_DATE, TS)
    assert [row.moneyness for row in overview.options] == ["ITM", None]
    assert any(
        "MSFT" in limitation and "missing underlying price" in limitation
        for limitation in overview.data_limitations
    )
    assert {id(contract) for contract in fake.cancelled} == {
        id(contract) for contract in [*option_contracts, *FakeStock.constructed]
    }


def test_live_client_cancels_partial_underlying_subscriptions_on_error(
    monkeypatch, tmp_path
):
    """Cleanup closes options and any already-opened underlying subscriptions."""
    option_contracts = [
        SimpleNamespace(
            conId=index,
            symbol=symbol,
            secType="OPT",
            currency="USD",
            lastTradeDateOrContractMonth="20260821",
            right="C",
            strike=200.0,
            multiplier="100",
        )
        for index, symbol in ((1, "AAPL"), (2, "MSFT"))
    ]

    class FakeStock:
        """Build a stock contract directly from the requested underlying key."""

        constructed = []

        def __init__(self, symbol, exchange, currency):
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency
            self.secType = "STK"
            FakeStock.constructed.append(self)

    class FakeIB:
        """Raise during the second underlying subscription after opening the first."""

        instance = None

        def __init__(self):
            FakeIB.instance = self
            self.cancelled = []
            self.underlying_requests = 0

        def connect(self, *args, **kwargs):
            pass

        def reqMarketDataType(self, market_data_type):
            pass

        def managedAccounts(self):
            return ["U0000000"]

        def accountValues(self, account_id=None):
            return [SimpleNamespace(tag="Currency", value="USD", currency="BASE")]

        def portfolio(self, account_id):
            return [
                SimpleNamespace(
                    contract=contract,
                    position=1,
                    averageCost=1000.0,
                    marketValue=2500.0,
                    unrealizedPNL=500.0,
                )
                for contract in option_contracts
            ]

        def qualifyContracts(self, *contracts):
            return list(contracts)

        def reqMktData(self, contract, generic_tick_list, snapshot, regulatory_snapshot):
            if contract.secType == "OPT":
                return SimpleNamespace(modelGreeks=None, marketPrice=lambda: 12.5)
            self.underlying_requests += 1
            if self.underlying_requests == 2:
                raise RuntimeError("underlying quote unavailable")
            return SimpleNamespace(close=210.0, marketPrice=lambda: math.nan)

        def sleep(self, seconds):
            pass

        def cancelMktData(self, contract):
            self.cancelled.append(contract)

        def disconnect(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "ib_async",
        SimpleNamespace(IB=FakeIB, Stock=FakeStock),
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("connection:\n  market_data_type: delayed\n")

    with pytest.raises(RuntimeError, match="underlying quote unavailable"):
        options_overview._default_client_factory(load_config(cfg_path)).fetch_raw()

    fake = FakeIB.instance
    assert {id(contract) for contract in fake.cancelled} == {
        id(contract) for contract in [*option_contracts, FakeStock.constructed[0]]
    }


def test_module_never_imports_order_apis():
    """Read-only guarantee: this source must never touch an order path."""
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
        assert forbidden not in SPEC.read_text()


def test_skill_instructs_grouped_moneyness_presentation():
    skill = (SPEC.parent.parent / "SKILL.md").read_text(encoding="utf-8")

    assert "group positions by `moneyness`" in skill
    assert "ITM, ATM, OTM, and UNKNOWN" in skill
    assert "absolute difference between `underlying_price` and `strike`" in skill
    assert "user's language" in skill


def test_base_currency_falls_back_to_net_liquidation_currency():
    """IB accounts without a Currency tag use NetLiquidation's quote currency."""
    values = [
        SimpleNamespace(tag="NetLiquidation", value="100000", currency="USD"),
    ]

    assert options_overview._account_base_currency(values) == "USD"
