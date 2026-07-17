# skills/ib-gateway/scripts/ib_sync.py
"""/ib-sync entrypoint: pull read-only account + positions and land to the lake.

The live connection is isolated behind `client_factory` so business logic
(build_snapshot, storage) is fully testable against fixtures. This module
NEVER imports order-placing APIs — read-only by construction.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path

from ib_common.config import load_config, resolve_base_currency
from ib_common.schema import Account, Position, Snapshot
from ib_common.storage import write_snapshot, append_timeseries


def build_snapshot(raw: dict, ts: datetime) -> Snapshot:
    """Convert a raw account+positions dict into a typed, base-currency-checked Snapshot."""
    acct_raw = raw["account"]
    base = acct_raw.get("base_currency")
    account = Account(
        account_id=acct_raw["account_id"],
        base_currency=base,
        net_liquidation=float(acct_raw["net_liquidation"]),
        total_cash=float(acct_raw["total_cash"]),
        buying_power=float(acct_raw["buying_power"]),
        ts=ts,
    )
    positions: list[Position] = []
    for p in raw["positions"]:
        mkt_val = float(p["quantity"]) * float(p["market_price"])
        cost_val = float(p["quantity"]) * float(p["avg_cost"])
        positions.append(Position(
            account_id=account.account_id,
            symbol=p["symbol"],
            sec_type=p["sec_type"],
            currency=p["currency"],
            quantity=float(p["quantity"]),
            avg_cost=float(p["avg_cost"]),
            market_price=float(p["market_price"]),
            market_value=mkt_val,
            unrealized_pnl=mkt_val - cost_val,
        ))
    return Snapshot(account=account, positions=positions, ts=ts)


def _default_client_factory(cfg):
    """Build a read-only IB Gateway client. Imported lazily to keep tests offline."""
    from ib_async import IB  # local import: no network dependency at import time

    class _LiveClient:
        def __init__(self, cfg):
            self.ib = IB()
            self.ib.connect(cfg.connection.host, cfg.connection.port,
                            clientId=cfg.connection.client_id,
                            readonly=True)   # hard read-only

        def fetch_raw(self) -> dict:
            summary = {v.tag: v.value for v in self.ib.accountSummary()}
            acct_id = self.ib.managedAccounts()[0]
            positions = []
            for p in self.ib.positions():
                c = p.contract
                positions.append({
                    "symbol": c.symbol, "sec_type": c.secType,
                    "currency": c.currency, "quantity": p.position,
                    "avg_cost": p.avgCost,
                    "market_price": p.avgCost,  # replaced by mkt data in later plan
                })
            return {
                "account": {
                    "account_id": acct_id,
                    "base_currency": summary.get("Currency", "USD"),
                    "net_liquidation": float(summary.get("NetLiquidation", 0)),
                    "total_cash": float(summary.get("TotalCashValue", 0)),
                    "buying_power": float(summary.get("BuyingPower", 0)),
                },
                "positions": positions,
            }

        def disconnect(self):
            self.ib.disconnect()

    return _LiveClient(cfg)


def sync(cfg_path: str, client_factory=None, now=None) -> dict:
    """Load config, pull data via a read-only client, land snapshot + time-series."""
    cfg = load_config(cfg_path)
    now = now or (lambda: datetime.now(timezone.utc))
    client_factory = client_factory or _default_client_factory

    client = client_factory(cfg)
    try:
        raw = client.fetch_raw()
    finally:
        client.disconnect()

    # enforce base-currency policy (account wins over config)
    raw["account"]["base_currency"] = resolve_base_currency(
        cfg, raw["account"].get("base_currency"))

    snap = build_snapshot(raw, now())
    snap_path = write_snapshot(snap, cfg.storage.root)
    ts_path = append_timeseries(snap.positions, cfg.storage.root, "positions_history")
    return {"snapshot": str(snap_path), "timeseries": str(ts_path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync read-only IB data to the local lake.")
    parser.add_argument("--config", required=True, help="path to config.yaml")
    args = parser.parse_args()
    result = sync(args.config)
    print(result)
