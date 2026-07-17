# skills/ib-portfolio-analyst/tests/test_dividend_store.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ib_common.schema import Dividend
from ib_analyst import dividend_store

FIX = Path(__file__).parent / "fixtures"


def _divs():
    return [Dividend(**r) for r in json.loads((FIX / "dividends_sample.json").read_text())]


def test_store_then_load_roundtrip(tmp_path):
    dividend_store.store_dividends(_divs(), tmp_path)
    loaded = dividend_store.load_dividends(tmp_path)
    assert len(loaded) == 3
    assert {d.symbol for d in loaded} == {"AAPL", "MSFT", "TSM"}


def test_store_is_idempotent(tmp_path):
    dividend_store.store_dividends(_divs(), tmp_path)
    dividend_store.store_dividends(_divs(), tmp_path)   # dup append
    assert len(dividend_store.load_dividends(tmp_path)) == 3


def test_load_missing_returns_empty(tmp_path):
    assert dividend_store.load_dividends(tmp_path) == []
