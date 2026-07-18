"""Read-only IBKR Flex trade-history entrypoint."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ib-gateway" / "scripts"))

from flex_fetch import fetch_flex_report, parse_flex_trade_records
from ib_common.config import Config, load_config
from ib_common.schema import FlexTrade, TradeHistoryReport, TradeHistorySummary


def parse_iso_date(value: str) -> date:
    """Parse an ISO calendar date or raise an actionable argument error."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def resolve_period(start: str | None, end: str | None, today: date) -> tuple[date, date]:
    """Resolve explicit inclusive bounds or the default seven-calendar-day period."""
    if (start is None) != (end is None):
        raise ValueError("--start-date and --end-date must be supplied together")
    if start is None:
        return today - timedelta(days=6), today
    start_date, end_date = parse_iso_date(start), parse_iso_date(end)
    if start_date > end_date:
        raise ValueError("--start-date must be on or before --end-date")
    return start_date, end_date


def resolve_flex_credentials(cfg: Config, environ: Mapping[str, str]) -> tuple[str, str]:
    """Return one complete Flex credential pair from config or environment."""
    config_pair = (cfg.flex.token, cfg.flex.query_id)
    if all(config_pair):
        return config_pair
    if any(config_pair):
        raise ValueError("config.flex.token and config.flex.query_id must both be configured")
    env_pair = (environ.get("FLEX_TOKEN"), environ.get("FLEX_QUERY_ID"))
    if all(env_pair):
        return env_pair
    if any(env_pair):
        raise ValueError("FLEX_TOKEN and FLEX_QUERY_ID must both be configured")
    raise ValueError(
        "Flex credentials are not configured; run ib-trade-history setup or set both environment variables"
    )


def _normalize_fx(trades: list[FlexTrade], base_currency: str) -> list[FlexTrade]:
    """Set base-currency rates to one and reject missing foreign-currency FX."""
    for trade in trades:
        trade._commission_fx_rate_to_base = None
        if trade.currency == base_currency:
            trade.fx_rate_to_base = 1.0
        elif trade.fx_rate_to_base is None:
            raise ValueError(
                f"Flex Trade {trade.exec_id} has no fxRateToBase for {trade.currency}; "
                "enable FX Rate to Base in the Flex Query Trades section"
            )
        elif not math.isfinite(trade.fx_rate_to_base) or trade.fx_rate_to_base <= 0:
            raise ValueError(
                f"Flex Trade {trade.exec_id} has invalid fxRateToBase "
                f"{trade.fx_rate_to_base!r} for {trade.currency}; configure a finite, "
                "positive FX Rate to Base in the Flex Query Trades section"
            )
        if trade.commission_currency == trade.currency:
            continue
        if trade.commission_currency == base_currency:
            trade._commission_fx_rate_to_base = 1.0
            continue
        raise ValueError(
            f"Flex Trade {trade.exec_id} commission currency {trade.commission_currency} "
            f"differs from asset currency {trade.currency}; configure an independent "
            "commission FX rate before reporting base-currency totals"
        )
    return trades


def summarize(trades: list[FlexTrade]) -> TradeHistorySummary:
    """Return base-currency counts and realized-P&L statistics for execution rows."""
    for trade in trades:
        if trade.fx_rate_to_base is None:
            raise ValueError(
                f"Flex Trade {trade.exec_id} has no fxRateToBase for {trade.currency}; "
                "enable FX Rate to Base in the Flex Query Trades section"
            )
        if trade.base_commission is None:
            raise ValueError(
                f"Flex Trade {trade.exec_id} has no base conversion for commission "
                f"currency {trade.commission_currency}"
            )
    profits = [
        trade.base_realized_pnl
        for trade in trades
        if trade.base_realized_pnl and trade.base_realized_pnl > 0
    ]
    losses = [
        trade.base_realized_pnl
        for trade in trades
        if trade.base_realized_pnl and trade.base_realized_pnl < 0
    ]
    average_profit = sum(profits) / len(profits) if profits else None
    average_loss = sum(losses) / len(losses) if losses else None
    closed_count = len(profits) + len(losses)
    return TradeHistorySummary(
        total_trades=len(trades),
        buy_count=sum(trade.side == "BUY" for trade in trades),
        sell_count=sum(trade.side == "SELL" for trade in trades),
        total_notional=sum(trade.base_notional or 0.0 for trade in trades),
        total_commission=sum(trade.base_commission or 0.0 for trade in trades),
        profitable_trades=len(profits),
        losing_trades=len(losses),
        win_rate=len(profits) / closed_count if closed_count else None,
        average_profit=average_profit,
        average_loss=average_loss,
        profit_loss_ratio=(
            average_profit / abs(average_loss)
            if average_profit is not None and average_loss is not None
            else None
        ),
    )


def build_report(
    trades: list[FlexTrade], start_date: date, end_date: date, base_currency: str
) -> TradeHistoryReport:
    """Filter Flex fills by inclusive date and assemble the typed response."""
    if start_date > end_date:
        raise ValueError("start date must be on or before end date")
    in_range = [trade for trade in trades if start_date <= trade.ts.date() <= end_date]
    normalized = _normalize_fx(in_range, base_currency)
    return TradeHistoryReport(
        start_date=start_date,
        end_date=end_date,
        base_currency=base_currency,
        trades=normalized,
        summary=summarize(normalized),
    )


def trade_history(
    config_path: str,
    start: str | None,
    end: str | None,
    fetcher: Callable[[str, str], str] = fetch_flex_report,
    today: date | None = None,
    environ: dict[str, str] | None = None,
) -> dict:
    """Fetch Flex trades once and return a JSON-safe inclusive-period report."""
    cfg = load_config(config_path)
    base_currency = (cfg.data.base_currency or "").upper()
    if not base_currency:
        raise ValueError(
            "data.base_currency is required for Flex trade-history conversion; "
            "set it in .ib-suite/config.yaml"
        )
    env = os.environ if environ is None else environ
    token, query_id = resolve_flex_credentials(cfg, env)
    start_date, end_date = resolve_period(start, end, today or date.today())
    try:
        xml_text = fetcher(token, query_id)
    except (requests.RequestException, RuntimeError, ET.ParseError, ValueError):
        raise RuntimeError(
            "Flex report retrieval failed; verify FLEX_TOKEN, FLEX_QUERY_ID, "
            "Flex Query settings, and service status"
        ) from None
    try:
        records = parse_flex_trade_records(xml_text)
    except ET.ParseError:
        raise RuntimeError(
            "Flex response is not a valid report; check the Flex Query and service status"
        ) from None
    return build_report(records, start_date, end_date, base_currency).model_dump(mode="json")


def main() -> None:
    """Parse CLI arguments and print exactly one JSON object on success."""
    parser = argparse.ArgumentParser(description="Read-only IBKR Flex trade history")
    parser.add_argument("--config", required=True, help="path to config.yaml")
    parser.add_argument("--start-date", help="inclusive YYYY-MM-DD start date")
    parser.add_argument("--end-date", help="inclusive YYYY-MM-DD end date")
    args = parser.parse_args()
    try:
        print(json.dumps(trade_history(args.config, args.start_date, args.end_date)))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
