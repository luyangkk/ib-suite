# IB Dividend Income Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flex-only `/ib-dividend-income` skill that separates paid and expected dividends, reconciles taxes and quantities, summarizes multi-currency income, estimates current annual income from trailing history, and guides first-run Flex configuration.

**Architecture:** Extract shared Flex window/config primitives into `ib_common`, extend the existing Flex parser with typed dividend-report sections, and keep reconciliation/aggregation in a pure `ib_common.dividend_income` module. A thin skill-local CLI selects one Flex report, emits structured stderr logs and one stdout JSON object, while `SKILL.md` and a standalone setup guide own conversational behavior.

**Tech Stack:** Python 3.11+, pydantic v2, `xml.etree.ElementTree`, `ruamel.yaml`, `requests`, pytest, OpenClaw `SKILL.md` metadata.

## Global Constraints

- Use only IBKR Flex Web Service data; do not connect to IB Gateway or request market data.
- Preserve the hard read-only boundary: no order imports or order methods.
- Do not add runtime dependencies; update neither `pyproject.toml` nor `requirements.txt`.
- Put every typed data structure in `ib_common.schema`; every module/public function gets an English docstring and type annotations.
- Print exactly one JSON object to stdout; emit logs only to stderr.
- Never log or echo Flex tokens, Query IDs, account IDs, reference codes, request URLs, or raw XML.
- Treat the requested start and end dates as inclusive.
- Use only Flex `fxRateToBase` values for base-currency conversion; missing values remain null and are disclosed.
- Keep realized and expected dividends separate; never fabricate unavailable values as zero.
- Preserve the user's unrelated `.gitignore` working-tree modification.

---

## File Map

- Create `skills/ib-suite/ib-common/ib_common/flex.py`: shared date, token, and window-selection primitives.
- Modify `skills/ib-suite/ib-trade-history/scripts/trade_history.py`: import shared primitives without changing behavior.
- Modify `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`: protect the refactor.
- Modify `skills/ib-suite/ib-trade-history/scripts/configure_flex.py`: add stdin-only token input.
- Modify `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`: verify stdin and mutual exclusion.
- Modify `skills/ib-suite/ib-common/ib_common/schema.py`: add raw Flex dividend-section and report models.
- Modify `skills/ib-suite/ib-gateway/scripts/flex_fetch.py`: parse and validate the six required Flex sections.
- Modify `skills/ib-suite/ib-gateway/tests/test_flex_fetch.py`: parser and secret-redaction tests.
- Create `skills/ib-suite/ib-common/ib_common/dividend_income.py`: pure reconciliation, aggregation, country mapping, and annual estimates.
- Create `skills/ib-suite/ib-common/tests/test_dividend_income.py`: calculation tests.
- Create `skills/ib-suite/ib-dividend-income/scripts/dividend_income.py`: CLI orchestration, setup states, and logs.
- Create `skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py`: orchestration/logging tests.
- Create `skills/ib-suite/ib-dividend-income/tests/fixtures/flex_dividend_income_sample.xml`: desensitized multi-section fixture.
- Create `skills/ib-suite/ib-dividend-income/SKILL.md`: trigger, command, presentation and setup behavior.
- Create `skills/ib-suite/ib-dividend-income/flex-query-setup.md`: standalone Client Portal guide.
- Modify `skills/ib-suite/SKILL.md`: route and document the new skill.
- Modify `CLAUDE.md`: keep the real repository inventory and validation commands accurate.

### Task 1: Share Flex Date, Token, and Window Selection

**Files:**
- Create: `skills/ib-suite/ib-common/ib_common/flex.py`
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`
- Modify: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`
- Test: `skills/ib-suite/ib-common/tests/test_flex.py`

**Interfaces:**
- Produces: `parse_iso_date(value: str) -> date`
- Produces: `resolve_date_range(start: str | None, end: str | None, today: date, default_days: int = 7) -> tuple[date, date]`
- Produces: `resolve_flex_token(cfg: Config) -> str`
- Produces: `select_numeric_window(query_ids: dict[str, str], required_start: date, today: date, *, allow_partial: bool) -> tuple[str, str, str | None]`
- Consumes: `ib_common.config.Config`

