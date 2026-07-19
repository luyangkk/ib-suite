# IB Options Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `/ib-options-overview` skill that lists all live IBKR
option positions and returns their valuation, IV, Greeks, moneyness, expiry
distribution, and absolute-value underlying concentration.

**Architecture:** `ib_common.schema` owns typed response models. The new
`options_overview.py` keeps report construction and aggregation pure while an
injectable client owns the read-only Gateway connection, portfolio lookup,
market-data subscriptions, and cleanup. `SKILL.md` exposes a single command;
the index skill routes option-risk requests to it.

**Tech Stack:** Python 3.11+, Pydantic v2, ib_async, ruamel.yaml, pytest.

## Global Constraints

- Use Python >= 3.11 and begin every Python module with `from __future__ import annotations`.
- Use Pydantic v2 `BaseModel` for response data; no additional dependency is allowed.
- All IB connections must pass `readonly=True`; do not import or reference order APIs.
- Use IB-provided `portfolio()` valuation and unrealized P&L without recomputing them.
- Honor `connection.market_data_type`; delayed market data is accepted.
- Print exactly one parseable JSON object and persist no data.
- Greeks and underlying price unavailable from IB remain `null`, never zero.
- DTE is inclusive calendar days: `expiry_date - report_date + 1`.
- Underlying concentration uses absolute base-currency option market value and does not net long and short legs.
- Keep secrets out of source and stdout; no token, cookie, or account identifier fixture may be real.
- Run all commands through `skills/ib-suite/.venv/bin/python`; do not alter existing unrelated worktree changes.

---

### Task 1: Define Typed Option-Risk Responses

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/schema.py`
- Modify: `skills/ib-suite/ib-common/tests/test_schema.py`

**Interfaces:**
- Produces: `OptionPositionView`, `OptionGreekCoverage`, `OptionExpirationBucket`,
  `OptionUnderlyingConcentration`, `OptionsOverviewSummary`, and
  `OptionsOverview`.
- Consumes: `datetime.date`, `datetime.datetime`, Pydantic `BaseModel`, and
  existing `computed_field` conventions in `schema.py`.
- Used by: `options_overview.build_options_overview()` in Task 2.

- [ ] **Step 1: Write failing schema tests**

Add tests that instantiate a long Call and confirm serialized fields retain
nullable Greeks and that a response model preserves `null` aggregate fields:

```python
from datetime import date, datetime, timezone

from ib_common.schema import OptionPositionView, OptionsOverview, OptionsOverviewSummary


def test_option_position_view_serializes_nullable_market_data():
    position = OptionPositionView(
        account_id="U0000000",
        underlying_symbol="AAPL",
        right="CALL",
        quantity=2,
        strike=200.0,
        expiry_date=date(2026, 8, 21),
        days_to_expiry=35,
        avg_cost=1234.0,
        market_price=12.5,
        market_value=2500.0,
        unrealized_pnl=32.0,
        currency="USD",
        multiplier=100,
        implied_volatility=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        underlying_price=None,
        moneyness=None,
        greeks_status="unavailable: no option market data",
    )

    assert position.position_side == "LONG"
    assert position.model_dump(mode="json")["theta"] is None


def test_options_overview_preserves_null_aggregate_when_uncovered():
    response = OptionsOverview(
        account_id="U0000000",
        base_currency="USD",
        options=[],
        summary=OptionsOverviewSummary(
            total_delta=None,
            total_gamma=None,
            total_theta=None,
            total_vega=None,
            daily_time_value_decay=None,
            greek_coverage={},
            expiration_distribution=[],
            underlying_concentration=[],
        ),
        data_limitations=["No open option positions."],
        ts=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )

    assert response.model_dump(mode="json")["summary"]["total_delta"] is None
```

- [ ] **Step 2: Run the schema tests and verify they fail**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_schema.py -q
```

Expected: FAIL during import because `OptionPositionView`,
`OptionsOverviewSummary`, and `OptionsOverview` do not yet exist.

- [ ] **Step 3: Add the minimal Pydantic models**

Append the following model family after the existing overview models in
`skills/ib-suite/ib-common/ib_common/schema.py`:

