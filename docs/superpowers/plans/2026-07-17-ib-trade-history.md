# IB Trade History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only `/ib-trade-history` skill that downloads IBKR Flex Query trades for an inclusive date range and prints per-fill records plus a base-currency performance summary.

**Architecture:** Keep the existing `Execution` model and offline analyst contract unchanged. Add a typed `FlexTrade` record to `ib_common`, extend the existing read-only Flex XML parser to populate it, and make the new entry script orchestrate fetch, local date filtering, FX validation, and deterministic aggregation. The script does not write a lake artifact and accesses credentials only through environment variables.

**Tech Stack:** Python 3.11+, Pydantic v2, `argparse`, `requests`, `xml.etree.ElementTree`, `ruamel.yaml`, `pytest`.

## Global Constraints

- Every Python module starts with `from __future__ import annotations`; public functions have English docstrings and type annotations.
- Do not add dependencies; use the shared editable `ib-common` package and existing `requests` dependency.
- The skill is read-only: it may call only the IBKR Flex Web Service, imports no order API, and never connects to IB Gateway.
- Never persist Flex XML, trades, tokens, or account credentials. Print exactly one structured JSON object to stdout on success.
- Read `FLEX_TOKEN` and `FLEX_QUERY_ID` only from environment variables; do not echo them in errors or logs.
- Require `data.base_currency` in the supplied config. Flex `fxRateToBase` identifies the conversion rate but does not reliably identify the base currency name.
- A user-provided period uses inclusive `YYYY-MM-DD` bounds. With neither date argument, default to today and the preceding six calendar dates.
- Preserve each fill: never merge multiple rows of one order. Use IBKR `fifoPnlRealized`, never reconstruct lot matching.
- Do not commit without an explicit user instruction.

## File Structure

- Modify: `skills/ib-suite/ib-common/ib_common/schema.py`
  - Add `FlexTrade`, `TradeHistorySummary`, and `TradeHistoryReport` Pydantic models.
- Modify: `skills/ib-suite/ib-common/tests/test_schema.py`
  - Assert the new computed base-currency fields and JSON serialization.
- Modify: `skills/ib-suite/ib-gateway/scripts/flex_fetch.py`
  - Add strict Flex datetime/number helpers and `parse_flex_trade_records()`.
- Modify: `skills/ib-suite/ib-gateway/tests/test_flex_fetch.py`
  - Validate the extended parser against a safe XML fixture.
- Modify: `skills/ib-suite/ib-gateway/tests/fixtures/flex_response_sample.xml`
  - Add the fields required by the extended parser without exposing real data.
- Create: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`
  - Implement period validation, FX validation, aggregation, Flex orchestration, and CLI.
- Create: `skills/ib-suite/ib-trade-history/tests/fixtures/flex_trade_history_sample.xml`
  - Supply deterministic USD and SGD fills, a winning close, a losing close, a zero-P&L open, and an out-of-range row.
- Create: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`
  - Test pure functions, injected Flex fetch orchestration, validation errors, and command metadata.
- Create: `skills/ib-suite/ib-trade-history/SKILL.md`
  - Register the slash command, Flex prerequisites, date-resolution behavior, executable command, output contract, and no-order boundary.
- Modify: `skills/ib-suite/SKILL.md`
  - Add `ib-trade-history` to directory overview, routing table, dependency guide, and direct invocation examples.

---

### Task 1: Add Typed Flex Trade and Report Models

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/schema.py`
- Modify: `skills/ib-suite/ib-common/tests/test_schema.py`

**Interfaces:**
- Produces `FlexTrade`, a raw Flex execution row with optional `fx_rate_to_base`.
- Produces `TradeHistorySummary` and `TradeHistoryReport`, the response contract consumed by `trade_history.py`.
- `FlexTrade.base_notional`, `base_commission`, and `base_realized_pnl` raise no errors and return `None` until an FX rate is available.

- [ ] **Step 1: Write the failing schema tests**

Append the following test to `skills/ib-suite/ib-common/tests/test_schema.py`:

```python
from datetime import date, datetime, timezone
from ib_common.schema import FlexTrade, TradeHistoryReport, TradeHistorySummary


