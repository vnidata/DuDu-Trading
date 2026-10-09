"""Kiểm thử tầng dữ liệu: chuẩn hoá, cache, điều tiết nhịp API."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from dudu.data import PricePanel, RateLimiter, _normalize, compute_adv


def test_normalize_converts_thousand_vnd_to_vnd():
    df = pd.DataFrame(
        {
            "time": pd.bdate_range("2020-01-01", periods=5),
            "open": [10.0] * 5,
            "high": [11.0] * 5,
            "low": [9.0] * 5,
            "close": [10.5] * 5,
            "volume": [1000] * 5,
        }
    )
    out = _normalize(df, "AAA")
    assert out["close"].iloc[0] == pytest.approx(10_500)


def test_normalize_keeps_vnd_values():
    df = pd.DataFrame(
        {
            "time": pd.bdate_range("2020-01-01", periods=5),
            "open": [20_000.0] * 5,
            "high": [21_000.0] * 5,
            "low": [19_000.0] * 5,
            "close": [20_500.0] * 5,
            "volume": [1_000_000] * 5,
        }
    )
    out = _normalize(df, "AAA")
    assert out["close"].iloc[0] == pytest.approx(20_500.0)


def test_normalize_sorts_and_dedupes():
    df = pd.DataFrame(
        {
            "time": [pd.Timestamp("2020-01-03"), pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")],
            "open": [3.0, 2.0, 3.5],
            "high": [3.0, 2.0, 3.5],
            "low": [3.0, 2.0, 3.5],
            "close": [30_000.0, 20_000.0, 31_000.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    out = _normalize(df, "AAA")
    assert len(out) == 2
    assert out["close"].tolist() == [20_000.0, 31_000.0]


def test_normalize_requires_columns():
    with pytest.raises(ValueError):
        _normalize(pd.DataFrame({"time": [pd.Timestamp("2020-01-01")]}), "AAA")


def test_price_panel_handles_ragged_symbols():
    a = pd.DataFrame(
        {
            "time": pd.bdate_range("2020-01-01", periods=10),
            "open": 1.0, "high": 1.0, "low": 1.0, "close": np.arange(10.0) + 100,
            "volume": 1000.0,
        }
    )
    b = pd.DataFrame(
        {
            "time": pd.bdate_range("2020-01-06", periods=5),
            "open": 2.0, "high": 2.0, "low": 2.0, "close": np.arange(5.0) + 200,
            "volume": 2000.0,
        }
    )
    panel = PricePanel({"AAA": a, "BBB": b})
    assert len(panel.dates) == 10
    assert panel.symbols == ["AAA", "BBB"]
    # BBB chưa niêm yết ở đầu chuỗi -> giữ NaN, không forward-fill ngược
    assert not panel.listed[0, 1]
    assert np.isnan(panel.close[0, 1])
    assert int(panel.listed[:, 1].sum()) == 5
    # Sau ngày niêm yết đầu tiên, cột BBB không còn NaN
    assert not np.isnan(panel.close[panel.listed[:, 1], 1]).any()


def test_compute_adv_is_shifted_to_avoid_lookahead():
    n = 60
    close = np.full((n, 1), 10_000.0)
    volume = np.full((n, 1), 1_000_000.0)
    volume[59, 0] = 1e12   # cú bùng nổ thanh khoản ở phiên cuối
    panel = PricePanel(
        {
            "AAA": pd.DataFrame(
                {
                    "time": pd.bdate_range("2020-01-01", periods=n),
                    "open": close.ravel(), "high": close.ravel(), "low": close.ravel(),
                    "close": close.ravel(), "volume": volume.ravel(),
                }
            )
        }
    )
    adv = compute_adv(panel, 20)
    # Nhờ shift(1), ADV tại phiên cuối không phản ánh chính phiên đó
    assert adv[-1, 0] < 1e11


def test_rate_limiter_enforces_window():
    limiter = RateLimiter(max_per_minute=5, window=0.4)
    t0 = time.monotonic()
    for _ in range(9):
        limiter.acquire()
    elapsed = time.monotonic() - t0
    # 9 request với trần 5/0,4s phải mất ít nhất một chu kỳ chờ
    assert elapsed >= 0.35
    assert limiter.usage() <= 5