```python
class OptionPositionView(BaseModel):
    """One live option holding with IB valuation and model-Greeks fields."""

    account_id: str
    underlying_symbol: str
    right: str
    quantity: float
    strike: float
    expiry_date: date
    days_to_expiry: int
    avg_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    currency: str
    multiplier: int
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    underlying_price: float | None = None
    moneyness: str | None = None
    greeks_status: str
    fx_rate: float | None = None
    base_market_value: float | None = None
    base_unrealized_pnl: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def position_side(self) -> str:
        """Return the direction represented by the signed holding quantity."""
        return "LONG" if self.quantity > 0 else "SHORT" if self.quantity < 0 else "FLAT"


class OptionGreekCoverage(BaseModel):
    """Coverage metadata for one account-level Greek."""

    contributing_contracts: int
    excluded_contracts: list[str] = Field(default_factory=list)


class OptionExpirationBucket(BaseModel):
    """Absolute option exposure and signed quantity for one expiry."""

    expiry_date: date
    contract_count: int
    quantity: float
    absolute_base_market_value: float | None = None


class OptionUnderlyingConcentration(BaseModel):
    """Absolute option-market-value concentration for one underlying."""

    underlying_symbol: str
    absolute_base_market_value: float | None = None
    weight: float | None = None


class OptionsOverviewSummary(BaseModel):
    """Aggregate option Greeks and deterministic risk distributions."""

    total_delta: float | None = None
    total_gamma: float | None = None
    total_theta: float | None = None
    total_vega: float | None = None
    daily_time_value_decay: float | None = None
    greek_coverage: dict[str, OptionGreekCoverage] = Field(default_factory=dict)
    expiration_distribution: list[OptionExpirationBucket] = Field(default_factory=list)
    underlying_concentration: list[OptionUnderlyingConcentration] = Field(default_factory=list)


class OptionsOverview(BaseModel):
    """Read-only option holdings and aggregate risk overview."""

    account_id: str
    base_currency: str
    options: list[OptionPositionView]
    summary: OptionsOverviewSummary
    data_limitations: list[str]
    ts: datetime
```

Import `date` alongside the module's existing `datetime` import.