def test_flex_trade_exposes_original_and_base_currency_amounts():
    """Trade-history rows retain local amounts and derive base amounts from Flex FX."""
    row = FlexTrade(
        exec_id="T-2",
        ts=datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc),
        symbol="D05",
        side="SELL",
        quantity=100.0,
        price=40.0,
        commission=4.0,
        currency="SGD",
        order_type="LMT",
        exchange="SGX",
        open_close="C",
        realized_pnl=200.0,
        fx_rate_to_base=0.75,
    )

    assert row.notional == 4000.0
    assert row.base_notional == 3000.0
    assert row.base_commission == 3.0
    assert row.base_realized_pnl == 150.0

    report = TradeHistoryReport(
        start_date=date(2026, 7, 9),
        end_date=date(2026, 7, 15),
        base_currency="USD",
        trades=[row],
        summary=TradeHistorySummary(
            total_trades=1, buy_count=0, sell_count=1, total_notional=3000.0,
            total_commission=3.0, profitable_trades=1, losing_trades=0,
            win_rate=1.0, average_profit=150.0, average_loss=None,
            profit_loss_ratio=None,
        ),
    )
    assert report.model_dump(mode="json")["trades"][0]["base_realized_pnl"] == 150.0
```

- [ ] **Step 2: Run the schema test to verify it fails**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_schema.py::test_flex_trade_exposes_original_and_base_currency_amounts -q
```

Expected: FAIL because `FlexTrade`, `TradeHistorySummary`, and `TradeHistoryReport` are not importable.

- [ ] **Step 3: Add the minimal Pydantic models**

After `Execution` in `skills/ib-suite/ib-common/ib_common/schema.py`, add:

```python
class FlexTrade(BaseModel):
    """One IBKR Flex Trade execution with local and optional base FX amounts."""

    exec_id: str
    ts: datetime
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    currency: str
    order_type: str
    exchange: str
    open_close: str
    realized_pnl: float
    fx_rate_to_base: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def notional(self) -> float:
        """Absolute local-currency execution notional."""
        return abs(self.quantity * self.price)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_notional(self) -> float | None:
        """Execution notional converted by Flex's local-to-base FX rate."""
        return None if self.fx_rate_to_base is None else self.notional * self.fx_rate_to_base

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_commission(self) -> float | None:
        """Absolute commission converted by Flex's local-to-base FX rate."""
        return None if self.fx_rate_to_base is None else abs(self.commission) * self.fx_rate_to_base

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_realized_pnl(self) -> float | None:
        """IBKR FIFO realized P&L converted by Flex's local-to-base FX rate."""
        return None if self.fx_rate_to_base is None else self.realized_pnl * self.fx_rate_to_base


class TradeHistorySummary(BaseModel):
    """Base-currency aggregate statistics for an inclusive trade period."""

    total_trades: int
    buy_count: int
    sell_count: int
    total_notional: float
    total_commission: float
    profitable_trades: int
    losing_trades: int
    win_rate: float | None
    average_profit: float | None
    average_loss: float | None
    profit_loss_ratio: float | None


class TradeHistoryReport(BaseModel):
    """Read-only Flex trade records and their base-currency summary."""

    start_date: date
    end_date: date
    base_currency: str
    trades: list[FlexTrade]
    summary: TradeHistorySummary
```

- [ ] **Step 4: Run the schema test to verify it passes**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_schema.py::test_flex_trade_exposes_original_and_base_currency_amounts -q
```

Expected: PASS.

### Task 2: Extend the Shared Flex Parser

**Files:**
- Modify: `skills/ib-suite/ib-gateway/scripts/flex_fetch.py`
- Modify: `skills/ib-suite/ib-gateway/tests/test_flex_fetch.py`
- Modify: `skills/ib-suite/ib-gateway/tests/fixtures/flex_response_sample.xml`

**Interfaces:**
- Consumes a Flex XML document with `Trade` attributes `dateTime`, `tradeID`, `symbol`, `buySell`, `quantity`, `tradePrice`, `ibCommission`, `currency`, `orderType`, `exchange`, `openCloseIndicator`, `fifoPnlRealized`, and optional `fxRateToBase`.
- Produces `parse_flex_trade_records(xml_text: str) -> list[FlexTrade]`.
- Continues to produce the existing `parse_flex_trades(xml_text: str) -> list[Execution]` output unchanged for `/ib-analyze`.

- [ ] **Step 1: Write the failing extended-parser test**

Append to `skills/ib-suite/ib-gateway/tests/test_flex_fetch.py`:

```python
def test_parse_flex_trade_records_keeps_required_trade_history_fields():
    """The extended parser exposes each Flex fill without changing Execution."""
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    rows = flex.parse_flex_trade_records(xml_text)

    assert len(rows) == 1
    row = rows[0]
    assert row.exec_id == "T1"
    assert row.ts.isoformat() == "2026-02-01T15:30:00+00:00"
    assert row.order_type == "LMT"
    assert row.exchange == "NASDAQ"
    assert row.open_close == "O"
    assert row.realized_pnl == 0.0
    assert row.fx_rate_to_base == 1.0
