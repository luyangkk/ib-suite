# IB Dividend Income Skill Design

**Date:** 2026-07-19  
**Status:** Approved  
**Scope:** Add one read-only, Flex-only dividend income skill under `skills/ib-suite/`.

## Goal

Add `ib-dividend-income`, invoked as `/ib-dividend-income`, to analyze an
Interactive Brokers account's dividend income for an inclusive start/end date
range. The result must separate paid dividends from expected dividends and show
line-item details, base-currency totals, currency and country attribution,
highest-contributing holdings, and a history-based estimate of current annual
dividend income and portfolio dividend yield.

The skill must not connect to IB Gateway, request market data, place orders, or
persist account data. Historical and current facts come exclusively from the
IBKR Flex Web Service.

## Chosen Approach

Reuse the existing `flex.token` and `flex.query_ids` configuration. Each saved
Activity Flex Query used by this skill includes the sections required for trade
history and dividend analysis. This avoids a second credential and window map,
and lets the existing smallest-covering-window selection and safe configuration
workflow remain the single source of truth.

Alternatives rejected:

- A separate `dividend_query_ids` map would isolate concerns but duplicate
  credentials, window selection, onboarding, and maintenance.
- Manual XML import would be fully offline but would not provide automatic
  retrieval or conversational first-run setup.

An existing query that lacks dividend sections remains valid for trade history,
but this skill reports the precise missing sections or fields and directs the
user to update it.

## Files and Responsibilities

```text
skills/ib-suite/
  SKILL.md                                  index/router update
  ib-common/ib_common/
    config.py                               shared Flex config, if needed
    schema.py                               typed dividend report models
  ib-gateway/scripts/
    flex_fetch.py                           reusable Flex XML section parsers
  ib-trade-history/scripts/
    configure_flex.py                       safe stdin credential input
  ib-dividend-income/
    SKILL.md                                trigger, command, presentation contract
    flex-query-setup.md                     standalone IBKR setup guide
    scripts/dividend_income.py              CLI, fetch, validation, computation
    tests/                                  unit and end-to-end tests + fixtures
```

Deterministic parsing and calculations live in Python. `SKILL.md` stays a
concise control plane with the command, safety boundary, configuration behavior,
and output presentation contract. No `agents/`, `references/`, or `assets/`
directories are added because this repository's OpenClaw unit does not use the
generic Codex skill scaffold.

## Command and Data Flow

The user supplies an inclusive date range:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/dividend_income.py \
  --config .ib-suite/config.yaml \
  --start-date 2026-01-01 \
  --end-date 2026-07-19