- [ ] **Step 4: Run the schema tests and verify they pass**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_schema.py -q
```

Expected: PASS, including both new option-response tests.

- [ ] **Step 5: Commit the response contract**

```bash
git add skills/ib-suite/ib-common/ib_common/schema.py skills/ib-suite/ib-common/tests/test_schema.py
git commit -m "feat(ib-suite): add option overview schema"
```

### Task 2: Build Pure Option Mapping and Risk Aggregation

**Files:**
- Create: `skills/ib-suite/ib-options-overview/scripts/options_overview.py`
- Create: `skills/ib-suite/ib-options-overview/tests/fixtures/ib_raw_options_sample.json`
- Create: `skills/ib-suite/ib-options-overview/tests/test_options_overview.py`

**Interfaces:**
- Consumes: raw dictionary:
  `{"account": {"account_id": str, "base_currency": str}, "options": list[dict]}`.
- Produces: `build_options_overview(raw: dict, report_date: date, ts: datetime) -> OptionsOverview`,
  `classify_moneyness(right: str, strike: float, underlying_price: float | None) -> str | None`,
  and `build_summary(options: list[OptionPositionView]) -> tuple[OptionsOverviewSummary, list[str]]`.
- Used by: `options_overview.options_overview()` in Task 3.

- [ ] **Step 1: Write failing pure-function tests and fixture**

Create a fixture with three USD contracts: long AAPL Call (strike 200,
underlying 210, complete Greeks), short AAPL Put (strike 190, underlying 185,
complete Greeks), and long MSFT Call (missing Greeks and underlying price).
Use multiplier 100 and a report date of `2026-07-18`.

Use this exact fixture content:

```json
{
  "account": {
    "account_id": "U0000000",
    "base_currency": "USD"
  },
  "options": [
    {
      "contract_id": "AAPL-20260821-C-200",
      "underlying_symbol": "AAPL",
      "right": "CALL",
      "strike": 200.0,
      "expiry_date": "2026-08-21",
      "multiplier": "100",
      "quantity": 2,
      "avg_cost": 1000.0,
      "market_price": 12.5,
      "market_value": 2500.0,
      "unrealized_pnl": 500.0,
      "currency": "USD",
      "fx_rate": 1.0,
      "implied_volatility": 0.25,
      "delta": 0.5,
      "gamma": 0.03,
      "theta": -0.14,
      "vega": 0.4,
      "underlying_price": 210.0
    },
    {
      "contract_id": "AAPL-20260821-P-190",
      "underlying_symbol": "AAPL",
      "right": "PUT",
      "strike": 190.0,
      "expiry_date": "2026-08-21",
      "multiplier": "100",
      "quantity": -1,
      "avg_cost": 900.0,
      "market_price": 10.0,
      "market_value": -1000.0,
      "unrealized_pnl": -100.0,
      "currency": "USD",
      "fx_rate": 1.0,
      "implied_volatility": 0.30,
      "delta": -0.4,
      "gamma": 0.02,
      "theta": -0.04,
      "vega": 0.2,
      "underlying_price": 185.0
    },
    {
      "contract_id": "MSFT-20260918-C-500",
      "underlying_symbol": "MSFT",
      "right": "CALL",
      "strike": 500.0,
      "expiry_date": "2026-09-18",
      "multiplier": "100",
      "quantity": 1,
      "avg_cost": 600.0,
      "market_price": 5.0,
      "market_value": 500.0,
      "unrealized_pnl": -100.0,
      "currency": "USD",
      "fx_rate": 1.0,
      "implied_volatility": null,
      "delta": null,
      "gamma": null,
      "theta": null,
      "vega": null,
      "underlying_price": null
    }
  ]
}
```

Add these tests:

```python
def test_build_options_maps_contract_fields_and_inclusive_dte():
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    call = overview.options[0]
    assert call.underlying_symbol == "AAPL"
    assert call.right == "CALL"
    assert call.position_side == "LONG"
    assert call.days_to_expiry == 35
    assert call.moneyness == "ITM"


def test_build_options_scales_signed_greeks_and_daily_theta():
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    assert overview.summary.total_delta == 140.0
    assert overview.summary.total_gamma == 4.0
    assert overview.summary.total_theta == -24.0
    assert overview.summary.total_vega == 60.0
    assert overview.summary.daily_time_value_decay == 24.0
    assert overview.summary.greek_coverage["delta"].contributing_contracts == 2


def test_missing_greeks_are_null_and_excluded_with_limitations():
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    msft = next(row for row in overview.options if row.underlying_symbol == "MSFT")
    assert msft.delta is None
    assert msft.moneyness is None
    assert any("MSFT" in item for item in overview.data_limitations)


def test_absolute_value_concentration_does_not_net_long_short_legs():
    overview = options_overview.build_options_overview(_raw(), REPORT_DATE, TS)
    aapl = overview.summary.underlying_concentration[0]
    assert aapl.underlying_symbol == "AAPL"
    assert aapl.absolute_base_market_value == 3500.0
    assert aapl.weight == 3500.0 / 4000.0
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-options-overview/tests/test_options_overview.py -q
```

Expected: FAIL because `options_overview.py` does not exist.

- [ ] **Step 3: Implement deterministic mapping and aggregation**

Create `options_overview.py` with:

```python
def classify_moneyness(right: str, strike: float, underlying_price: float | None) -> str | None:
    """Classify an option using the observed underlying price."""
    if underlying_price is None:
        return None
    if underlying_price == strike:
        return "ATM"
    if right == "CALL":
        return "ITM" if underlying_price > strike else "OTM"
    if right == "PUT":
        return "ITM" if underlying_price < strike else "OTM"
    raise ValueError(f"unsupported option right: {right!r}")


def _scaled_greek(position: OptionPositionView, name: str) -> float | None:
    """Return the signed, contract-multiplier-adjusted Greek when available."""
    value = getattr(position, name)
    if value is None or position.fx_rate is None:
        return None
    return value * position.quantity * position.multiplier * position.fx_rate