- [ ] **Step 1: Write failing shared-helper tests**

Create `test_flex.py` with focused tests:

```python
from datetime import date
import pytest
from ib_common.config import Config
from ib_common.flex import (
    parse_iso_date, resolve_date_range, resolve_flex_token,
    select_numeric_window,
)

def test_select_numeric_window_returns_smallest_covering_key():
    assert select_numeric_window(
        {"7": "q7", "30": "q30", "365": "q365"},
        date(2026, 7, 1), date(2026, 7, 19), allow_partial=False,
    ) == ("30", "q30", None)

def test_select_numeric_window_can_require_complete_coverage():
    with pytest.raises(ValueError, match="365 days"):
        select_numeric_window(
            {"30": "q30"}, date(2025, 7, 20), date(2026, 7, 19),
            allow_partial=False,
        )

def test_resolve_date_range_is_inclusive_and_ordered():
    assert resolve_date_range(
        "2026-07-01", "2026-07-19", date(2026, 7, 19)
    ) == (date(2026, 7, 1), date(2026, 7, 19))
    with pytest.raises(ValueError, match="on or before"):
        resolve_date_range("2026-07-20", "2026-07-19", date(2026, 7, 19))

def test_resolve_flex_token_never_includes_value_in_error():
    with pytest.raises(ValueError, match="not configured"):
        resolve_flex_token(Config())
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_flex.py -q
```

Expected: collection fails because `ib_common.flex` does not exist.

- [ ] **Step 3: Implement the shared helpers**

Create `ib_common/flex.py` with the exact public signatures above. Numeric window
selection computes `gap = (today - required_start).days + 1`, returns the
smallest key with `days >= gap`, and either raises an actionable coverage error
or returns the largest key plus the existing incomplete-coverage note according
to `allow_partial`.

- [ ] **Step 4: Migrate trade history without changing its public API**

Replace local `parse_iso_date`, `resolve_period`, `resolve_flex_token`, and the
numeric body of `select_flex_window` with imports/adapters from `ib_common.flex`.
Keep `trade_history.select_flex_window(...) -> tuple[int, str, str | None]` so
existing callers and tests remain compatible.

- [ ] **Step 5: Run shared and trade-history tests GREEN**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_flex.py \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q
```

Expected: all selected tests pass with no warnings.

- [ ] **Step 6: Commit the refactor**

```bash
git add skills/ib-suite/ib-common/ib_common/flex.py \
  skills/ib-suite/ib-common/tests/test_flex.py \
  skills/ib-suite/ib-trade-history/scripts/trade_history.py \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "refactor(ib-suite): share Flex window selection"
```

### Task 2: Accept Flex Tokens Safely from Standard Input

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/configure_flex.py`
- Modify: `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`

**Interfaces:**
- Produces CLI flag: `--token-stdin`
- Preserves: `configure_flex(config_path, token, windows, force) -> dict`
- Rule: `--token` and `--token-stdin` are mutually exclusive.

- [ ] **Step 1: Write failing CLI input tests**

Add subprocess tests that run the script with `input="secret-token\n"`, assert
return code zero, assert neither stdout nor stderr contains `secret-token`, and
reload the config to assert the token was stored. Add a second test invoking
both flags and assert exit code 2 with a mutual-exclusion message.

- [ ] **Step 2: Run the tests and verify RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py \
  -k 'stdin or mutually_exclusive' -q
```

Expected: FAIL because `--token-stdin` is unrecognized.

- [ ] **Step 3: Implement stdin token handling**

Use a mutually exclusive argparse group:

```python
token_group = parser.add_mutually_exclusive_group()
token_group.add_argument("--token", help="IBKR Flex token")
token_group.add_argument(
    "--token-stdin", action="store_true",
    help="read the IBKR Flex token from one stdin line",
)
token = sys.stdin.readline().rstrip("\r\n") if args.token_stdin else args.token
```

Import `sys`; pass `token` to the unchanged `configure_flex` function. Blank
stdin must produce the existing blank-token validation error.

- [ ] **Step 4: Run the full configuration tests GREEN**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q
```

