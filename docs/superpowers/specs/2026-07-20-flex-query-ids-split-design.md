# Flex query-ids split design

## Goal

Separate the Flex Query ID windows used by `ib-trade-history` from those used by
`ib-dividend-income` so each skill resolves only the saved queries built for its
own report sections. Preserve the shared read-only Flex token and the existing
window-selection behaviour. Add no order placement, market-data, or Gateway
path.

## Confirmed failure mode

`FlexCfg` currently exposes one shared `flex.query_ids` map. Both skills read and
both writes (`configure_flex.py`) target this single map. A Query ID registered
for trade history contains only the `Trades` section, so when dividend income
resolves the same window it fetches a report missing the six dividend sections
and returns `query_update_required`. The model cannot express which skill a given
Query ID serves. This reverses the earlier "one shared 7-section Query ID"
decision on purpose.

## Design

### 1. Schema — `ib_common/config.py`

`FlexCfg` replaces `query_ids` with two independent top-level maps, symmetrically
named, both `dict[str, str]`:

- `trade_history_query_ids`
- `dividend_query_ids`

The shared `token` field is unchanged. The window-key validator (positive digit
day count, or `mtd` / `ytd`) is extracted into a reusable classmethod applied to
both fields. `coerce_numbers_to_str=True` stays.

Hard cutover: no `query_ids` alias and no historical fallback. A stale
`flex.query_ids` key in a local config is silently ignored by pydantic, so each
skill reports its normal `setup_required` for its own empty map until the user
re-registers. This is the accepted breaking change; local `.ib-suite/config.yaml`
is gitignored and re-registered once via `configure_flex.py`.

### 2. Write path — `configure_flex.py`

Add a `--target {trade_history,dividend}` argument, required whenever `--window`
is supplied (a token-only invocation needs no target). `configure_flex()` gains a
`target` parameter that selects which map receives the merge, de-duplication, and
clash detection. Token persistence, atomic temp-file write, and reload
validation are unchanged and remain shared. No default target — the caller must
state intent so a window is never written to the wrong skill's map.

### 3. Read path

- `dividend_income.py`: read `cfg.flex.dividend_query_ids`; the
  `setup_required` / `coverage_required` missing names become
  `flex.dividend_query_ids`; `_validation_missing` matches the new loc.
- `trade_history.py`: read `cfg.flex.trade_history_query_ids`.
- `flex.py` `select_flex_window` / `select_numeric_window` signatures are
  unchanged; they already take a map argument. Only the call sites change which
  map they pass.

### 4. Documentation

- `config.example.yaml`: show both maps with commented examples.
- `ib-dividend-income/SKILL.md`, `ib-trade-history/SKILL.md`, `ib-suite/SKILL.md`:
  update setup-state key names and add `--target` to `--window` commands.
- Both `flex-query-setup.md` guides: `--window` commands carry `--target`; state
  that the dividend target needs a query with the six dividend sections (the full
  7-section query still works), while the trade-history target may use a
  `Trades`-only query. The two skills now register independent Query IDs and no
  longer must share one.

### 5. Tests (TDD, red before green)

- `test_config.py`: new schema loads both maps; a `flex.query_ids` key no longer
  populates either map.
- `test_flex.py`: window selection behaviour unchanged (map argument).
- `test_configure_flex.py`: `--target` routes writes to the correct map; missing
  `--target` with `--window` errors; clash detection is per-map.
- `test_dividend_income_cli.py`: reads `dividend_query_ids`; setup/coverage
  states name the new key.
- `test_trade_history.py`: reads `trade_history_query_ids`.

## Impact and risk

- Breaking: existing local `flex.query_ids` becomes inert; user re-registers once
  per skill. Accepted.
- Read/write paths stay read-only and Flex-only: no Gateway, no market data, no
  orders.
- Credentials never enter stdout, logs, or version control; the token remains
  file-only and passed via `--token-stdin`.
