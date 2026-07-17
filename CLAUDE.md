# CLAUDE.md

Project-level, long-lived instructions for any AI agent working in this repo.
This file describes the **real structure and constraints** of this repository, not
a generic template. Every command, path, and dependency below comes from the
actual tree; when in doubt, trust the files, not the directory names.

## 1. Project Overview

This is an **OpenClaw multi-skill monorepo** (not a single Anthropic Skill: there
is no `agents/openai.yaml`, no `references/` or `assets/` directory, and no
`validate.py` / `package_skill.py`). The goal is to pull Interactive Brokers (IB)
account data **read-only** and turn it into structured portfolio diagnostics.

Everything lives under `skills/ib-suite/`, which is the single installable unit.
It contains **one index skill + five functional skills + one shared library**:

- **`ib-suite`** (index) — the router/onboarding skill. `always: true`, no config
  gate. It runs nothing itself; it tells you (and OpenClaw) which sub-skill to
  run, in what order, and it owns first-run config generation.
- **`ib-gateway`** — read-only ingestion. Command `/ib-sync` connects to IB
  Gateway (`readonly=True`) or reads a Flex report, and lands data in the local
  lake. **Never places orders, never imports an order API.**
- **`ib-account-overview`** — command `/ib-account-overview`. Live read-only
  account snapshot (equity, cash, buying power, margin, liquidity, P&L) with a
  per-currency breakdown. **Prints to stdout; persists nothing.**
- **`ib-positions-overview`** — command `/ib-positions-overview`. Live read-only
  enriched positions list, ranked four ways with the most concentrated name
  flagged. **Prints to stdout; persists nothing.**
- **`ib-daily-pnl`** — command `/ib-daily-pnl`. Live read-only breakdown of
  today's P&L (realized/unrealized), ranked winners/losers, by asset class and
  currency. **Prints to stdout; persists nothing.**
- **`ib-portfolio-analyst`** — command `/ib-analyze`. Offline diagnostics: reads
  the data lake and emits a P0–P3 graded findings report plus charts. **Never
  touches the network, never contacts IB, never places orders.**
- **`ib-common`** — a `pip`-installable shared package (config / schema / storage
  / metrics / charts), installed editable into the shared `.venv`. Depended on by
  every skill. **It is not itself a skill.**

- **Typical inputs:** a `config.yaml`; snapshot JSON under
  `.ib-suite/data/snapshots/<account>/<ts>.json`; optional bars / executions /
  dividends JSON arrays (matching the `DailyBar` / `Execution` / `Dividend`
  schema).
- **Typical outputs:** `report.md` plus, per chart, an `.html` (interactive) and
  a `.png` (static, via kaleido) in the `--out` directory. The three overview
  skills instead print a single parseable JSON object to stdout.
- **Explicitly out of scope:** placing / modifying / cancelling orders, live
  WhatIf margin checks, real-time market-data streaming, any write path into IB.
  These are **hard boundaries** — do not add them under the banner of
  "completeness".

## 2. Repository Structure

```text
skills/ib-suite/                        the single installable OpenClaw unit
  SKILL.md                              index/router skill (always:true, owns onboarding)
  scripts/setup_venv.sh                 idempotent venv bootstrap: pick Python>=3.11, install ib-common(editable)+deps
  scripts/init_config.py                deterministic first-run config generator (live/paper -> port); never overwrites without --force
  scripts/tests/test_init_config.py     tests for init_config
  ib-common/                            shared pip package (NOT a skill)
    pyproject.toml                      package metadata + runtime dependency declaration
    requirements.txt                    venv install entry (-e ./ib-common + ib_async/requests/pytest)
    config.example.yaml                 config.yaml template (holds every threshold default)
    ib_common/{config,schema,storage}.py  config loading / pydantic types / data-lake read-write
    ib_common/metrics/{returns,risk}.py   sharpe/sortino/calmar, max_drawdown/var/cvar/hhi
    ib_common/charts/render.py            fig -> {html,png} dual-artifact render
    tests/                              ib-common unit tests + fixtures
  ib-gateway/
    SKILL.md                            OpenClaw entry: /ib-sync registration + gating
    scripts/ib_sync.py                  /ib-sync entry: read-only pull -> snapshot + parquet
    scripts/flex_fetch.py               Flex Web Service two-step handshake + XML parse
    tests/                              gateway unit tests + fixtures
  ib-account-overview/
    SKILL.md                            OpenClaw entry: /ib-account-overview
    scripts/account_overview.py         live read-only account overview -> stdout JSON
    tests/                              account-overview tests + fixtures
  ib-positions-overview/
    SKILL.md                            OpenClaw entry: /ib-positions-overview
    scripts/positions_overview.py       live read-only enriched positions -> stdout JSON
    tests/                              positions-overview tests + fixtures
  ib-daily-pnl/
    SKILL.md                            OpenClaw entry: /ib-daily-pnl
    scripts/daily_pnl.py                live read-only today's P&L breakdown -> stdout JSON
    tests/                              daily-pnl tests + fixtures
  ib-portfolio-analyst/
    SKILL.md                            OpenClaw entry: /ib-analyze
    scripts/analyze.py                  /ib-analyze entry: read lake -> run diagnostics -> emit report
    ib_analyst/*.py                     diagnostic dimensions + findings vocabulary + report assembly
    tests/                              analyst tests + fixtures
docs/superpowers/{plans,specs}/         local-only design docs (gitignored, NOT distributed)
```

