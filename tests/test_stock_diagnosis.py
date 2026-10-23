"""Kiểm thử Bộ Máy Chẩn Đoán Sức Khỏe Cổ Phiếu (Stock Doctor).

Kế thừa từ vn-stock-ai-advisors:
- Khám sức khỏe 360 độ: Xu hướng MA, Động lượng RSI, Dòng tiền Volume, Kênh Donchian, RS Rating
- Đánh giá từ 6 Chuyên gia AI
- Kết luận chẩn đoán (Health Verdict: Xuất sắc, Tích cực, Trung lập, Tiêu cực)
"""

from __future__ import annotations

import pandas as pd
import pytest

from dudu.diagnosis import StockDoctor


def _make_stock_history(trend="up"):
    dates = pd.date_range("2024-01-01", periods=60)
    if trend == "up":
        prices = [100.0 * (1.0 + 0.005 * i) for i in range(60)]
        vol = [1_000_000] * 59 + [2_500_000] # Bùng nổ volume phiên cuối
        rs = 88.0
    else:
        prices = [100.0 * (1.0 - 0.005 * i) for i in range(60)]
        vol = [500_000] * 60
        rs = 25.0

    return pd.DataFrame({
        "time": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": vol,
        "rs_rating": [rs] * 60,
    })


def test_stock_doctor_bullish():
    """Cổ phiếu bùng nổ khối lượng và uptrend phải được chẩn đoán Tích cực hoặc Xuất sắc."""
    doc = StockDoctor()
    df = _make_stock_history(trend="up")

    report = doc.diagnose("FPT", df)

    assert report.symbol == "FPT"
    assert report.rs_rating == 88.0
    assert report.volume_surge_ratio > 2.0
    assert report.health_verdict in ["XUẤT SẮC", "TÍCH CỰC"]
    assert len(report.strengths) >= 2
    assert len(report.advisor_opinions) >= 6


def test_stock_doctor_bearish():
    """Cổ phiếu gãy trend, RS kém và nằm dưới SMA50 phải nhận cảnh báo Tiêu cực."""
    doc = StockDoctor()
    df = _make_stock_history(trend="down")

    report = doc.diagnose("SẬP", df)

    assert report.symbol == "SẬP"
    assert report.rs_rating == 25.0
    assert report.health_verdict in ["TIÊU CỰC", "TRUNG LẬP"]
    assert len(report.warnings) >= 1
    assert "SMA50" in " ".join(report.warnings)