```

- [ ] **Step 2: Run the parser test to verify it fails**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py::test_parse_flex_trade_records_keeps_required_trade_history_fields -q
```

Expected: FAIL because `parse_flex_trade_records` does not exist.

- [ ] **Step 3: Make the fixture express the real contract**

Replace the existing `<Trade .../>` row in
`skills/ib-suite/ib-gateway/tests/fixtures/flex_response_sample.xml` with:

```xml
<Trade symbol="AAPL" buySell="BUY" quantity="100" tradePrice="150.00"
       ibCommission="-1.00" tradeDate="2026-02-01"
       dateTime="2026-02-01;15:30:00" tradeID="T1" currency="USD"
       orderType="LMT" exchange="NASDAQ" openCloseIndicator="O"
       fifoPnlRealized="0.00" fxRateToBase="1.00"/>
```

- [ ] **Step 4: Implement strict datetime parsing and record extraction**

In `skills/ib-suite/ib-gateway/scripts/flex_fetch.py`, import `timezone` and
`FlexTrade`. Add the following functions before `parse_flex_trades`:

```python
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


def parse_flex_trade_records(xml_text: str) -> list[FlexTrade]:
    """Extract complete Flex execution rows for the trade-history skill."""
    root = ET.fromstring(xml_text)
    rows: list[FlexTrade] = []
    for trade in root.iter("Trade"):
        fx_text = trade.get("fxRateToBase")
        rows.append(FlexTrade(
            exec_id=_required(trade, "tradeID"),
            ts=_parse_datetime(_required(trade, "dateTime")),
            symbol=_required(trade, "symbol"),
            side=_required(trade, "buySell").upper(),
            quantity=abs(float(_required(trade, "quantity"))),
            price=float(_required(trade, "tradePrice")),
            commission=abs(float(_required(trade, "ibCommission"))),
            currency=_required(trade, "currency").upper(),
            order_type=_required(trade, "orderType"),
            exchange=_required(trade, "exchange"),
            open_close=_required(trade, "openCloseIndicator").upper(),
            realized_pnl=float(_required(trade, "fifoPnlRealized")),
            fx_rate_to_base=float(fx_text) if fx_text not in (None, "") else None,
        ))
    return rows
```

Do not rewrite `parse_flex_trades`; its existing mapping intentionally remains
the compatibility path for `Execution`.

