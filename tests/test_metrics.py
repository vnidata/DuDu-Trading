"""Kiểm thử các chỉ số đo lường hiệu quả và rủi ro."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bubu.metrics import (
    drawdown_series,
    equity_metrics,
    max_drawdown,
    max_drawdown_duration,
    monthly_returns_table,
    summarize,
    trade_metrics,
)


def test_max_drawdown_known_series():
    equity = np.array([100.0, 120.0, 90.0, 130.0, 65.0, 100.0])
    dd, peak, trough = max_drawdown(equity)
    assert dd == pytest.approx(65.0 / 130.0 - 1.0)
    assert peak == 3
    assert trough == 4


def test_max_drawdown_duration_counts_sessions_under_peak():
    equity = np.array([100.0, 110.0, 105.0, 104.0, 115.0, 100.0, 99.0])
    assert max_drawdown_duration(equity) == 2


def test_equity_metrics_cagr_and_calmar():
    n = 252 * 3
    equity = 1e9 * (1.10 ** (np.arange(n) / 252.0))
    m = equity_metrics(equity, trading_days=252)
    assert m["cagr"] == pytest.approx(0.10, rel=0.02)
    assert m["max_dd"] == pytest.approx(0.0, abs=1e-9)
    assert m["calmar"] == 0.0  # không có drawdown -> Calmar quy ước bằng 0
    assert m["total_return"] == pytest.approx(1.10 ** ((n - 1) / 252.0) - 1, rel=0.02)


def test_equity_metrics_sharpe_sign():
    up = 1e9 * (1.001 ** np.arange(500))
    down = 1e9 * (0.999 ** np.arange(500))
    assert equity_metrics(up)["sharpe"] > 0
    assert equity_metrics(down)["sharpe"] < 0
    assert equity_metrics(down)["sortino"] < 0


def test_drawdown_series_bounds():
    equity = np.array([100.0, 80.0, 120.0])
    dd = drawdown_series(equity)
    assert dd[0] == 0
    assert dd[1] == pytest.approx(-0.2)
    assert dd[2] == pytest.approx(0.0)


def test_equity_metrics_handles_empty_and_flat():
    assert equity_metrics(np.array([]))["sessions"] == 0
    flat = equity_metrics(np.full(100, 1e9))
    assert flat["total_return"] == 0.0
    assert flat["max_dd"] == 0.0


def test_trade_metrics_basic():
    trades = [
        {"pnl": 100.0, "r_multiple": 3.0, "holding_days": 10, "fees": 1.0},
        {"pnl": -50.0, "r_multiple": -1.0, "holding_days": 5, "fees": 1.0},
        {"pnl": -50.0, "r_multiple": -1.0, "holding_days": 4, "fees": 1.0},
        {"pnl": 200.0, "r_multiple": 4.0, "holding_days": 20, "fees": 2.0},
    ]
    t = trade_metrics(trades, sessions=252)
    assert t["trades"] == 4
    assert t["hit_rate"] == pytest.approx(0.5)
    assert t["profit_factor"] == pytest.approx(300.0 / 100.0)
    assert t["avg_r"] == pytest.approx((3.0 - 1.0 - 1.0 + 4.0) / 4)
    assert t["max_consecutive_losses"] == 2
    assert t["total_fees"] == pytest.approx(5.0)


def test_trade_metrics_empty():
    t = trade_metrics([], sessions=252)
    assert t["trades"] == 0
    assert t["hit_rate"] == 0.0


def test_monthly_returns_table_groups_by_month():
    dates = pd.date_range("2020-01-01", periods=400, freq="B")
    equity = 1e9 * (1.0005 ** np.arange(len(dates)))
    rows = monthly_returns_table(equity, dates)
    assert len(rows) >= 18
    assert all({"year", "month", "return"} <= set(r) for r in rows)


def test_summarize_distribution():
    results = {
        "A": {"cagr": 0.1, "sharpe": 1.0, "calmar": 0.5, "max_dd": -0.2},
        "B": {"cagr": -0.05, "sharpe": -0.5, "calmar": -0.1, "max_dd": -0.4},
        "C": {"cagr": 0.2, "sharpe": 2.0, "calmar": 1.0, "max_dd": -0.2},
    }
    s = summarize(results)
    assert s["n_symbols"] == 3
    assert s["sharpe"]["median"] == pytest.approx(1.0)
    assert s["cagr"]["positive_share"] == pytest.approx(2 / 3)
