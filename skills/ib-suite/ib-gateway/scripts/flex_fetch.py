"""Flex Web Service client + XML parsers (read-only historical data).

Two-step handshake: SendRequest returns a ReferenceCode + statement URL,
GetStatement returns the report XML. Parsers convert the XML into typed
ib_common rows. Free of charge and covers history beyond the ~7-day
reqExecutions window.
"""
from __future__ import annotations
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
import requests

from ib_common.schema import Dividend, Execution, FlexTrade

_FLEX_BASE = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
)
_FLEX_HEADERS = {"User-Agent": "Python/3 ib-suite/0.1"}


class FlexServiceError(RuntimeError):
    """A credential-safe error returned by IBKR Flex Version 3."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"IBKR Flex error {code}: {message}")


def _raise_flex_error(root: ET.Element) -> None:
    """Raise a sanitized service error when a Version 3 response failed."""
    code = root.findtext("ErrorCode")
    if code:
        message = root.findtext("ErrorMessage") or "Unknown Flex service error."
        raise FlexServiceError(code, message)


def _parse_date(s: str) -> date:
    """Parse Flex date fields which may be 'YYYY-MM-DD' or 'YYYYMMDD'."""
    s = s.split(";")[0].strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def parse_flex_dividends(xml_text: str) -> list[Dividend]:
    """Extract dividend cash transactions into Dividend rows."""
    root = ET.fromstring(xml_text)
    out: list[Dividend] = []
    for ct in root.iter("CashTransaction"):
        if "Dividend" not in (ct.get("type") or ""):
            continue
        out.append(Dividend(
            symbol=ct.get("symbol", ""),
            ex_date=_parse_date(ct.get("dateTime", "1970-01-01")),
            pay_date=_parse_date(ct.get("settleDate")) if ct.get("settleDate") else None,
            gross=float(ct.get("amount", 0.0)),
            tax=0.0,
            currency=ct.get("currency", ""),
        ))
    return out


def _parse_datetime(value: str) -> datetime:
    """Parse a required Flex execution timestamp as UTC."""
    normalized = value.strip()
    for fmt in ("%Y-%m-%d;%H:%M:%S", "%Y%m%d;%H%M%S"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"invalid Flex dateTime: {value!r}")


def _required(trade: ET.Element, name: str) -> str:
    """Return one required Flex Trade attribute with a configuration hint."""
    value = trade.get(name)
    if value is None or not value.strip():
        raise ValueError(
            f"Flex Trade field {name!r} is missing; enable it in the Flex Query Trades section"
        )
    return value


def _present(trade: ET.Element, name: str) -> str:
    """Return an attribute that may be empty, rejecting an omitted query field."""
    value = trade.get(name)
    if value is None:
        raise ValueError(
            f"Flex Trade field {name!r} is missing; enable it in the Flex Query Trades section"
        )
    return value


def parse_flex_trade_records(xml_text: str) -> list[FlexTrade]:
    """Extract complete Flex execution rows for the trade-history skill."""
    root = ET.fromstring(xml_text)
    rows: list[FlexTrade] = []
    for trade in root.iter("Trade"):
        fx_text = trade.get("fxRateToBase")
        multiplier_text = (trade.get("multiplier") or "").strip()
        rows.append(FlexTrade(
            exec_id=_required(trade, "tradeID"),
            ts=_parse_datetime(_required(trade, "dateTime")),
            symbol=_required(trade, "symbol"),
            side=_required(trade, "buySell").upper(),
            quantity=abs(float(_required(trade, "quantity"))),
            price=float(_required(trade, "tradePrice")),
            commission=abs(float(_required(trade, "ibCommission"))),
            currency=_required(trade, "currency").upper(),
            commission_currency=_required(trade, "ibCommissionCurrency").upper(),
            multiplier=float(multiplier_text) if multiplier_text else 1.0,
            order_type=_present(trade, "orderType"),
            exchange=_required(trade, "exchange"),
            open_close=(trade.get("openCloseIndicator") or "").upper(),
            realized_pnl=float(_required(trade, "fifoPnlRealized")),
            fx_rate_to_base=float(fx_text) if fx_text not in (None, "") else None,
        ))
    return rows


def parse_flex_trades(xml_text: str) -> list[Execution]:
    """Extract trades into Execution rows."""
    root = ET.fromstring(xml_text)
    out: list[Execution] = []
    for tr in root.iter("Trade"):
        out.append(Execution(
            exec_id=tr.get("tradeID", ""),
            symbol=tr.get("symbol", ""),
            side=tr.get("buySell", ""),
            quantity=abs(float(tr.get("quantity", 0.0))),
            price=float(tr.get("tradePrice", 0.0)),
            commission=abs(float(tr.get("ibCommission", 0.0))),
            ts=datetime.combine(_parse_date(tr.get("tradeDate", "1970-01-01")),
                                datetime.min.time()),
        ))
    return out


def fetch_flex_report(token: str, query_id: str, http_get=requests.get,
                      poll_interval: float = 1.0, max_polls: int = 10) -> str:
    """Run the Flex two-step handshake and return raw statement XML."""
    send = http_get(
        f"{_FLEX_BASE}/SendRequest",
        params={"t": token, "q": query_id, "v": "3"},
        headers=_FLEX_HEADERS,
    )
    send.raise_for_status()
    root = ET.fromstring(send.text)
    _raise_flex_error(root)
    ref = root.findtext("ReferenceCode")
    url = (
        root.findtext("url")
        or root.findtext("Url")
        or f"{_FLEX_BASE}/GetStatement"
    )
    if not ref:
        raise RuntimeError("Flex SendRequest succeeded without a reference code")

    for _ in range(max_polls):
        stmt = http_get(
            url,
            params={"t": token, "q": ref, "v": "3"},
            headers=_FLEX_HEADERS,
        )
        stmt.raise_for_status()
        statement_root = ET.fromstring(stmt.text)
        if "Statement generation in progress" in stmt.text:
            time.sleep(poll_interval)
            continue
        _raise_flex_error(statement_root)
        return stmt.text
    return stmt.text
