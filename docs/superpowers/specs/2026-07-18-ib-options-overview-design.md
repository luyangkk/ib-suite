# IB Options Overview Skill Design

## Goal

Add a read-only `ib-options-overview` skill under `skills/ib-suite/` that
retrieves every open IBKR option position and emits a JSON option-risk overview.
The result must expose each contract's holdings, valuation, implied volatility,
Greeks, and moneyness, followed by account-level Greeks, daily theta decay,
expiration distribution, and underlying concentration.

## Scope

The skill exposes `/ib-options-overview` and connects to IB Gateway with
`readonly=True`. It reads the account's live `portfolio()` state, filters
`OPT` contracts, and requests live or delayed market data for each option.
Nothing is persisted.

The new skill contains:

- `SKILL.md` with the trigger description, prerequisites, copy-pasteable
  command, data limitations, and strict read-only boundary.
- `scripts/options_overview.py` with the CLI, read-only IB client, pure report
  construction, and aggregation helpers.
- `tests/` with offline fixtures and a fake injected client.

`skills/ib-suite/SKILL.md` is updated to route option-position and option-risk
requests to the new skill. Shared Pydantic response models live in
`ib-common/ib_common/schema.py`.

## Runtime Data Flow

1. Load `config.yaml` and open an IB Gateway connection with `readonly=True`.
2. Resolve the managed account and account base currency. Obtain local-to-base
   FX rates from `$LEDGER-ExchangeRate` account values.
3. Read `portfolio(account)` and retain all rows whose contract security type
   is `OPT`.
4. For every retained contract, request market data using `reqMktData`, wait a
   bounded period for IB to populate the ticker, then always cancel every
   market-data subscription.
5. Map `ticker.modelGreeks` to implied volatility, Delta, Gamma, Theta, and
   Vega. Missing or unavailable data stays `null`; it is never converted to
   zero.
6. Use the option contract fields for the underlying symbol, right, strike,
   expiry, and multiplier. Use the portfolio row's IB-computed average cost,
   market price, market value, and unrealized P&L without recomputation.
7. Read the underlying price from the model-Greeks payload when available,
   otherwise request or reuse an underlying ticker. Derive moneyness from the
   underlying price and strike. A missing price produces a `null` moneyness
   value and a limitation rather than a guess.
8. Convert monetary exposures to account base currency only with an available
   IB FX rate. An affected contract is excluded from the relevant
   cross-currency aggregate and its cause is recorded; the aggregate is `null`
   only when no contract can contribute.

## Per-Contract Data Contract

Each item in `options[]` has the following user-facing data:

1. `underlying_symbol`
2. `right` (`CALL` or `PUT`)
3. `position_side` (`LONG` or `SHORT`)
4. `strike`
5. `expiry_date`
6. `days_to_expiry`
7. `quantity`
8. `avg_cost`
9. `market_price`
10. `market_value`
11. `unrealized_pnl`
12. `implied_volatility`
13. `delta`
14. `gamma`
15. `theta`
16. `vega`
17. `moneyness` (`ITM`, `ATM`, `OTM`, or `null`)

The item also retains `currency`, `multiplier`, base-currency value/P&L where
available, and `greeks_status` explaining whether its market data is complete.

`days_to_expiry` is calendar days inclusive of the report date:
`expiry_date - report_date + 1`. Thus an option expiring on the report date has
one day remaining.

Moneyness uses the current underlying price and contract strike. A Call is ITM
when the underlying is above strike and a Put is ITM when the underlying is
below strike. Equal values are ATM; opposite cases are OTM.

## Aggregation Semantics

The stdout response is one JSON object with `account_id`, `base_currency`,
`ts`, `options`, `summary`, and `data_limitations`.

`summary` contains:

- `total_delta`, `total_gamma`, `total_theta`, and `total_vega`: each option's
  IB Greek multiplied by its signed position quantity and contract multiplier.
  Each aggregate uses only contracts with that available Greek and a usable
  cross-currency conversion. It is `null` only when no contract can contribute.
  The response records contributor and exclusion counts, plus the excluded
  contracts and their reasons, so a partial aggregate is never presented as a
  complete account total.
- `daily_time_value_decay`: `-total_theta`, expressed in the account base
  currency when at least one valid theta contribution exists. This makes a
  positive value the expected one-day time-value loss for the covered book.
- `expiration_distribution`: positions grouped by `expiry_date`, with contract
  count, signed quantity, and absolute base-currency market value where
  convertible.
- `underlying_concentration`: positions grouped by underlying symbol. Its
  `weight` is the underlying's absolute base-currency option market value divided
  by the total absolute base-currency option market value. Long and short legs
  do not net for concentration.

All market data honors the existing configuration's requested market-data type.
Delayed quotes are accepted. A missing entitlement, delayed quote, absent
model-Greeks response, or unavailable underlying price is exposed in
`data_limitations`, not hidden.

## Error Handling

- An empty option book succeeds with `options: []`, zero-valued monetary
  distributions, and Greek totals that are `null` because no observations
  exist.
- Missing config, a Gateway connection failure, no managed account, unresolved
  base currency, malformed expiry, or invalid multiplier causes a non-zero exit
  with an actionable message.
- Missing per-contract market data or Greeks does not fail the full report. The
  contract remains visible with `null` fields and an explicit limitation.
- All subscriptions opened by the skill are cancelled in `finally` paths before
  disconnecting.

The script imports no order API and has no order-placement, modification, or
cancellation path.

## Testing Strategy

Tests use injected fake clients and desensitized JSON fixtures, with no network
or Gateway connection. They cover:

- Call and Put contracts; long and short position signs.
- Contract multiplier scaling for all aggregate Greeks.
- Inclusive calendar-day DTE and ITM/ATM/OTM classification.
- IB-provided market value and unrealized P&L preservation.
- Missing or delayed Greeks, missing underlying price, and no false zero
  aggregates.
- FX conversion, missing FX behavior, expiration distribution, and absolute
  market-value underlying concentration.
- Empty option accounts, client disconnects, and all market-data subscriptions
  being cancelled.
- Invalid contract data and CLI error messages.
- Valid SKILL.md metadata, correct `{baseDir}` command, index routing, and the
  absence of forbidden order APIs.

No dependency is added.
