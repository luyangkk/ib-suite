# Contributing to ib-suite

Thanks for your interest in improving ib-suite. This is a **read-only**
Interactive Brokers diagnostics suite — please read the boundaries below before
opening a PR.

## Read-only invariant (non-negotiable)

- Every IB connection uses `readonly=True`. No module may import an order API.
- No order placement / modification / cancellation, no live WhatIf margin checks,
  no real-time market-data streaming, no write path into IB — ever.
- Never commit or print a token, Query ID, account number, or user path.

## Development setup

Requires Python >= 3.11 on macOS or Linux.

```bash
# Bootstrap the shared virtualenv (idempotent; installs ib-common editable + deps)
bash skills/ib-suite/scripts/setup_venv.sh
```

Runtime config and data live under a workspace-local `.ib-suite/` directory that
is gitignored. Never commit a real `config.yaml` or a live snapshot.

## Workflow

1. Read only the files relevant to your change; search rather than guess.
2. Follow TDD: write a failing test -> run it red -> implement -> run it green.
3. Make the smallest change that works; reuse existing schema, the `Finding`
   vocabulary, `grade()`, `render()`, and storage helpers. No unrelated
   refactors or reformatting.
4. Keep `SKILL.md`, scripts, `ib_common` schema/thresholds, and tests consistent.

## Testing

```bash
# Full test run
skills/ib-suite/.venv/bin/python -m pytest skills -q

# A single skill, e.g. dividend income
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-dividend-income -q
```

All tests must pass before you open a PR.

## Commit messages

Use `type(scope): summary`, e.g. `fix(ib-dividend-income): reconcile gross with Flex data`.
Explain the *why*, not just the *what*. Prefer new commits over amending.

## Pull requests

- Confirm the read-only boundary is respected and no secrets/runtime data are
  included (`.ib-suite/`, real `config.yaml`, live snapshots, `.venv/`).
- Fill in the PR template checklist.
- See [SECURITY.md](SECURITY.md) for reporting vulnerabilities and
  [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations.

For the full architecture and conventions, read [CLAUDE.md](CLAUDE.md).
