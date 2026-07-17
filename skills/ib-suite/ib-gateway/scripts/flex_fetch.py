"""Flex Web Service client + XML parsers (read-only historical data).

Two-step handshake: SendRequest returns a ReferenceCode + statement URL,
GetStatement returns the report XML. Parsers convert the XML into typed
ib_common rows. Free of charge and covers history beyond the ~7-day
reqExecutions window.
"""
from __future__ import annotations
import time
import xml.etree.ElementTree as ET
from datetime import datetime, date
import requests

from ib_common.schema import Dividend, Execution

_FLEX_BASE = "https://gdcdyn.interactivebrokers.com/Universal/servlet"


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
    send = http_get(f"{_FLEX_BASE}/FlexStatementService.SendRequest",
                    params={"t": token, "q": query_id, "v": "3"})
    send.raise_for_status()
    root = ET.fromstring(send.text)
    ref = root.findtext("ReferenceCode")
    url = root.findtext("Url") or f"{_FLEX_BASE}/FlexStatementService.GetStatement"
    if not ref:
        raise RuntimeError(f"Flex SendRequest failed: {send.text[:200]}")

    for _ in range(max_polls):
        stmt = http_get(url, params={"t": token, "q": ref, "v": "3"})
        stmt.raise_for_status()
        if "Statement generation in progress" not in stmt.text:
            return stmt.text
        time.sleep(poll_interval)
    return stmt.text
