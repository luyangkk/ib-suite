# skills/ib-common/tests/test_config.py
from pathlib import Path
import pytest
from ib_common.config import load_config, resolve_base_currency

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
    assert cfg.flex.query_ids == {}


def test_flex_query_ids_parsed_as_int_keyed_map(tmp_path):
    """Window days become integer keys mapping to Flex Query IDs."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n  query_ids:\n    7: q7\n    30: q30\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.flex.query_ids == {7: "q7", 30: "q30"}


def test_load_config_rejects_legacy_single_query_id(tmp_path):
    """The retired single query_id key must direct users to query_ids."""
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_id: legacy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="query_ids"):
        load_config(path)


def test_options_market_data_defaults_to_disabled():
    """Default is the free mode: no option market-data requests, no snapshot fees."""
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.options.fetch_market_data is False


def test_options_market_data_can_be_enabled():
    """Explicit true opts into Greeks/IV subscription (may incur snapshot fees)."""
    cfg = load_config(FIX / "config_options_market_data.yaml")
    assert cfg.options.fetch_market_data is True
