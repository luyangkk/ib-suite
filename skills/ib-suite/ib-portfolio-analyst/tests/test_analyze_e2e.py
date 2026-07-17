import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "analyze.py"
spec = importlib.util.spec_from_file_location("analyze", SPEC)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)

FIX = Path(__file__).parent / "fixtures"


def test_end_to_end_generates_report(tmp_path):
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
    )
    out = analyze.run(
        str(cfg),
        snapshot_path=str(FIX / "snapshot_diag.json"),
        bars=json.loads((FIX / "daily_bars_multi.json").read_text()),
        executions=json.loads((FIX / "executions_sample.json").read_text()),
        out_dir=str(tmp_path / "run"),
    )
    report_text = Path(out["report"]).read_text()
    assert "Portfolio Diagnostic Report" in report_text
    # every dimension should appear
    for dim in ("account_health", "concentration", "pnl_attribution",
                "trade_review", "portfolio_risk"):
        assert dim in report_text
