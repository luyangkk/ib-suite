# IB Options Moneyness Fallback Design

## Goal

Improve the existing read-only `ib-options-overview` skill so every open option
position receives an `ITM`, `ATM`, or `OTM` classification whenever IB can
provide either the option model's underlying price or an independent quote for
the underlying. Do not add option-chain discovery or change the JSON response
schema.

## Scope and Constraints

- Only classify existing open option positions returned by `portfolio()`.
- Keep every IB connection `readonly=True` and import no order API.
- Persist no account or market data.
- Honor the configured live, frozen, delayed, or delayed-frozen market-data
  type.
- Add no dependency and do not modify the user's runtime configuration.
- Preserve the current JSON fields and moneyness semantics.
- Always cancel every option and underlying market-data subscription.

## Runtime Data Flow

1. Load the account and retain existing option positions as today.
2. Subscribe to option market data and wait up to four seconds for the normal
   option price and model-Greeks payload.
3. Use a valid positive finite `modelGreeks.undPrice` as the preferred
   underlying price.
4. Collect positions that still lack an underlying price and deduplicate them by
   `(symbol, currency)`.
5. Build and qualify one `SMART` stock contract for each missing underlying,
   then subscribe to its market data while keeping the option subscriptions
   open.
6. Poll every 0.25 seconds for at most 20 seconds. Stop early when every missing
   underlying has a valid price. Option model data may continue to arrive during
   this fallback window.
7. Resolve each position's underlying price in this order:
   `modelGreeks.undPrice`, underlying `marketPrice()`, underlying `close`.
8. Reuse one resolved underlying price for all open Call and Put positions with
   the same `(symbol, currency)`.
9. Pass the resolved price into the existing deterministic moneyness classifier.
10. Cancel every successfully opened option and underlying subscription in a
    `finally` path before disconnecting.

## Price Validation and Classification

An underlying price is usable only when it is numeric, finite, and greater than
zero. Values such as `None`, `NaN`, infinity, zero, and negative IB sentinel
values are unavailable rather than real prices.

Classification keeps the current exact rules:

- Call: `ITM` above strike, `ATM` at strike, otherwise `OTM`.
- Put: `ITM` below strike, `ATM` at strike, otherwise `OTM`.

If both the option model and independent underlying quote remain unavailable,
the affected position keeps `underlying_price: null` and `moneyness: null` with
the existing explicit `data_limitations` entry. One missing symbol does not
erase classifications for other positions.

## Components and Interfaces

The change remains within
`skills/ib-suite/ib-options-overview/scripts/options_overview.py` and its tests.
Small private helpers isolate:

- validation of an underlying price;
- bounded condition polling;
- deduplication and subscription of missing underlying contracts;
- resolution of model, live/delayed, and close-price fallbacks.

The public `options_overview()` function, response Pydantic models, and CLI
arguments remain unchanged. The live client continues to be injectable for
fully offline tests.

## Error Handling

- Missing per-symbol quotes remain partial-data limitations, not report-level
  failures.
- Contract qualification, Gateway disconnection, or other systemic IB failures
  continue to propagate instead of being silently swallowed.
- Cleanup covers partial setup: every subscription opened before an exception is
  cancelled.
- An empty option book succeeds without creating underlying contracts or market
  data subscriptions.

## Human-Readable Output

The script continues to print one parseable JSON object. `SKILL.md` instructs
the caller to render classified positions in a compact table grouped by status,
including the underlying price and absolute in/out-of-the-money distance when
available. Multiple strikes for the same underlying, right, expiry, and status
may be combined without hiding distinct states.

Example:

| Status | Positions |
|---|---|
| **ITM** | BABA $105 Call (underlying about $115.18, ITM by about $10.18) |
| **OTM** | AAPL $335 Call (underlying about $333.69, OTM by about $1.31) |
| **OTM** | GOOG $400/$405 Call, TSLA $427.5 Call |
| **OTM** | QQQM $265/$275 Put (underlying about $285.85) |

The presentation layer computes distance from the existing strike and resolved
underlying price; no new response field is required. Positions without a
classification appear in a separate `UNKNOWN` row with the relevant data
limitation stated below the table.

## Testing Strategy

Follow test-driven development and verify each new behavior fails before its
implementation is added. Offline tests cover:

- model `undPrice` wins and avoids an underlying subscription;
- missing model data creates one underlying subscription per `(symbol,
  currency)` and fills every matching position;
- `marketPrice()` wins over `close` and an unavailable market price falls back
  to close;
- `None`, `NaN`, infinity, zero, and negative prices remain unavailable;
- polling stops early when data arrives and exits at the 20-second bound when it
  does not;
- missing one symbol leaves only its positions unclassified;
- option and underlying subscriptions are cancelled on success and failure;
- the connection remains read-only and the module contains no order API path;
- `SKILL.md` retains valid OpenClaw metadata and its command remains
  copy-pasteable.

Run the focused option-overview tests, then the complete `skills` test suite.
After automated verification, run the real read-only command against the local
IB Gateway and confirm previously null open positions receive moneyness values.
If Gateway connectivity or market-data permissions prevent this manual check,
report it as unverified rather than treating unit tests as live evidence.
