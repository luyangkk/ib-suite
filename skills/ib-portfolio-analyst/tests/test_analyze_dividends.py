import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "analyze.py"
spec = importlib.util.spec_from_file_location("analyze", SPEC)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)

FIX = Path(__file__).parent / "fixtures"


def test_dividends_appear_in_report(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "data:\n  base_currency: USD\n"
        "thresholds:\n"
        "  cash_ratio_warn: 0.10\n  cash_ratio_crit: 0.05\n"
        "  leverage_warn: 1.5\n  leverage_crit: 2.0\n"
        "  single_position_weight_warn: 0.20\n  single_position_weight_crit: 0.35\n"
        "  hhi_concentration_warn: 0.18\n  hhi_concentration_crit: 0.30\n"
        "  pnl_contrib_warn: 0.50\n"
        "  commission_bps_warn: 5.0\n  commission_bps_crit: 15.0\n"
        "  var95_warn: 0.02\n  var95_crit: 0.05\n"
        "  max_drawdown_warn: 0.15\n  max_drawdown_crit: 0.30\n"
        "  yield_on_cost_warn: 0.02\n  yield_on_cost_crit: 0.01\n"
        "  withholding_drag_warn: 0.10\n  withholding_drag_crit: 0.20\n"
    )
    out = analyze.run(
        str(cfg),
        snapshot_path=str(FIX / "snapshot_diag.json"),
        dividends=json.loads((FIX / "dividends_sample.json").read_text()),
        out_dir=str(tmp_path / "run"),
    )
    report_text = Path(out["report"]).read_text()
    assert "dividends" in report_text
    # dividend FINDINGS text must render, not just the chart reference:
    # these would fail if dividend findings were dropped from the report,
    # whereas the "dividends" chart image link alone would still satisfy the
    # assertion above.
    assert "yield on cost" in report_text.lower()  # Yield-on-Cost finding
    assert "Withholding tax is" in report_text     # withholding-drag finding
    # dividend chart rendered
    assert "dividends" in out["charts"]
    assert Path(out["charts"]["dividends"]["png"]).exists()
