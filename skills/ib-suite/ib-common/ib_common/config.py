# skills/ib-common/ib_common/config.py
"""Central configuration loading and base-currency resolution.

One config.yaml drives every skill. Unspecified fields fall back to safe
defaults defined here (read-only, paper port, 24h freshness).
"""
from __future__ import annotations
from pathlib import Path
from ruamel.yaml import YAML
from pydantic import BaseModel, Field


class ConnectionCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4002            # IB Gateway paper default; live is 4001
    client_id: int = 17
    read_only: bool = True      # never flip silently; read-only by default
    market_data_type: str = "delayed"  # delayed marks work without a live subscription


class DataCfg(BaseModel):
    freshness_hours: float = 24.0
    base_currency: str | None = None   # None => follow account BASE at runtime


class StorageCfg(BaseModel):
    root: str = "./data"


class FlexCfg(BaseModel):
    """Workspace-local IBKR Flex credentials for the trade-history skill."""

    token: str | None = None
    query_ids: dict[int, str] = Field(default_factory=dict)


class OptionsCfg(BaseModel):
    """Option-overview behaviour toggles."""

    # False (default): skip every option market-data request. No Greeks/IV, but
    # zero IBKR snapshot-fee risk. Set True to briefly subscribe for Greeks/IV.
    fetch_market_data: bool = False


class Config(BaseModel):
    connection: ConnectionCfg = Field(default_factory=ConnectionCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    flex: FlexCfg = Field(default_factory=FlexCfg)
    options: OptionsCfg = Field(default_factory=OptionsCfg)
    thresholds: dict[str, float] = Field(default_factory=dict)


def load_config(path: str | Path) -> Config:
    """Load and validate config.yaml, applying defaults for missing keys."""
    yaml = YAML(typ="safe")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.load(f) or {}
    return Config(**raw)


def resolve_base_currency(cfg: Config, account_base: str | None) -> str:
    """Resolve report base currency. Account setting wins over config.

    Order: account BASE (from Gateway) -> config.data.base_currency -> error.
    """
    if account_base:
        return account_base
    if cfg.data.base_currency:
        return cfg.data.base_currency
    raise ValueError("base currency unresolved: no account BASE and no config default")