Expected: all tests pass and captured output contains no token.

- [ ] **Step 5: Commit the secure input path**

```bash
git add skills/ib-suite/ib-trade-history/scripts/configure_flex.py \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py
git commit -m "feat(ib-suite): configure Flex token from stdin"
```

### Task 3: Parse the Six Flex Dividend Sections into Typed Records

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/schema.py`
- Modify: `skills/ib-suite/ib-gateway/scripts/flex_fetch.py`
- Modify: `skills/ib-suite/ib-gateway/tests/test_flex_fetch.py`
- Create: `skills/ib-suite/ib-dividend-income/tests/fixtures/flex_dividend_income_sample.xml`

**Interfaces:**
- Produces models: `FlexCashTransaction`, `FlexDividendAccrual`, `FlexOpenPosition`, `FlexInstrument`, `FlexDividendDataset`
- Produces: `parse_flex_dividend_dataset(xml_text: str) -> FlexDividendDataset`
- Produces: `FlexQuerySchemaError(ValueError)` with `missing_sections` and `missing_fields`.

- [ ] **Step 1: Add a desensitized, multi-section XML fixture**

The fixture contains account base USD, a paid USD AAPL dividend plus its tax
cash row and lifecycle accruals, an expected SGD dividend, long AAPL/SGD fund
positions, one short and one option position, and financial-instrument listing
exchanges. Use fake account `U0000000`, fake Query ID nowhere, and no token or
service URL.

- [ ] **Step 2: Write failing parser tests**

Add tests asserting:

```python
dataset = flex.parse_flex_dividend_dataset(xml_text)
assert dataset.base_currency == "USD"
assert len(dataset.cash_transactions) == 2
assert dataset.cash_transactions[0].symbol == "AAPL"
assert dataset.cash_transactions[0].fx_rate_to_base == 1.0
assert dataset.dividend_accruals[0].quantity == 100
assert dataset.open_dividend_accruals[0].pay_date.isoformat() == "2026-08-15"
assert dataset.open_positions[0].level_of_detail == "SUMMARY"
assert dataset.instruments[0].listing_exchange == "NASDAQ"
```

Add parameterized XML mutations that remove each required section and one
required attribute per section. Assert `FlexQuerySchemaError` reports only
section/field names and never includes XML content or account IDs.

- [ ] **Step 3: Run parser tests and verify RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py \
  -k 'dividend_dataset or required_dividend' -q
```

Expected: FAIL because the models/parser do not exist.

- [ ] **Step 4: Add pydantic raw-record models**

Each model includes only normalized fields required by the approved design.
Dates use `date`, cash timestamps use `datetime`, monetary/quantity fields use
`float | None` where Flex may omit a fact, codes are uppercase strings, and
`fx_rate_to_base` is `float | None`. `FlexDividendDataset` contains the five
record lists plus `base_currency`.

- [ ] **Step 5: Implement strict section parsing**

In `flex_fetch.py`, use `_required(element, field)`-style helpers that name the
Flex section in errors. Accept IB's known XML element names for each section,
normalize blank optional values to `None`, normalize sign conventions only in
the calculation layer, and parse both `YYYYMMDD` and `YYYY-MM-DD` dates with the
existing `_parse_date` helper.

- [ ] **Step 6: Run parser and gateway regression tests GREEN**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py -q
```

Expected: all gateway tests pass.

- [ ] **Step 7: Commit the typed parser**

```bash
git add skills/ib-suite/ib-common/ib_common/schema.py \
  skills/ib-suite/ib-gateway/scripts/flex_fetch.py \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py \
  skills/ib-suite/ib-dividend-income/tests/fixtures/flex_dividend_income_sample.xml
