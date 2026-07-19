# First-run config detection & onboarding — design

Date: 2026-07-17
Status: approved (brainstorming)
Scope: `skills/ib-suite/`

## Problem

`config.yaml` is the only thing standing between a fresh checkout and a working
run, but nothing helps a first-time user create it. Worse, the sub-skills gate on
it: `ib-gateway` and `ib-portfolio-analyst` both declare
`metadata.openclaw.requires.config: [config.yaml]`. Per OpenClaw's gating docs,
`requires.config` means "this `openclaw.json` path must be truthy" and a failed
gate **prevents the skill from triggering**. So the skill that needs config can't
run without config, and it can't guide the user to create config either — a
chicken-and-egg problem.

We want first-run detection: when config is absent, talk to the user, collect the
one decision that actually matters, and generate a valid `config.yaml`.

## Key facts (from code)

- `ib_common.config.Config` gives **every field a safe default**; an empty file
  loads fine. The only value a machine can't safely assume is
  `connection.port` — 4002 (paper) vs 4001 (live).
- `storage.root` default `.ib-suite/data` and `base_currency: null` (follow
  account BASE) are already the recommended values; no need to prompt for them.
- `resolve_base_currency` only errors when there's *no* account BASE *and* config
  default is null — doesn't happen on a normal IB connection.
- Config is loaded via `ruamel.yaml` (round-trip capable), so we can rewrite the
  template while preserving its inline comments.
- Runtime config lives at `<workspace>/.ib-suite/config.yaml` by project
  convention (kept out of the skill dir, gitignored).

## Decisions

1. **Onboarding lives in the top-level `ib-suite` index.** The index does no real
   work and must always be reachable, so it owns first-run setup and routing; the
   sub-skills keep doing the work.
2. **Interactive prompt + deterministic script.** Conversation stays in
   `SKILL.md`; config generation goes into a new deterministic script
   `init_config.py`. This matches CLAUDE.md §3 ("deterministic logic in scripts")
   and the OpenClaw docs ("keep SKILL.md concise").
3. **Collect exactly one decision: paper vs live**, defaulting to **live (4001)**.
   `storage.root` and `base_currency` use template defaults (they already are the
   best practice). `$FLEX_TOKEN` is mentioned in prose only, never written to the
   file or read by the script.
4. **Detection target path is `.ib-suite/config.yaml`** (relative to workspace
   root / CWD). Executable commands use the relative path; prose may prefix
   `<workspace>/` for human readability. `<workspace>` is NOT a resolved
   placeholder — only `{baseDir}` is — so it must never appear in a runnable
   command.

## Architecture

```
ib-suite/SKILL.md (always:true, no requires.config)
  └─ "0. First-run setup" section: detect → ask paper/live → call script → receipt
       └─ scripts/init_config.py  (deterministic: template → override port → write)
ib-gateway/SKILL.md            (requires.config unchanged — gated until config exists)
ib-portfolio-analyst/SKILL.md  (requires.config unchanged)
```

Responsibility split: index = onboarding + routing; sub-skills = the work.
Dialogue in SKILL.md; deterministic generation in the script.

### Gating change

- Top-level `ib-suite/SKILL.md`: add `always: true`, remove its
  `requires.config`. The index must be reachable regardless of config state.
- `ib-gateway` / `ib-portfolio-analyst`: gating **unchanged**. When config is
  absent they don't trigger; the index picks up the slack and guides setup.

## `init_config.py` contract

Deterministic, no dialogue. The Agent (via SKILL.md) collects the user's choice
and passes it as an argument.

Interface (argparse):

```
--template <path>   default {baseDir}/ib-common/config.example.yaml
--out <path>        default .ib-suite/config.yaml
--mode {live,paper} default live   → connection.port 4001/4002
--force             default off; without it, refuse to overwrite an existing --out
```

Behavior:

1. Read `--template` with `ruamel.yaml` `YAML(typ="rt")`, preserving comments and
   all thresholds. Never hardcode config content.
2. Override `connection.port` by `--mode` (live=4001, paper=4002). Leave
   `storage.root` and `base_currency` at template defaults.
3. Ensure the parent dir of `--out` exists, then write.
4. Safety (CLAUDE.md §10): if `--out` exists and `--force` is not set → raise,
   exit non-zero, **never overwrite** an existing user config; message tells the
   user to pass `--force` to rebuild.
5. Print a structured result to stdout (out path + final mode/port) for the
   caller to parse.
6. No network, never print any token.

`$FLEX_TOKEN`: prose-only hint ("export FLEX_TOKEN=… before pulling Flex
dividends/history"); not written to config, not read by the script.

## SKILL.md "0. First-run setup" flow

Command-style steps in the top-level index:

1. **Detect**: `test -f .ib-suite/config.yaml`.
   - Exists → print "config ready", jump to Run guide, don't bother the user.
   - Missing → run onboarding below.
2. **Ensure venv** (only if missing):
   `test -d {baseDir}/.venv || bash {baseDir}/scripts/setup_venv.sh`.
3. **Ask** one question: live (4001) or paper (4002)? Default live.
4. **Generate**:
   ```bash
   {baseDir}/.venv/bin/python {baseDir}/scripts/init_config.py \
     --mode live --out .ib-suite/config.yaml
   ```
5. **Receipt**: report out path + mode/port; remind: start IB Gateway with
   read-only API before `/ib-sync`; `export FLEX_TOKEN=…` for Flex data.
6. **Handoff**: point to `/ib-sync` → `/ib-analyze`.

Prose may say `<workspace>/.ib-suite/config.yaml`; commands use the relative
`.ib-suite/config.yaml`. No literal `<workspace>` in any runnable command.

## Testing (TDD)

New `skills/ib-suite/scripts/tests/test_init_config.py`:

1. `--mode live` → generated `connection.port == 4001`.
2. `--mode paper` → `port == 4002`.
3. Default mode (omitted) → live/4001.
4. thresholds, `storage.root`, `base_currency` match the template (untouched).
5. Existing `--out` + no `--force` → raises, non-zero exit, original file
   unchanged.
6. Existing `--out` + `--force` → overwrites.
7. Generated YAML loads via `ib_common.config.load_config` (round-trip check).

Follow the repo's red→green TDD: failing tests first, then implement.

## Acceptance (CLAUDE.md §12)

- Top-level SKILL.md frontmatter valid, has `always: true`, drops
  `requires.config`; sub-skill gating unchanged.
- Full suite passes; record count (baseline 54 → 54 + new cases).
- `init_config.py` covers: live/paper, default, refuse-overwrite, `--force`,
  load round-trip.
- SKILL.md commands copy-paste runnable, `{baseDir}` correct, no literal
  `<workspace>` in commands.
- No code crossing the read-only boundary; no token printed/written; no real
  `config.yaml` committed.

## Out of scope (YAGNI)

- No change to `ib_sync` / `analyze` existing `--config` behavior.
- No interactive TUI.
- No thresholds collection.
- Withholding-tax parsing and landing bars/dividends into the lake remain future
  iterations.