- [ ] **Step 5: Run parser regression tests**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-gateway/tests/test_flex_fetch.py -q
```

Expected: PASS for dividend parsing, legacy execution parsing, extended record
parsing, and the two-step handshake test.

### Task 3: Implement Deterministic Trade-History Aggregation

**Files:**
- Create: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`
- Create: `skills/ib-suite/ib-trade-history/tests/fixtures/flex_trade_history_sample.xml`
- Create: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`

**Interfaces:**
- Consumes `list[FlexTrade]`, `start_date: date`, `end_date: date`, and `base_currency: str`.
- Produces `summarize(trades: list[FlexTrade]) -> TradeHistorySummary`.
- Produces `build_report(trades: list[FlexTrade], start_date: date, end_date: date, base_currency: str) -> TradeHistoryReport`.
- Raises `ValueError` for inverted dates or a non-base-currency trade lacking `fxRateToBase`.

- [ ] **Step 1: Create the safe multi-currency Flex fixture**

Create `skills/ib-suite/ib-trade-history/tests/fixtures/flex_trade_history_sample.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements count="1">
    <FlexStatement accountId="U0000000">
      <Trades>
        <Trade tradeID="B1" dateTime="2026-07-09;09:30:00" symbol="AAPL" buySell="BUY"
               quantity="10" tradePrice="100" ibCommission="-1" currency="USD"
               orderType="LMT" exchange="NASDAQ" openCloseIndicator="O"
               fifoPnlRealized="0" fxRateToBase="1"/>
        <Trade tradeID="S1" dateTime="2026-07-10;10:00:00" symbol="AAPL" buySell="SELL"
               quantity="10" tradePrice="120" ibCommission="-1" currency="USD"
               orderType="LMT" exchange="NASDAQ" openCloseIndicator="C"
               fifoPnlRealized="200" fxRateToBase="1"/>
        <Trade tradeID="S2" dateTime="2026-07-11;11:00:00" symbol="D05" buySell="SELL"
               quantity="100" tradePrice="40" ibCommission="-4" currency="SGD"
               orderType="MKT" exchange="SGX" openCloseIndicator="C"
               fifoPnlRealized="-100" fxRateToBase="0.75"/>
        <Trade tradeID="OLD1" dateTime="2026-07-08;11:00:00" symbol="MSFT" buySell="SELL"
               quantity="1" tradePrice="300" ibCommission="-1" currency="USD"
               orderType="MKT" exchange="NASDAQ" openCloseIndicator="C"
               fifoPnlRealized="10" fxRateToBase="1"/>
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
```

- [ ] **Step 2: Write failing aggregation tests**

Create `skills/ib-suite/ib-trade-history/tests/test_trade_history.py` with this
initial pure-function test:

```python
from __future__ import annotations
from datetime import date
from pathlib import Path
import importlib.util

import pytest

SPEC = Path(__file__).parent.parent / "scripts" / "trade_history.py"
spec = importlib.util.spec_from_file_location("trade_history", SPEC)
trade_history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trade_history)


def test_build_report_filters_inclusively_and_aggregates_base_currency():
    """Every in-range fill survives and only Flex FX-converted money is summed."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)

    report = trade_history.build_report(
        rows, date(2026, 7, 9), date(2026, 7, 11), "USD"
    )

    assert [row.exec_id for row in report.trades] == ["B1", "S1", "S2"]
    assert report.summary.total_trades == 3
    assert report.summary.buy_count == 1
    assert report.summary.sell_count == 2
    assert report.summary.total_notional == 5200.0
    assert report.summary.total_commission == 5.0
    assert report.summary.profitable_trades == 1
    assert report.summary.losing_trades == 1
    assert report.summary.win_rate == 0.5
    assert report.summary.average_profit == 200.0
    assert report.summary.average_loss == -75.0
    assert report.summary.profit_loss_ratio == pytest.approx(200.0 / 75.0)


def test_build_report_rejects_missing_foreign_exchange_rate():
    """A mixed-currency total cannot silently assume an FX conversion."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)
    rows[2].fx_rate_to_base = None

    with pytest.raises(ValueError, match="fxRateToBase.*SGD"):
        trade_history.build_report(rows, date(2026, 7, 9), date(2026, 7, 11), "USD")
```

- [ ] **Step 3: Run the aggregation tests to verify they fail**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q
```

Expected: FAIL because `trade_history.py` does not exist.

- [ ] **Step 4: Implement validation, FX normalization, filtering, and summary**

Create `skills/ib-suite/ib-trade-history/scripts/trade_history.py` with:

```python
"""Read-only IBKR Flex trade-history entrypoint."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ib-gateway" / "scripts"))

from flex_fetch import fetch_flex_report, parse_flex_trade_records
from ib_common.config import load_config
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


def _normalize_fx(trades: list[FlexTrade], base_currency: str) -> list[FlexTrade]:
    """Set base-currency rates to one and reject missing foreign-currency FX."""
    for trade in trades:
        if trade.currency == base_currency:
            trade.fx_rate_to_base = 1.0
        elif trade.fx_rate_to_base is None:
            raise ValueError(
                f"Flex Trade {trade.exec_id} is {trade.currency} but has no fxRateToBase; "
                "enable FX Rate to Base in the Flex Query Trades section"
            )
    return trades


def summarize(trades: list[FlexTrade]) -> TradeHistorySummary:
    """Return base-currency counts and realized-P&L statistics for execution rows."""
    profits = [trade.base_realized_pnl for trade in trades if trade.base_realized_pnl and trade.base_realized_pnl > 0]
    losses = [trade.base_realized_pnl for trade in trades if trade.base_realized_pnl and trade.base_realized_pnl < 0]
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
            if average_profit is not None and average_loss is not None else None
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
```