git commit -m "feat(ib-suite): parse Flex dividend sections"
```

### Task 4: Reconcile, Aggregate, and Estimate Dividend Income

**Files:**
- Create: `skills/ib-suite/ib-common/ib_common/dividend_income.py`
- Modify: `skills/ib-suite/ib-common/ib_common/schema.py`
- Create: `skills/ib-suite/ib-common/tests/test_dividend_income.py`

**Interfaces:**
- Produces models: `DividendIncomeLine`, `DividendTotals`, `AnnualDividendHolding`, `AnnualDividendEstimate`, `DividendIncomeReport`
- Produces: `build_dividend_income_report(dataset: FlexDividendDataset, start_date: date, end_date: date, coverage_note: str | None = None) -> DividendIncomeReport`
- Produces: `listing_country(exchange: str, isin: str) -> str`

- [ ] **Step 1: Write failing realized/expected reconciliation tests**

Construct typed datasets directly and assert:

```python
report = build_dividend_income_report(
    dataset, date(2026, 7, 1), date(2026, 8, 31)
)
assert [row.status for row in report.realized_dividends] == ["REALIZED"]
assert report.realized_dividends[0].gross == 25.0
assert report.realized_dividends[0].withholding_tax == 3.75
assert report.realized_dividends[0].net == 21.25
assert report.realized_dividends[0].quantity == 100
assert [row.status for row in report.expected_dividends] == ["EXPECTED"]
```

Add cases for exact conid match, symbol fallback, ambiguous fallback, a paid row
also present in open accruals, and inclusive boundary dates.

- [ ] **Step 2: Run the reconciliation tests and verify RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_dividend_income.py \
  -k 'reconcile or expected or inclusive' -q
```

Expected: collection fails because `ib_common.dividend_income` does not exist.

- [ ] **Step 3: Implement deterministic lifecycle and association helpers**

Use `(account_id, conid, currency, ex_date, pay_date)` as the preferred economic
event key. Fall back to normalized symbol only when conid is absent. Reduce `Po`
postings, corrections/cancellations, and `Re` reversals before matching. Match
cash by account/conid/currency/pay date first, then unique symbol fallback within
the documented deterministic date tolerance. Return no match when more than one
candidate remains.

- [ ] **Step 4: Write failing aggregation and FX tests**

Assert separate realized/expected totals; native currency buckets; base country
buckets; contribution ranking by realized `base_net`; positive tax/fee deduction
signs; missing FX preserving native values while base values stay null; NASDAQ
mapping to US, SGX to SG, ISIN fallback, and `UNKNOWN`.

- [ ] **Step 5: Implement line conversion and summaries**

`DividendIncomeLine` exposes `base_gross`, `base_withholding_tax`, `base_fee`, and
`base_net` as nullable values set at build time. The summary stores realized and
expected `DividendTotals` separately, `by_currency`, `by_country`, and
`top_contributors`. Never sum a null base value as zero; track excluded rows in
`data_limitations`.

- [ ] **Step 6: Write failing annual-estimate tests**

Cover current long STK/FUND positions, non-paying long holdings in the yield
denominator, exclusion of OPT and shorts, trailing per-share rate × current
quantity, symbol-level effective tax rate, unavailable net estimate, complete
365-day history, and a 120-day lower bound marked incomplete.

- [ ] **Step 7: Implement annual estimates**

Use unique, positive trailing accrual events with ex dates in
`[end_date - 364 days, end_date]`. Compute gross estimates per holding and base
currency; compute net only with reliable realized tax history. Set
`portfolio_estimated_gross_yield` only from gross base estimates divided by all
eligible long STK/FUND base market value. Include `history_days_covered` and
`complete_history`.

- [ ] **Step 8: Run calculation tests GREEN**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_dividend_income.py -q
```

Expected: all calculation tests pass.

- [ ] **Step 9: Commit the calculation engine**

```bash
git add skills/ib-suite/ib-common/ib_common/schema.py \
  skills/ib-suite/ib-common/ib_common/dividend_income.py \
  skills/ib-suite/ib-common/tests/test_dividend_income.py
