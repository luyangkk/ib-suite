# Flex Config Onboarding Design

## Goal

Allow `ib-trade-history` to initialize and persist IBKR Flex credentials in the
workspace-local `.ib-suite/config.yaml` through its SKILL.md conversation flow.
The feature validates local configuration only; it does not contact Flex during
setup.

## Scope

Add a `flex` section to the shared config model and template:

```yaml
flex:
  token: null
  query_id: null
```

The distributed template retains null values. Real credentials are written only
to `.ib-suite/config.yaml`, which is workspace-local and ignored by Git.

## Runtime Credential Resolution

`ib-trade-history` resolves credentials atomically:

1. Use `config.flex.token` and `config.flex.query_id` when both are configured.
2. Otherwise, when neither config value is configured, use both
   `FLEX_TOKEN` and `FLEX_QUERY_ID` environment variables as a compatibility
   fallback.
3. Reject a partial config or partial environment configuration. Credentials
   from config and environment are never mixed.

Credentials never appear in stdout, JSON results, exceptions, or structured
logs.

## Configuration Script

Create `ib-trade-history/scripts/configure_flex.py` with:

```text
--config PATH
--token TOKEN
--query-id QUERY_ID
--force
```

It uses `ruamel.yaml` round-trip parsing to preserve existing comments. It
requires non-empty token and query ID values and verifies that the persisted
config reloads with both fields present. When either credential already exists,
it refuses to update without `--force`; forced updates write both values
together.

Its success result contains the config path and a boolean readiness status, but
never the token or query ID.

## Skill Workflow

Before a trade-history query, `SKILL.md` checks whether the config has both
Flex values. If it does not, it asks for token and Query ID one at a time, then
runs `configure_flex.py` to persist them and reports local configuration
readiness. The skill then runs the standard trade-history command.

No setup path contacts IBKR Flex automatically.

## Error Handling

- Missing config file: direct the user to `ib-suite` first-run setup.
- Empty token or Query ID: do not write the file.
- Existing partial or complete Flex config: refuse without `--force`.
- Partial config or environment credentials: fail with a remediation message;
  do not merge sources.

## Tests

Offline tests cover template defaults, first write, reload validation, comment
preservation, empty input, overwrite protection, forced paired updates,
credential-source precedence, complete environment fallback, partial-source
rejection, and secret-free stdout/JSON.

No live Flex request or secret fixture is used.
