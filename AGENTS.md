# Project instructions

## Scope

`skills/ib-suite/` is one portable Agent Skill. It contains exactly one
`SKILL.md`; capability instructions belong in `references/`. The package stays
read-only with respect to Interactive Brokers: never add an order API or a path
that places, modifies, or cancels orders.

## Paths and runtime state

- `SKILL_ROOT` is the installed `ib-suite` directory and is read-only.
- `WORKSPACE_ROOT` is an existing writable user workspace.
- All mutable state lives under `WORKSPACE_ROOT/.ib-suite/`.
- `scripts/setup_venv.sh` requires `--workspace-root` and delegates lifecycle
  logic to `scripts/bootstrap.py`.
- Do not use `{baseDir}`, a user home path, a sibling Skill, or the current
  directory as a runtime-path contract.

## Dependencies and tests

- Python 3.11+ on macOS and Linux is supported.
- Runtime, build, and test dependencies are defined by the committed
  `requirements-*.in` and `requirements-*.lock` files. Regenerate them with
  `uv==0.12.13` when inputs change.
- Write a failing pytest first, implement the smallest change, then run the
  focused test before the wider suite.
- Validate frontmatter, links, payload shape, path isolation, and bootstrap
  lifecycle with `skills/ib-suite/tests/test_distribution_contract.py` and
  `skills/ib-suite/scripts/tests/test_bootstrap.py`.

## Safety

Never read, commit, or print Flex tokens, Query IDs, account numbers, or live
snapshots. Do not remove user workspace state during an install, bootstrap, or
update. The only managed symlink is `.ib-suite/venv`, and it must resolve under
`.ib-suite/venvs/`.