Do not invent `agents/`, `references/`, `assets/`. Runtime data and the real
`config.yaml` live under a **workspace-local `.ib-suite/`** directory that is
gitignored and created at runtime; the skill directory ships only code and
`config.example.yaml`.

## 3. Skill Architecture

- Each skill's `SKILL.md` is the **control plane**: trigger description, gating
  metadata, copy-pasteable commands, and the key constraints — no knowledge dumps.
- **Deterministic logic lives in scripts, not in SKILL.md.** IB connection,
  parsing, metrics, and report assembly all live in `scripts/` and package code;
  `SKILL.md` only invokes `.venv/bin/python {baseDir}/scripts/*.py`.
- **Reusable, offline-testable pure functions live in `ib-common`.** The **only
  networked code** (IB connection, Flex HTTP) is isolated in each skill's
  `scripts/`, hidden behind an injectable `client_factory` / `http_get` so the
  tests run against fixtures with no network. Every entry script that talks to IB
  connects with `readonly=True` and imports no order API.
- The `ib_analyst` package is **not installed**; `analyze.py` imports the sibling
  package via `sys.path.insert`. Keep this convention — new diagnostic modules go
  under `ib_analyst/`.
- The `ib-suite` **index skill owns onboarding**: it detects config, ensures the
  venv, asks live-vs-paper once, and calls `init_config.py`. The sub-skills stay
  gated on `config.yaml` until it exists.
- Domain knowledge and historical decisions live in `docs/superpowers/`
  (gitignored, local-only). **Read on demand**; do not load them wholesale into
  context, and do not assume they ship with the skill.

## 4. SKILL.md Rules

**Authoritative spec.** These bullets are *this repo's* constraints layered on
top of the OpenClaw skill format. Before changing any `SKILL.md` frontmatter,
read and conform to the two tracked spec docs (they ship with the repo):

- `docs/openclaw-creating-skills.md` — how to author a skill: required fields
  (`name`, `description`), optional keys (`user-invocable`, `command-dispatch`,
  `homepage`, …), `{baseDir}` resolution, and conditional activation / gating.
- `docs/openclaw-skill-format.md` — the on-disk format and the full
  `metadata.openclaw` field reference (`requires.bins`/`anyBins`/`env`/`config`,
  `envVars`, `primaryEnv`, `always`, `os`, `install`, …), plus naming/slug rules.

When a bullet below and the spec disagree, the **spec wins on format** (field
names, allowed keys, on-disk layout); the bullets only add **project rules**
(read-only boundary, `name == directory`, the `{baseDir}/../.venv` path). Any new
frontmatter key must exist in the spec's field reference — do not invent keys.

- Must keep valid YAML frontmatter that includes `metadata.openclaw` — this is how
  OpenClaw discovers and gates the skill; deleting or breaking it makes the skill
  untriggerable.
  - The **index** (`ib-suite`) uses `always: true`, `requires.bins: [python3]`,
    `os: [darwin, linux]`, and **no `requires.config`** (so onboarding can run
    before any config exists).
  - The **functional skills** use `requires.bins: [python3]`,
    `requires.config: [config.yaml]`, `os: [darwin, linux]`. `envVars` is optional
    (e.g. `ib-gateway` declares `FLEX_TOKEN` / `FLEX_QUERY_ID` as not required).
- `name` MUST equal the directory name (`ib-gateway`, `ib-account-overview`,
  `ib-positions-overview`, `ib-daily-pnl`, `ib-portfolio-analyst`, `ib-suite`) —
  lowercase and stable.
