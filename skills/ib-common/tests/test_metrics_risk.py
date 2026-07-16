# skills/ib-common/tests/test_metrics_risk.py
import numpy as np
from ib_common.metrics.risk import max_drawdown, hist_var, hist_cvar, hhi


def test_max_drawdown_simple():
    equity = [100, 120, 90, 110]      # peak 120 -> trough 90 => -0.25
    assert abs(max_drawdown(equity) - (-0.25)) < 1e-9


def test_hist_var_positive_loss():
    returns = [-0.05, -0.02, 0.01, 0.03, -0.10, 0.02, 0.00]
    v = hist_var(returns, level=0.95)
    assert v > 0                       # reported as a positive loss magnitude


def test_cvar_ge_var():
    returns = [-0.05, -0.02, 0.01, 0.03, -0.10, 0.02, 0.00]
    assert hist_cvar(returns, 0.95) >= hist_var(returns, 0.95)


def test_hhi_concentrated_vs_diversified():
    assert hhi([1.0]) == 1.0                       # fully concentrated
    assert abs(hhi([0.25, 0.25, 0.25, 0.25]) - 0.25) < 1e-9
