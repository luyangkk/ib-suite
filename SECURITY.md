# Security Policy

## Read-only by design

ib-suite connects to Interactive Brokers with `readonly=True` and never places,
modifies, or cancels orders. It never writes to your IB account. If you find any
code path that could violate this boundary, treat it as a security issue and
report it privately.

## Credentials

- Flex tokens, Query IDs, account numbers, and user paths must never appear in
  stdout, logs, or committed files.
- Real config and runtime data live only under the gitignored `.ib-suite/`
  directory. Committed fixtures are desensitized.

## Supported versions

The project is pre-1.0; only the latest `main` receives security fixes.

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| older commits | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead, use
GitHub's private vulnerability reporting: open a
[private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
via the repository's **Security** tab. We aim to acknowledge reports within a
few days.