git commit -m "feat(ib-suite): calculate dividend income report"
```

### Task 5: Add the Dividend CLI, Structured Setup States, and Safe Logs

**Files:**
- Create: `skills/ib-suite/ib-dividend-income/scripts/dividend_income.py`
- Create: `skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py`

**Interfaces:**
- Produces: `dividend_income(config_path: str, start: str, end: str, fetcher: Callable[[str, str], str] = fetch_flex_report, today: date | None = None, run_id: str | None = None) -> dict`
- Produces CLI flags: `--config`, `--start-date`, `--end-date`, `--log-level`
- Produces setup statuses: `setup_required`, `coverage_required`, `query_update_required`

- [ ] **Step 1: Write failing orchestration tests**

Use an injected fetcher to assert one call, the smallest query covering both the
requested range and 365-day estimate history, JSON-safe output, and no Gateway
client import. Add missing-token, empty-query-map, insufficient-window, and
missing-section tests that assert the exact structured status and guide path.

- [ ] **Step 2: Run orchestration tests and verify RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py \
  -k 'orchestration or setup or coverage or query_update' -q
```

Expected: collection fails because the CLI module does not exist.

- [ ] **Step 3: Implement orchestration**

Load config, parse the explicit inclusive dates, compute
`required_start = min(start_date, end_date - timedelta(days=364))`, select a
strictly covering numeric window relative to `today`, fetch once, parse once,
and call `build_dividend_income_report`. Convert known configuration/schema
failures into a JSON-safe error payload containing status, missing names,
`guide: "{baseDir}/../flex-query-setup.md"` at skill-instruction level, and no
secret values.

- [ ] **Step 4: Write failing stdout/stderr and redaction tests**

Run the CLI as a subprocess against a temporary config and fixture. Assert
stdout parses as exactly one JSON object; stderr contains `run_id`, selected
window key, section counts and elapsed time; neither stream contains token,
Query ID, account ID, raw XML, reference code, or URL query parameters. Repeat
with `--log-level DEBUG` and a synthetic `FlexServiceError`.

- [ ] **Step 5: Implement structured logging and sanitization**

Configure a stderr `logging.StreamHandler`; log event names with stable
`key=value` fields. Generate `run_id = uuid.uuid4().hex`. Reuse the Flex client's
credential-safe exception text and add a final sanitizer for account-like IDs,
URLs, and `t=`/`q=` parameters before logging. Never attach XML or row objects.

- [ ] **Step 6: Run CLI tests GREEN**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py -q
```

Expected: all CLI tests pass with no secret matches.

- [ ] **Step 7: Commit the CLI**

```bash
git add skills/ib-suite/ib-dividend-income/scripts/dividend_income.py \
  skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py
git commit -m "feat(ib-suite): add dividend income CLI"
```

### Task 6: Add OpenClaw Skill Instructions and Flex Query Setup Guide

**Files:**
- Create: `skills/ib-suite/ib-dividend-income/SKILL.md`
- Create: `skills/ib-suite/ib-dividend-income/flex-query-setup.md`
- Modify: `skills/ib-suite/SKILL.md`
- Modify: `CLAUDE.md`
- Create: `skills/ib-suite/ib-dividend-income/tests/test_skill_contract.py`

**Interfaces:**
- Produces OpenClaw skill name: `ib-dividend-income`
- Produces slash command: `/ib-dividend-income`
- Produces standalone guide link: `{baseDir}/flex-query-setup.md`

- [ ] **Step 1: Write failing skill-contract tests**

Parse frontmatter with `ruamel.yaml` and assert `name == directory`, description
starts with `Read-only`, `metadata.openclaw.requires.bins == ["python3"]`, config
gate is `["config.yaml"]`, and OS list is `darwin/linux`. Assert the command uses
`{baseDir}/../.venv/bin/python`, both date flags, and no absolute path. Assert the
index names and routes the skill. Assert both docs state no Gateway/market-data/
order use and the setup guide lists all six Flex sections.

- [ ] **Step 2: Run contract tests and verify RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-dividend-income/tests/test_skill_contract.py -q
```

