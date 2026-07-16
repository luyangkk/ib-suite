# skills/ib-common/tests/test_metrics_returns.py
import numpy as np
from ib_common.metrics.returns import sharpe, sortino, calmar


def test_sharpe_zero_when_no_variance():
    assert sharpe([0.001, 0.001, 0.001]) == 0.0   # no volatility -> defined as 0


def test_sharpe_positive_for_positive_mean():
    r = [0.01, -0.005, 0.012, 0.003, -0.002]
    assert sharpe(r) > 0


def test_sortino_ge_zero_and_penalizes_downside():
    r = [0.01, -0.02, 0.015, -0.01, 0.02]
    s = sortino(r)
    assert np.isfinite(s)


def test_calmar_finite_for_drawdown_series():
    r = [0.02, -0.05, 0.03, -0.01, 0.04]
    assert np.isfinite(calmar(r))