```

The runtime:

1. Validates the two ISO dates and `start_date <= end_date`.
2. Loads `.ib-suite/config.yaml` without displaying credentials.
3. Requires `flex.token` and a non-empty `flex.query_ids` map.
4. Computes the required coverage from the earlier of the requested start date
   and `end_date - 364 days` through the requested end date. This ensures the
   annual estimate has up to 365 days of history without a second Flex request.
5. Selects the smallest configured numeric, `mtd`, or `ytd` query that covers
   the required range, using the existing trade-history semantics.
6. Fetches one Flex XML document through the existing Version 3 client.
7. Validates the presence and required attributes of every necessary section.
8. Parses paid cash transactions, dividend accruals, open accruals, current open
   positions, financial-instrument metadata, and account base currency.
9. Associates related records, filters the inclusive requested date range, and
   computes line items, summaries, and annual estimates.
10. Prints exactly one JSON object to stdout. Logs go only to stderr.

The script never writes the XML or normalized financial rows to disk.

## Required Flex Query Content

The standalone setup guide gives IBKR Client Portal instructions for creating
an Activity Flex Query with XML output and these sections:

### Account Information

Required to identify the account base currency without Gateway access. Include
the base-currency and account identifier fields exposed by the Flex editor.

### Cash Transactions

Required fields: account ID, currency, asset class, FX rate to base, symbol,
description, conid, underlying conid/symbol, date/time, amount, type, trade ID,
871(m) withholding, and code. These records prove that a dividend or withholding
cash movement was posted.

### Change in Dividend Accruals

Required fields: account ID, currency, asset class, FX rate to base, symbol,
description, conid, date, ex date, pay date, quantity, tax, fee, gross rate,
gross amount, net amount, code, and report date. These records provide the
per-share rate, ex-date quantity, tax, fees, and correction/reversal lifecycle.

### Open Dividend Accruals

Required fields: account ID, currency, asset class, FX rate to base, symbol,
conid, ex date, pay date, quantity, tax, fee, gross rate, gross amount, net
amount, and code. These records are expected dividends that have not yet paid.

### Open Positions

Required fields: account ID, currency, asset class, FX rate to base, symbol,
conid, report date, quantity, multiplier, mark price, position value, side, and
level of detail. Only summary-level current positions participate in annual
income and yield calculations; lot rows must not be double counted.

### Financial Instrument Information

Required fields: asset class, symbol, currency, listing exchange, description,
conid, ISIN, multiplier, and security subtype where available. Listing exchange
maps a holding to its primary listing-market country. ISIN country prefix is a
secondary hint only when the listing exchange is absent. Unresolved records use
`UNKNOWN`; the report must not label this as issuer domicile or tax residence.

The guide also explains how to create the Flex Web Service token, find a Query
ID, configure numeric windows such as 7/30/90/365 days and optional `mtd`/`ytd`
windows, validate a query, rotate a token, and avoid sharing credentials.

## Output Contract

The top-level JSON contains:

- `start_date`, `end_date`, `base_currency`, `run_id`
- `realized_dividends`
- `expected_dividends`
- `summary`
- `annual_estimate`
- `coverage_note`
- `data_limitations`

Each realized or expected line contains:

- `symbol`, `payment_date`, `status`
- `gross`, `withholding_tax`, `fee`, `net`, `currency`
- `fx_rate_to_base`
- `base_gross`, `base_withholding_tax`, `base_fee`, `base_net`
- `quantity`
- `country`

`status` is exactly `REALIZED` or `EXPECTED`. The main table's “base-currency
amount” is `base_net`, while the JSON retains all four converted components for
reconciliation.

Missing financial values are `null`, never fabricated as zero. A line can be
retained with partial facts only when the known values remain useful and its
limitation is explicit.

## Paid Dividend Reconciliation

A dividend is realized only when a dividend `CashTransaction` confirms the cash
posting. Accrual rows alone do not prove payment.

Association uses account ID and conid first, then normalized symbol as a
fallback, together with currency and pay date. A bounded date tolerance may be
used for settlement/reporting differences and must be deterministic. Exact
matches outrank fallback matches. Ambiguous matches remain unassociated rather
than being assigned arbitrarily.

Associated `Change in Dividend Accruals` records provide gross amount, tax, fee,
quantity, and rate. Posting, correction, cancellation, and payout-reversal codes
must be reduced as a lifecycle so the same economic dividend is counted once.
Cash withholding rows are used as a reconciliation check and to fill tax only
when the association is unique. Tax and fee are exposed as positive deductions
even when Flex encodes them as negative cash or accrual values.

When no reliable accrual match exists, preserve the confirmed cash payment and
known currency/net amount, set unknown gross/tax/quantity fields to `null`, and
add a limitation. Do not infer a zero withholding rate.

## Expected Dividends

Expected lines come only from `Open Dividend Accruals`. Include a line when its
pay date falls inside the inclusive requested range. Use IB's quantity, gross,
tax, fee, and net values directly after sign normalization and base conversion.
Do not combine expected values with realized totals.

If an expected line later appears as a paid cash transaction in the same Flex
document, realized status wins and the open accrual is excluded to avoid double
counting.

## Aggregation

All portfolio-wide totals use the row's IB-provided `FX Rate to Base`:

- Realized and expected gross, withholding, fee, and net totals are separate.
- Currency attribution groups native gross, withholding, fee, and net by
  original currency; native amounts from different currencies are never added.
- Country attribution groups base-currency gross, withholding, fee, and net by
  primary listing-market country, with an `UNKNOWN` bucket.
- Highest-contributing holdings rank symbols by realized base-currency net
  income. Ties use symbol ascending for deterministic output.

If a required FX rate is missing, keep the native-currency line, set its base
fields to `null`, exclude it from base totals, and disclose the exclusion. Do not
apply a guessed or current market FX rate.

## Annual Income Estimate

The estimate is history-based and makes no Gateway or market-data request.

For each current long stock or fund position:

1. Reduce trailing accrual lifecycle records to unique economic dividends.
2. Sum positive per-share gross rates with ex dates in the latest available
   365-day interval ending on `end_date`.
3. Multiply this trailing per-share total by the current position quantity.
4. Convert with the current position's Flex FX rate.
5. Estimate net income only when the symbol has a reliable trailing effective
   withholding rate. Otherwise report estimated net as `null`.

The gross portfolio estimate is the sum of base-currency estimates. The
portfolio estimated dividend yield is:

```text
estimated annual gross dividend income in base currency
-------------------------------------------------------
current base market value of all long stock/fund positions
```

The denominator includes non-dividend-paying long stocks and funds. It excludes
cash, options, other derivatives, and short positions. Gross yield is used
because net tax estimates can legitimately be unavailable.

If the selected Flex result covers fewer than 365 days, output the observed
period's current-quantity run-rate lower bound and `history_days_covered`; do not
scale it mechanically to one year. Mark the portfolio yield incomplete.

## Setup and Conversational Onboarding

The runtime returns structured, non-secret setup errors:

- `setup_required`: token or `query_ids` is absent.
- `coverage_required`: no configured query can cover the requested range and
  annual-history requirement.
- `query_update_required`: the fetched query lacks a required section or field.

Each response includes the local path to `flex-query-setup.md`, missing item
names, and a safe next action. It never includes configured values.

The skill instructs the agent to ask for one item at a time: desired window,
Query ID, then token only if absent. `configure_flex.py` gains an stdin token
mode so the credential does not appear in process arguments. It atomically
writes the ignored `.ib-suite/config.yaml`, never echoes credentials, validates
the staged config, and requires explicit user confirmation before replacing an
existing token or window.

After configuration, the agent reruns the dividend command and reports the
actual validation result. Local persistence does not imply the remote Query is
valid.

## Logging and Security

The CLI emits structured logs to stderr and the report JSON to stdout. Default
level is `INFO`; `--log-level DEBUG` enables diagnostic detail. Every run has a
random `run_id` included in logs and output.

Log events cover phase transitions, selected window key, requested/available
coverage, Flex handshake stage, section record counts, association success and
failure counts, calculation stage, and elapsed time.

A central sanitizer removes tokens, Query IDs, account IDs, reference codes,
request parameters, URLs, and other credential-like values from service errors.
Raw XML and complete financial rows are never logged. Debug logging may show
field names, counts, dates, currencies, and hashed or truncated non-account
identifiers only. Sanitization tests inspect both stdout and stderr.

The skill preserves the repository's hard read-only boundary: no order imports,
no order methods, no Gateway connection, no market-data request, and no account
data persistence.

## Errors and Partial Data

Invalid dates, missing configuration, Flex service errors, invalid XML, missing
sections/fields, unresolved base currency, missing FX rates, ambiguous dividend
associations, and insufficient history have distinct actionable messages.

Structural problems that make the report unreliable fail the command. Row-level
problems that can be isolated retain valid rows and populate `data_limitations`.
The command never silently substitutes zero, guesses a country, converts with a
non-Flex FX rate, or combines realized and expected income.

## Testing

Follow red-green-refactor for every production behavior. Tests cover:

- Parsing and required-field validation for all six Flex sections.
- Paid cash/accrual/tax association by conid and symbol fallback.
- Multiple dividends, same-day events, currencies, accounts, fractional shares,
  tax, and fees.
- Posting, correction, cancellation, and payout reversal without duplication.
- Inclusive boundaries and exclusion of out-of-range records.
- Base conversion, missing FX behavior, and native-currency preservation.
- Listing-exchange country mapping, ISIN fallback, and `UNKNOWN`.
- A complete 365-day estimate and incomplete-history lower bound.
- Empty positions/dividends, non-dividend holdings, funds, shorts, and options.
- Missing token/query map, inadequate windows, missing fields, invalid XML, and
  sanitized Flex service failures.
- Stdin token setup, atomic writes, and explicit overwrite protection.
- stderr logging, single-object stdout, run correlation, and secret redaction.
- An end-to-end CLI run using a desensitized multi-section Flex fixture.
- Valid OpenClaw frontmatter, `name == directory`, `{baseDir}` paths, and index
  routing/discovery text.

Run the new skill tests first, then the full `skills` test suite. Manually verify
that no new file imports an order API or calls Gateway/market-data methods.

## Acceptance Criteria

- A valid configured query produces separate realized and expected tables for
  an inclusive date range and every requested summary.
- Base totals reconcile to line items with available Flex FX rates.
- Annual estimates use only historical Flex facts and current Flex positions.
- Missing or ambiguous facts are null and disclosed, never guessed.
- First-run and invalid-query states point to a complete standalone setup guide
  and support safe conversational configuration.
- Logs make stage and association failures diagnosable without leaking secrets
  or corrupting stdout JSON.
- The skill performs no Gateway, market-data, order, or persistence operation.
- Relevant and full test suites pass.

## External References

- [IBKR Cash Transactions](https://www.ibkrguides.com/reportingreference/reportguide/cash%20transactionsfq.htm)
- [IBKR Change in Dividend Accruals](https://www.ibkrguides.com/reportingreference/reportguide/change%20in%20dividend%20accrualsfq.htm)
- [IBKR Open Dividend Accruals](https://www.ibkrguides.com/reportingreference/reportguide/opendividendaccruals.htm)
- [IBKR Open Positions](https://www.ibkrguides.com/reportingreference/reportguide/open%20positionsfq.htm)
- [IBKR Financial Instrument Information](https://www.ibkrguides.com/reportingreference/reportguide/financialinstrumentinformationfq.htm)
