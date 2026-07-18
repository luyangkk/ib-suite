"""Tests for pure option position mapping and risk aggregation."""
from __future__ import annotations

from datetime import date, datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest


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


def test_invalid_right_names_contract_and_right_field():
    """Unsupported option rights fail before a misleading moneyness is emitted."""
    raw = _raw()
    raw["options"][0]["right"] = "STRADDLE"

    with pytest.raises(ValueError, match=r"AAPL-20260821-C-200.*right"):
        options_overview.build_options_overview(raw, REPORT_DATE, TS)