Keep the module importable without performing network I/O. Add its CLI and
injected fetch orchestration in Task 4.

- [ ] **Step 5: Run the aggregation tests to verify they pass**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q
```

Expected: PASS for inclusive filtering, all requested summary fields, and
missing foreign-FX rejection.

### Task 4: Add Read-Only CLI, Skill Control Plane, and Index Routing

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`
- Modify: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`
- Create: `skills/ib-suite/ib-trade-history/SKILL.md`
- Modify: `skills/ib-suite/SKILL.md`

**Interfaces:**
- Produces `trade_history(config_path: str, start: str | None, end: str | None, fetcher: Callable[[str, str], str] = fetch_flex_report, today: date | None = None) -> dict`.
- CLI usage: `trade_history.py --config .ib-suite/config.yaml [--start-date YYYY-MM-DD --end-date YYYY-MM-DD]`.
- Requires `FLEX_TOKEN`, `FLEX_QUERY_ID`, and `data.base_currency`.

- [ ] **Step 1: Write the failing orchestration and metadata tests**

Append to `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`:

```python
def test_orchestration_uses_injected_flex_fetcher_and_default_period(tmp_path):
    """The executable fetches once, defaults to seven days, and emits JSON-safe data."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
    calls = []

    def fake_fetch(token: str, query_id: str) -> str:
        calls.append((token, query_id))
        return xml

    out = trade_history.trade_history(
        str(config), None, None, fetcher=fake_fetch, today=date(2026, 7, 11),
        environ={"FLEX_TOKEN": "test-token", "FLEX_QUERY_ID": "test-query"},
    )

    assert calls == [("test-token", "test-query")]
    assert out["start_date"] == "2026-07-05"
    assert out["end_date"] == "2026-07-11"
    assert [row["exec_id"] for row in out["trades"]] == ["B1", "S1", "S2", "OLD1"]


def test_orchestration_requires_base_currency_and_flex_environment(tmp_path):
    """The failure tells operators exactly which local setup is incomplete."""
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: null\n", encoding="utf-8")

    with pytest.raises(ValueError, match="data.base_currency"):
        trade_history.trade_history(
            str(config), "2026-07-09", "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse/>",
            environ={"FLEX_TOKEN": "x", "FLEX_QUERY_ID": "y"},
        )

    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
    with pytest.raises(ValueError, match="FLEX_TOKEN"):
        trade_history.trade_history(
            str(config), "2026-07-09", "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse/>", environ={},
        )


def test_skill_metadata_and_source_preserve_read_only_boundary():
    """The skill is discoverable, has exact runnable paths, and no order path."""
    skill = (Path(__file__).parent.parent / "SKILL.md").read_text(encoding="utf-8")
    source = SPEC.read_text(encoding="utf-8")
    assert "name: ib-trade-history" in skill
    assert "Read-only" in skill
    assert "{baseDir}/../.venv/bin/python {baseDir}/scripts/trade_history.py" in skill
    assert "FLEX_TOKEN" in skill and "FLEX_QUERY_ID" in skill
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
        assert forbidden not in source
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q
```

Expected: FAIL because `trade_history()` and `SKILL.md` do not yet exist.

- [ ] **Step 3: Implement injected Flex orchestration and argparse CLI**

Append the following to `skills/ib-suite/ib-trade-history/scripts/trade_history.py`:

```python
def trade_history(
    config_path: str,
    start: str | None,
    end: str | None,
    fetcher=fetch_flex_report,
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
    token, query_id = env.get("FLEX_TOKEN"), env.get("FLEX_QUERY_ID")
    if not token or not query_id:
        raise ValueError(
            "FLEX_TOKEN and FLEX_QUERY_ID are required; export both before running /ib-trade-history"
        )
    start_date, end_date = resolve_period(start, end, today or date.today())
    records = parse_flex_trade_records(fetcher(token, query_id))
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
```

- [ ] **Step 4: Create the skill control plane**

Create `skills/ib-suite/ib-trade-history/SKILL.md` with:

```markdown
---
name: ib-trade-history
description: Read-only Interactive Brokers trade history from Flex Query. Use when the user asks to list executions or fills for a date range, inspect buy and sell activity, commissions, order type, exchange, open/close status, realized FIFO P&L, win rate, average win/loss, or profit/loss ratio. Reads Flex records only — never places, modifies, or cancels an order.
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [config.yaml]
      env: [FLEX_TOKEN, FLEX_QUERY_ID]
    os: [darwin, linux]
---

# ib-trade-history

Read only the requested IBKR Flex Query trade history. Do not place, modify, or
cancel orders; do not start IB Gateway; do not write trade data to the lake.

## Prerequisites

Configure the Flex Query `Trades` section to include `dateTime`, `tradeID`,
`symbol`, `buySell`, `quantity`, `tradePrice`, `ibCommission`, `currency`,
`orderType`, `exchange`, `openCloseIndicator`, `fifoPnlRealized`, and
`fxRateToBase`. Its configured history window must cover the requested dates.

Set `data.base_currency` in `.ib-suite/config.yaml`, then expose the Flex
credentials only in the current shell:

```bash
export FLEX_TOKEN='...'
export FLEX_QUERY_ID='...'
```

## Command

For a date range, resolve the user's dates to inclusive `YYYY-MM-DD` values and run:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/trade_history.py \
  --config .ib-suite/config.yaml \
  --start-date 2026-07-01 \
  --end-date 2026-07-17
```

With no stated time range, omit both date arguments to query the latest seven
calendar days:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/trade_history.py \
  --config .ib-suite/config.yaml
```

Interpret “this month” as the first day of the current month through today;
interpret “last month” as the previous calendar month; ask one clarifying
question for ambiguous phrases such as “recently”.

The script prints one JSON object with `trades` and `summary`. Each fill keeps
its original currency and has Flex-converted base-currency values. `FIFO P/L`
is IBKR's realized P&L; do not recompute lots. Zero-P&L fills are excluded from
win rate. `profit_loss_ratio` is null when there are no winning or no losing
realized-P&L fills.
```

- [ ] **Step 5: Update the ib-suite index**

In `skills/ib-suite/SKILL.md`:

1. Add an `ib-trade-history` row to the directory overview table, describing
   it as a read-only Flex Query execution-history skill and `/ib-trade-history`
   command.
2. Add the directory and a concise comment to the tree:

```text
  ib-trade-history/        # /ib-trade-history: Flex executions -> stdout JSON (no persistence)
```

3. Add the routing row:

```markdown
| List historical fills, commission, realized P&L and win/loss statistics | `ib-trade-history` → `/ib-trade-history` |
```

4. Add a direct invocation example in §4:

```bash
# historical Flex executions (default: latest 7 calendar days)
{baseDir}/.venv/bin/python {baseDir}/ib-trade-history/scripts/trade_history.py \
  --config .ib-suite/config.yaml
```

- [ ] **Step 6: Run focused skill tests**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_schema.py \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py \
  skills/ib-suite/ib-trade-history/tests -q
```

Expected: PASS. The test output must show all three groups passing with no live
IB Gateway or Flex request.

### Task 5: Run Full Regression and Static Contract Checks

**Files:**
- Verify only; no new source files.

**Interfaces:**
- Verifies the new functional skill is discoverable, uses portable paths, and
  does not violate the project read-only boundary.

- [ ] **Step 1: Verify frontmatter, paths, and forbidden order APIs**

Run:

```bash
rg -n '^name: ib-trade-history$|^description: Read-only|FLEX_TOKEN|FLEX_QUERY_ID|trade_history.py' \
  skills/ib-suite/ib-trade-history/SKILL.md
rg -n 'placeOrder|cancelOrder|reqGlobalCancel|bracketOrder' \
  skills/ib-suite/ib-trade-history skills/ib-suite/ib-gateway/scripts/flex_fetch.py
```

Expected: the first command prints the expected metadata and command references;
the second prints no matches.

- [ ] **Step 2: Run the complete suite**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills -q
```

Expected: PASS with the pre-existing suite plus the new schema, parser, and
trade-history tests.

- [ ] **Step 3: Inspect the final diff and generated files**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the planned skill, parser, schema, tests,
fixtures, and index documentation are modified. Do not commit unless the user
explicitly asks for a commit.