```

`build_options_overview()` must parse `expiry_date` with
`date.fromisoformat`, reject an invalid or zero/non-integer multiplier, retain
IB monetary fields as provided, derive base monetary fields only when
`fx_rate` exists, and populate explicit limitations for absent Greeks, price,
or FX.

`build_summary()` must calculate each Greek separately, record excluded
underlying/expiry/strike identifiers in `OptionGreekCoverage`, leave an
aggregate `None` only when its contributor count is zero, set daily decay to
the negated total theta, group expiry buckets in chronological order, and sort
concentration descending by absolute base market value then symbol.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-options-overview/tests/test_options_overview.py -q
```

Expected: PASS for moneyness, DTE, Greek scaling, coverage, limitations,
expiry grouping, and absolute-value concentration.

- [ ] **Step 5: Add error and empty-book tests, then run them**

Add tests for an empty `options` list, an invalid expiry string, an invalid
multiplier, a missing FX rate for a non-base currency, and a non-`CALL`/`PUT`
right. Execute:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-options-overview/tests/test_options_overview.py -q
```

Expected: PASS; malformed contract data raises `ValueError` with the contract
identifier and field name, and the empty book returns `[]` plus null Greek
totals.

- [ ] **Step 6: Commit pure report construction**

```bash
git add skills/ib-suite/ib-options-overview/scripts/options_overview.py \
  skills/ib-suite/ib-options-overview/tests/fixtures/ib_raw_options_sample.json \
  skills/ib-suite/ib-options-overview/tests/test_options_overview.py
git commit -m "feat(ib-suite): build option risk aggregates"
```

### Task 3: Add Read-Only IB Gateway Data Acquisition

**Files:**
- Modify: `skills/ib-suite/ib-options-overview/scripts/options_overview.py`
- Modify: `skills/ib-suite/ib-options-overview/tests/test_options_overview.py`

**Interfaces:**
- Consumes: `load_config(cfg_path)`, `resolve_base_currency(cfg, account_base)`,
  injected `client_factory(cfg)`, and `datetime` clock.
- Produces: `options_overview(cfg_path: str, client_factory=None, now=None) -> dict`.
- Client interface: `fetch_raw() -> dict`, `disconnect() -> None`.
- Used by: the module CLI and the command in Task 4.

- [ ] **Step 1: Write failing orchestration tests**

Add a fake client that records `disconnect()` and returns the Task 2 fixture.
Add a test that creates a temporary config and calls:

```python
out = options_overview.options_overview(
    cfg_path,
    client_factory=lambda cfg: FakeClient(),
    now=lambda: TS,
)

assert FakeClient.disconnected is True
assert out["account_id"] == "U0000000"
assert out["summary"]["daily_time_value_decay"] == 24.0
```

Also add a source-level test:

```python
for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
    assert forbidden not in SPEC.read_text()
```

- [ ] **Step 2: Run the orchestration tests and verify they fail**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-options-overview/tests/test_options_overview.py -q
```

Expected: FAIL because `options_overview()` and the client factory do not yet
exist.

- [ ] **Step 3: Implement live client and orchestration**

Add `_default_client_factory(cfg)` following
`ib-positions-overview/scripts/positions_overview.py`:

```python
from ib_async import IB

self.ib = IB()
self.ib.connect(
    cfg.connection.host,
    cfg.connection.port,
    clientId=cfg.connection.client_id,
    readonly=True,
)
self.ib.reqMarketDataType(
    {"realtime": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4}[cfg.connection.market_data_type]
)
```

In `fetch_raw()`, collect `$LEDGER-ExchangeRate` values; use `portfolio()` to
select only `contract.secType == "OPT"`; issue one `reqMktData(contract, "",
False, False)` per option; sleep for a bounded 4-second collection window; map
`ticker.modelGreeks` and `ticker.modelGreeks.undPrice`; and in a `finally`
block call `cancelMktData(contract)` for each opened option ticker. Return the
raw contracts, IB valuation, strings for `lastTradeDateOrContractMonth`,
`right`, and `multiplier`, market-data values, and local-to-base FX.

Implement:

