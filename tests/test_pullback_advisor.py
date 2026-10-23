"""Kiểm định Cố vấn AI Kéo Ngược (Pullback / Retest Advisor) & Mẫu hình Hỗ trợ SMA20."""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from dudu.advisors.pullback import PullbackAdvisor, detect_pullback_setup


def _generate_pullback_data(n_bars=60, scenario="ideal"):
    """Tạo dữ liệu giả lập mẫu hình kéo ngược."""
    dates = pd.date_range("2024-01-01", periods=n_bars)
    # Giai đoạn tăng từ 100 lên 120 trong 45 phiên đầu
    prices = [100.0 + 0.44 * i for i in range(45)]
    volumes = [1_000_000] * 45

    if scenario == "ideal":
        # 14 phiên tiếp theo điều chỉnh thoái lui nhẹ về SMA20
        # SMA20 khoảng 115-116
        for i in range(14):
            prices.append(120.0 - 0.25 * i)
            volumes.append(600_000)  # Volume cạn kiệt (0.6x bình thường)
        # Phiên cuối cùng nến rút chân test sát SMA20
        last_price = prices[-1]
        prices.append(last_price)
        volumes.append(500_000)
    elif scenario == "break_down":
        # Giá gãy thủng sâu dưới SMA20
        for i in range(15):
            prices.append(120.0 - 1.2 * i)
            volumes.append(1_800_000)  # Volume bán tháo cực lớn
    elif scenario == "heavy_volume":
        # Giá ở SMA20 nhưng volume bán xả lớn
        for i in range(15):
            prices.append(120.0 - 0.25 * i)
            volumes.append(2_500_000)
    elif scenario == "overextended":
        # Giá tiếp tục tăng vọt không có nhịp retest
        for i in range(15):
            prices.append(120.0 + 1.0 * i)
            volumes.append(1_500_000)

    df = pd.DataFrame({
        "time": dates[:len(prices)],
        "open": [p * 0.995 for p in prices],
        "high": [p * 1.015 for p in prices],
        "low": [p * 0.985 for p in prices],
        "close": prices,
        "volume": volumes,
        "rs_rating": [80.0] * len(prices),
        "rsi": [52.0] * len(prices),
    })
    return df


def test_pullback_advisor_genome_normalized():
    """Bộ gene PullbackAdvisor phải có tổng bằng 1.0."""
    adv = PullbackAdvisor()
    assert abs(sum(adv.genome.values()) - 1.0) < 1e-5


def test_detect_pullback_setup_ideal():
    """Phát hiện chính xác mẫu hình kéo ngược lành mạnh với volume cạn kiệt."""
    df = _generate_pullback_data(scenario="ideal")
    setup = detect_pullback_setup(df)
    assert setup["is_pullback"] is True
    assert setup["score"] >= 60.0
    assert setup["vol_ratio"] < 1.0


def test_detect_pullback_setup_break_down():
    """Từ chối tín hiệu khi giá gãy thủng hỗ trợ với volume lớn."""
    df = _generate_pullback_data(scenario="break_down")
    setup = detect_pullback_setup(df)
    assert setup["is_pullback"] is False


def test_detect_pullback_setup_heavy_volume():
    """Từ chối tín hiệu khi nhịp kéo ngược kèm khối lượng xả hàng lớn."""
    df = _generate_pullback_data(scenario="heavy_volume")
    setup = detect_pullback_setup(df)
    assert setup["is_pullback"] is False


def test_pullback_advisor_scoring():
    """PullbackAdvisor chấm điểm cao cho mã ideal và loại bỏ mã break_down."""
    adv = PullbackAdvisor()
    df_ideal = _generate_pullback_data(scenario="ideal")
    df_down = _generate_pullback_data(scenario="break_down")

    score_ideal = adv.score_symbol("IDEAL", df_ideal)
    score_down = adv.score_symbol("DOWN", df_down)

    assert score_ideal > 0.0
    assert score_down <= -500.0
