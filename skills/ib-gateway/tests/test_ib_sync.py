# skills/ib-gateway/tests/test_ib_sync.py
from pathlib import Path
from datetime import datetime, timezone
import json, importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "ib_sync.py"
spec = importlib.util.spec_from_file_location("ib_sync", SPEC)
ib_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ib_sync)

FIX = Path(__file__).parent / "fixtures"


def test_build_snapshot_from_raw():
    raw = json.loads((FIX / "ib_raw_account_sample.json").read_text())
    snap = ib_sync.build_snapshot(raw, datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert snap.account.base_currency == "USD"
    assert snap.account.account_id == "U0000000"
    assert len(snap.positions) == 2


def test_sync_writes_snapshot_and_timeseries(tmp_path):
    raw = json.loads((FIX / "ib_raw_account_sample.json").read_text())

    # config pointing storage at tmp
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"storage:\n  root: {tmp_path}\ndata:\n  base_currency: USD\n")

    class FakeClient:
        """Stand-in for a read-only IB Gateway session."""
        def fetch_raw(self): return raw
        def disconnect(self): pass

    out = ib_sync.sync(str(cfg_path),
                       client_factory=lambda cfg: FakeClient(),
                       now=lambda: datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert Path(out["snapshot"]).exists()
    assert Path(out["timeseries"]).exists()
