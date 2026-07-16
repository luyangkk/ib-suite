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