```python
def options_overview(cfg_path: str, client_factory=None, now=None) -> dict:
    """Load config, pull a read-only option book, and return JSON-safe data."""
    cfg = load_config(cfg_path)
    client = (client_factory or _default_client_factory)(cfg)
    try:
        raw = client.fetch_raw()
    finally:
        client.disconnect()
    raw["account"]["base_currency"] = resolve_base_currency(
        cfg, raw["account"].get("base_currency")
    )
    stamp = (now or (lambda: datetime.now(timezone.utc)))()
    return build_options_overview(raw, stamp.date(), stamp).model_dump(mode="json")
```

The CLI must require `--config`, call this function, print a single
`json.dumps()` response, and route `FileNotFoundError` and `ValueError`
through `parser.error()` for a non-zero actionable exit.

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-options-overview/tests/test_options_overview.py -q
```

Expected: PASS, including injected-client orchestration, guaranteed disconnect,
and read-only static guard.

- [ ] **Step 5: Commit Gateway acquisition**

```bash
git add skills/ib-suite/ib-options-overview/scripts/options_overview.py \
  skills/ib-suite/ib-options-overview/tests/test_options_overview.py
git commit -m "feat(ib-suite): read option Greeks from gateway"
```

### Task 4: Register and Validate the Option Overview Skill

**Files:**
- Create: `skills/ib-suite/ib-options-overview/SKILL.md`
- Modify: `skills/ib-suite/SKILL.md`
- Modify: `skills/ib-suite/ib-options-overview/tests/test_options_overview.py`

**Interfaces:**
- Consumes: `{baseDir}/../.venv/bin/python {baseDir}/scripts/options_overview.py`
  and `.ib-suite/config.yaml`.
- Produces: discoverable `/ib-options-overview` skill with valid OpenClaw
  metadata and a single JSON stdout contract.

- [ ] **Step 1: Write failing skill-documentation assertions**

Add tests that read both Markdown files and assert:

```python
assert "name: ib-options-overview" in skill
assert "Read-only" in skill
assert "config: [config.yaml]" in skill
assert "{baseDir}/../.venv/bin/python {baseDir}/scripts/options_overview.py" in skill
assert "never places, modifies, or cancels an order" in skill
assert "ib-options-overview" in index_skill
```

- [ ] **Step 2: Run the assertions and verify they fail**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-options-overview/tests/test_options_overview.py -q
```

Expected: FAIL because the new `SKILL.md` does not exist and the index has no
route for it.

- [ ] **Step 3: Add the Skill contract and index route**

Create `skills/ib-suite/ib-options-overview/SKILL.md` frontmatter:

```yaml
---
name: ib-options-overview
description: Read-only Interactive Brokers option positions and Greeks overview. Use when the user asks to list every open option contract, its Call/Put direction, long/short position, strike, expiry, DTE, cost, market value, unrealized P&L, implied volatility, Greeks, moneyness, or aggregate option risk. Reads live positions and market data only - never places, modifies, or cancels an order.
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [config.yaml]
    os: [darwin, linux]
---
```

Document the exact command:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/options_overview.py --config .ib-suite/config.yaml
```

Document all 17 fields, model-Greeks subscription cleanup, inclusive DTE,
partial Greek coverage, delayed-data behavior, missing-data `null` handling,
absolute-value concentration, and the read-only limit. Update the index's
skills table, directory tree, routing table, and onboarding flow only at the
relevant entries.

- [ ] **Step 4: Run targeted skill tests and verify they pass**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-options-overview/tests/test_options_overview.py -q
```

Expected: PASS for metadata, command paths, index route, and read-only wording.

- [ ] **Step 5: Run the complete repository suite**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills -q
```

Expected: PASS with no regression in existing overview, gateway, common, or
analyst tests.

- [ ] **Step 6: Inspect changed files and commit**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only Task 4 files are unstaged or staged.

Then commit:

```bash
git add skills/ib-suite/ib-options-overview/SKILL.md \
  skills/ib-suite/SKILL.md \
  skills/ib-suite/ib-options-overview/tests/test_options_overview.py
git commit -m "feat(ib-suite): register option overview skill"
```