- `description` must convey all three of: what the skill does, when it triggers,
  and the read-only boundary. Every functional `description` starts with
  "Read-only" — preserve that when editing, and keep it narrow enough to avoid
  mis-firing.
- The body uses imperative, copy-pasteable commands. Commands use the `{baseDir}`
  placeholder and `.venv/bin/python`, never absolute paths. Note the venv is at
  the `ib-suite` root, so sub-skills reference it as `{baseDir}/../.venv/bin/python`.
- Split complex branches into scripts or `docs/`, not long procedures inside
  SKILL.md.
- When changing a trigger description, check both a **positive example (should
  trigger)** and a **near-miss (should NOT trigger)** to avoid missed or false
  triggers.

## 5. Development Workflow

1. Read only the files directly relevant to the task; when unsure of structure,
   search — don't guess.
2. Decide where the change belongs: SKILL.md (entry/gating) / scripts (entry
   logic) / `ib_common` (shared pure functions) / `ib_analyst` (diagnostic
   dimensions) / tests / docs.
3. Make the smallest change that works; reuse existing schema, the `Finding`
   vocabulary, `grade()`, `render()`, and storage helpers.
4. Follow TDD (the repo's existing convention): write a failing test → run red →
   implement → run green.
5. Do not do unrelated refactors, reformatting, or comment rewrites.
6. Run the relevant tests after changing (see §8).
7. Reconcile SKILL.md, scripts, `config.example.yaml` thresholds, schema, and
   tests with each other.
8. In your closing summary, state explicitly: what changed / what was verified /
   what was not verified / residual risk.

## 6. Coding Conventions

- **Language:** Python **>= 3.11** (enforced by `pyproject.toml`). Every module
  starts with `from __future__ import annotations`.
- **Types:** all data structures are `pydantic` v2 `BaseModel` (see
  `ib_common/schema.py`, which uses `computed_field` for derived values); type-
  annotate functions.
- **Naming:** modules are lowercase_with_underscores; a diagnostic module exposes
  `analyze(...) -> list[Finding]` and an optional `build_chart(...)`, and marks
  its dimension with a module-level `DIM` constant.
- **Comments:** docstring every module / public function to state intent (follow
  the surrounding density; per the repo's language rule, doc/code comments are in
  English).
- **Error handling:** raise exceptions with a reason on a missing file / invalid
  config (e.g. `FileNotFoundError`, `ValueError`, `FileExistsError`); do not
  swallow errors, and do not add defensive code for impossible cases.
- **Paths:** resolve from the project root or `Path(__file__)` (see the
  `sys.path.insert` in `analyze.py`, the `ROOT` in `setup_venv.sh`, and the
  default-template resolution in `init_config.py`); **never hardcode a user home
  or machine path**.
- **stdout:** entry scripts `print()` a structured result (a dict / paths / a JSON
  object) so an upper layer can parse it.
- **Dependencies:** runtime deps are declared in
  `skills/ib-suite/ib-common/pyproject.toml` (the library) and
  `requirements.txt` (extra runtime items). Current library deps: `pydantic>=2.6`,
  `pandas>=2.2`, `pyarrow>=15`, `numpy>=1.26`, `plotly>=5.20`, `kaleido>=0.2.1`,
  `ruamel.yaml>=0.18`; runtime extras add `ib_async>=1.0.1`, `requests>=2.31`,
  `pytest>=8.0`. **Do not add dependencies by default**; if you must, update both
  files and explain why.
- **Read-only invariant:** every IB connection uses `readonly=True`; no file may
  import an order API.

## 7. Script Requirements (`scripts/`)

- Entry scripts use `argparse`; validate arguments (e.g. `--config`,
  `--snapshot`) as they currently do; exit non-zero with an actionable message
  when a required input is missing.
- Network / IB access must go through an injectable factory (`client_factory`,
  `http_get`) so the tests run fully offline.
- Failure returns a non-zero exit code; the message explains the cause and a fix
  direction (e.g. "base currency unresolved: ...").
- Do not depend on undeclared local state; do not hardcode a token / account
  number / user directory.
- `setup_venv.sh` stays idempotent and re-runnable; after any change it must still
  build `.venv` from scratch in a clean environment.
- `init_config.py` stays deterministic and offline: it only rewrites the port for
  the chosen mode, preserves template comments (via `ruamel.yaml`), refuses to
  overwrite without `--force`, and never reads or writes a token.
- Prefer putting deterministic work in a script or package function over piling
  steps into SKILL.md.

## 8. Validation and Testing

This repo has **no** `validate.py` / `package_skill.py`. Validation is tests plus
manual review.

```bash
# First time, or after dependency changes: bootstrap the shared venv (idempotent)
bash skills/ib-suite/scripts/setup_venv.sh

# Full test run (current baseline: 101 passed)
skills/ib-suite/.venv/bin/python -m pytest skills -q

# Test a single skill
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-portfolio-analyst -q

# End-to-end report run (example; substitute real paths). Config and data are
# workspace-local under .ib-suite/ by convention.
skills/ib-suite/.venv/bin/python skills/ib-suite/ib-portfolio-analyst/scripts/analyze.py \
  --config .ib-suite/config.yaml \
  --snapshot .ib-suite/data/snapshots/<account>/<ts>.json \
  --out .ib-suite/data/runs/$(date +%Y%m%dT%H%M%S)
```

Manual checklist (cover at least these after a change):

- Every `SKILL.md` has valid YAML frontmatter that includes `metadata.openclaw`.
- Each `SKILL.md` `name` equals its directory name.
- Script paths referenced from SKILL.md exist and run under `.venv/bin/python`
  (functional skills reference the venv as `{baseDir}/../.venv/bin/python`).
- The example analyst input produces `report.md` plus the matching `.html` /
  `.png` (covered by `ib-portfolio-analyst/tests/test_analyze_e2e.py`).
- You did not commit `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`,
  `data/runs/`, `.ib-suite/`, a real `config.yaml`, or a live snapshot.

> To verify `/ib-sync` (and the three live overview skills) against a real
> connection instead of fixtures, start IB Gateway locally (paper 4002 / live
> 4001) with the Read-Only API enabled. That is manual verification, outside the
> CI/unit-test scope.

## 9. Change-Specific Checks

- **Editing a trigger description (SKILL.md `description`):** give a positive
  example that should trigger and a near-miss that should not; confirm it carries
  "capability + trigger condition + read-only boundary".
- **Editing a workflow / command:** confirm the command is copy-paste runnable,
  the `{baseDir}` placeholder is correct, and the failure path / preconditions are
  clear.
- **Editing a script:** run the matching tests, covering normal / missing-arg /
  invalid-input; confirm the exit code and error message are correct.
- **Adding a diagnostic module (`ib_analyst/`):** expose `analyze()` returning a
  `Finding` list, reuse `grade()` and `thresholds`, mark it with a `DIM` constant;
  any new threshold MUST also be added to `ib-common/config.example.yaml` under
  `thresholds:`; wire it into `analyze.py`'s `run()`; add tests.
- **Adding a chart:** return a plotly `Figure` from `build_chart()` and hand it to
  `render()` for the dual artifact — do not do file I/O inside a business
  function.

## 10. Safety and Security

- **Never place orders:** do not import or call any IB order API; the connection
  is always `readonly=True`.
- Do not read / commit / print any token, secret, cookie, or credential; the Flex
  token is passed via environment only (e.g. `$FLEX_TOKEN`).
- Do not write a local absolute path into a version-controlled file; examples use
  placeholders (`<account>`, `<ts>`).
- Do not make unnecessary network requests; do not install dependencies from an
  unknown source.
- Do not perform risky deletes / overwrites unless the user explicitly asks.
- Do not modify configuration the user did not ask you to change; **do not
  overwrite the user's existing uncommitted changes**.
- Every committed fixture must be desensitized; **never commit a real
  `config.yaml` or a live snapshot**.

## 11. Packaging / Distribution

This project loads as OpenClaw skills; there is no standalone packaging script.
When distributing / delivering:

- Ship `skills/ib-suite/` whole — it is the single installable unit
  (`SKILL.md` + `scripts/` + `ib-common/` + every sub-skill, with `ib_analyst`
  traveling inside `ib-portfolio-analyst`).
- Exclude `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `data/runs/`,
  `.ib-suite/`, `docs/superpowers/`, and the real config/snapshots (all covered by
  `.gitignore`).
- Confirm every script referenced by a SKILL.md and every depended-on package is
  included; check filename case.
- Pass §8 tests and the manual checklist before packaging / delivery.


## 12. Definition of Done

All of the following must hold:

- The target functionality is implemented and the change scope matches the request
  (no unrelated refactors).
- SKILL.md, scripts, `ib_common` schema/thresholds, and tests are consistent with
  each other.
- `skills/ib-suite/.venv/bin/python -m pytest skills -q` passes (record the count).
- No broken references, no dead commands, no code crossing the read-only boundary.
- No sensitive data or unrelated files introduced.
- The final reply states explicitly: what changed / what was verified / what was
  not verified / residual risk.
