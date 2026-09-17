
# ib-gateway

Read-only data ingestion for the IB analyst toolchain. This skill never
places or modifies orders; it connects with `readonly=True` and only reads.

## Prerequisites

Config and the shared venv are owned by the `ib-suite` index skill (see its
first-run setup). Start IB Gateway (paper on 4002 / live on 4001) with API
access, and tick **Read-Only API** in Gateway settings as an extra guard.

## Commands

### /ib-sync — snapshot current account + positions

```bash
$WORKSPACE_ROOT/.ib-suite/venv/bin/python $SKILL_ROOT/ib-gateway/scripts/ib_sync.py --config $WORKSPACE_ROOT/.ib-suite/config.yaml
```

Writes `data/snapshots/<account>/<ts>.json` (instantaneous state) and appends
`data/timeseries/positions_history.parquet` (history).

### Flex history (dividends, trades > 7 days old)

```bash
$WORKSPACE_ROOT/.ib-suite/venv/bin/python -c "import sys; sys.path.insert(0,'$SKILL_ROOT/ib-gateway/scripts'); \
import flex_fetch; print(flex_fetch.fetch_flex_report('$FLEX_TOKEN','$FLEX_QUERY_ID'))"
```

## Notes

- Same `clientId` allows only one active Gateway connection — pick a unique id in `config.yaml`.
- Base currency follows the account's BASE; override only via `config.yaml`.
- All committed fixtures are desensitized. Never commit real `config.yaml` or live snapshots.