Expected: FAIL because `SKILL.md` and the guide do not exist.

- [ ] **Step 3: Write concise `SKILL.md`**

Use valid OpenClaw frontmatter and imperative instructions. Define date
resolution, command execution, realized-before-expected tables, required column
order, separate summaries, null/limitation behavior, setup-state handling, and
one-question-at-a-time conversational configuration using `--token-stdin`.
Require confirmation before `--force`. Keep deterministic financial logic out of
the skill body.

- [ ] **Step 4: Write `flex-query-setup.md`**

Document Client Portal navigation, Activity Flex Query creation, XML output,
every required section/field from the design, date/window profiles, Query ID and
Flex Web Service token retrieval, conversational registration commands, local
validation, token rotation, overwrite confirmation, and troubleshooting. State
that saving local credentials does not prove the remote query is correct.

- [ ] **Step 5: Update the ib-suite index and repository map**

Add the skill to the index table, tree, routing matrix, invocation examples,
scope wording, and shared Flex configuration notes. Update `CLAUDE.md` inventory,
structure, typical outputs, and single-skill test command without changing the
read-only boundary.

- [ ] **Step 6: Run contract tests GREEN**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-dividend-income/tests/test_skill_contract.py -q
```

Expected: all contract tests pass.

- [ ] **Step 7: Commit the skill and guide**

```bash
git add skills/ib-suite/ib-dividend-income/SKILL.md \
  skills/ib-suite/ib-dividend-income/flex-query-setup.md \
  skills/ib-suite/ib-dividend-income/tests/test_skill_contract.py \
  skills/ib-suite/SKILL.md CLAUDE.md
git commit -m "docs(ib-suite): add dividend income skill"
```

### Task 7: End-to-End and Full-Suite Verification

**Files:**
- Modify only files implicated by failures in Tasks 1–6.

**Interfaces:**
- Verifies all earlier public interfaces and safety constraints.

- [ ] **Step 1: Run the new skill end to end with the fixture**

Use a temporary config and injected-fixture test; do not call the real Flex Web
Service. Assert realized and expected sections, totals, contribution ranking,
country/currency attribution, annual estimate, run ID, and limitations.

- [ ] **Step 2: Run focused tests**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_flex.py \
  skills/ib-suite/ib-common/tests/test_dividend_income.py \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py \
  skills/ib-suite/ib-dividend-income -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run static safety searches**

```bash
rg -n "placeOrder|cancelOrder|reqMktData|reqMarketDataType|IB\(" \
  skills/ib-suite/ib-dividend-income \
  skills/ib-suite/ib-common/ib_common/dividend_income.py
rg -n "token|query.?id|account.?id|raw.?xml" \
  skills/ib-suite/ib-dividend-income/scripts/dividend_income.py
```

Expected: the first search has no matches; every second-search match is a
sanitization, input, or non-logging reference reviewed manually.

- [ ] **Step 4: Run the full suite**

```bash
skills/ib-suite/.venv/bin/python -m pytest skills -q
```

Expected: all tests pass with no errors or warnings.

- [ ] **Step 5: Verify the diff and working-tree isolation**

```bash
git diff --check
git status --short
git diff -- .gitignore
```

Expected: no whitespace errors; only intended feature files plus the user's
pre-existing `.gitignore` modification appear; `.gitignore` content is unchanged
from its pre-implementation state.

- [ ] **Step 6: Resolve any verification failure through its owning task**

If verification exposes a defect, return to the task that owns that interface,
add a focused failing regression test, make the minimal fix, rerun that task's
test command and the full suite, then commit the exact files named by that task.

- [ ] **Step 7: Final evidence report**

Report what changed, focused/full test commands and counts, what was not verified
against a live IBKR account, and residual risks: broker XML variations, exchange
country-map coverage, ambiguous legacy cash/accrual associations, and incomplete
Flex history.
