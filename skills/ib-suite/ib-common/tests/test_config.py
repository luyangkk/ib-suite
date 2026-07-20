# skills/ib-common/tests/test_config.py
from datetime import date
from pathlib import Path
import pytest
from ib_common.config import load_config, resolve_base_currency
from ib_common.schema import TradeHistoryReport, TradeHistorySummary

FIX = Path(__file__).parent / "fixtures"

def test_load_config_applies_defaults():
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.connection.read_only is True          # default must be read-only
    assert cfg.data.freshness_hours == 24.0          # default freshness
    assert cfg.connection.port == 4002               # paper default

def test_base_currency_follows_account_when_present():
    cfg = load_config(FIX / "config_minimal.yaml")
    assert resolve_base_currency(cfg, "HKD") == "HKD"   # account setting wins

def test_base_currency_falls_back_to_config():
    cfg = load_config(FIX / "config_minimal.yaml")
    assert resolve_base_currency(cfg, None) == "USD"    # config override

def test_base_currency_missing_raises():
    cfg = load_config(FIX / "config_minimal.yaml")
    cfg.data.base_currency = None
    with pytest.raises(ValueError):
        resolve_base_currency(cfg, None)


def test_market_data_type_defaults_to_delayed():
    """Accounts without a live subscription still get delayed marks by default."""
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.connection.market_data_type == "delayed"


def test_flex_config_defaults_to_empty_credentials():
    """Configs without Flex settings expose empty workspace-local credentials."""
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.flex.token is None
    assert cfg.flex.trade_history_query_ids == {}
    assert cfg.flex.dividend_query_ids == {}


def test_flex_query_ids_parsed_as_string_keyed_maps(tmp_path):
    """Window keys load as strings on both maps; integer keys coerce to digits."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n"
        "  trade_history_query_ids:\n    7: q7\n    mtd: qm\n"
        "  dividend_query_ids:\n    365: q365\n    ytd: qy\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.flex.trade_history_query_ids == {"7": "q7", "mtd": "qm"}
    assert cfg.flex.dividend_query_ids == {"365": "q365", "ytd": "qy"}


def test_stale_query_ids_key_is_ignored(tmp_path):
    """The removed shared key no longer populates either map (hard cutover)."""
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    7: q7\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.flex.trade_history_query_ids == {}
    assert cfg.flex.dividend_query_ids == {}


def test_flex_query_ids_reject_unknown_string_key(tmp_path):
    """A non-period, non-numeric key is a configuration error on either map."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  dividend_query_ids:\n    foo: x\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="invalid Flex window key"):
        load_config(path)


@pytest.mark.parametrize("bad", ["0", "-3"])
def test_flex_query_ids_reject_nonpositive_day_key(tmp_path, bad):
    """Numeric day keys must be strictly positive on either map."""
    path = tmp_path / "config.yaml"
    path.write_text(
        f"flex:\n  trade_history_query_ids:\n    '{bad}': x\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="invalid Flex window key"):
        load_config(path)


def test_options_market_data_defaults_to_disabled():
    """Default is the free mode: no option market-data requests, no snapshot fees."""
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.options.fetch_market_data is False


def test_options_market_data_can_be_enabled():
    """Explicit true opts into Greeks/IV subscription (may incur snapshot fees)."""
    cfg = load_config(FIX / "config_options_market_data.yaml")
    assert cfg.options.fetch_market_data is True


def _empty_summary() -> TradeHistorySummary:
    return TradeHistorySummary(
        total_trades=0, buy_count=0, sell_count=0,
        total_notional=0.0, total_commission=0.0,
        profitable_trades=0, losing_trades=0,
        win_rate=None, average_profit=None, average_loss=None,
        profit_loss_ratio=None,
    )


def test_report_coverage_note_defaults_to_null():
    """A report without coverage gaps serializes coverage_note as null."""
    report = TradeHistoryReport(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
        base_currency="USD", trades=[], summary=_empty_summary(),
    )
    assert report.coverage_note is None
    assert report.model_dump(mode="json")["coverage_note"] is None
