## Summary

<!-- What does this change and why? -->

## Checklist

- [ ] `skills/ib-suite/.venv/bin/python -m pytest skills -q` passes locally
- [ ] Change stays within the read-only boundary (no order placement/modification/cancellation, no write path to IB)
- [ ] No secrets or runtime data included (`.ib-suite/`, real `config.yaml`, live snapshots, `.venv/`)
- [ ] `SKILL.md`, scripts, `ib_common` schema/thresholds, and tests are consistent
- [ ] Commit messages follow `type(scope): summary`

## Notes

<!-- Anything reviewers should know: residual risk, follow-ups, screenshots. -->
