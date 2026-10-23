"""Cố Vấn AI Kéo Ngược (Pullback / Retest Advisor).

Chiến lược vào lệnh khi giá kiểm định lại hỗ trợ động (SMA10/SMA20) sau bứt phá:
- Khắc phục nhược điểm "đu trần/đu đỉnh" của mô hình Breakout thuần túy trên thị trường HOSE.
- Điều kiện xu hướng: Nằm trong uptrend trung hạn (Close > SMA50).
- Điều kiện kiểm định (Retest): Giá kéo ngược về vùng sát SMA20 (khoảng cách -1% đến +3.5%).
- Khối lượng cạn kiệt (Volume Dry-up): Khối lượng phiên kéo ngược thấp hơn mức trung bình 20 phiên (Vol < 0.85x SMA20 Vol), báo hiệu không có áp lực bán tháo tổ chức.
- Tín hiệu nến: Nến rút chân hoặc thu hẹp biên độ biến động (Volatility Contraction).
- Mục tiêu: Nâng tỷ lệ thắng (Win Rate) từ ~30% lên 45-55% và giảm thiểu tối đa trượt giá ATO.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd

from .base import BaseAdvisor, AllocationMethod


def detect_pullback_setup(
    df: pd.DataFrame,
    as_of_date: Optional[pd.Timestamp] = None,
) -> Dict[str, Any]:
    """Phát hiện và đánh giá tín hiệu Kéo ngược (Pullback/Retest) trên chuỗi dữ liệu giá.
    
    Returns:
        Dict chứa trạng thái is_pullback, điểm số chất lượng (0-100), và lý do chi tiết.
    """
    if df is None or len(df) < 30:
        return {"is_pullback": False, "score": 0.0, "reason": "Dữ liệu không đủ (dưới 30 phiên)"}

    if as_of_date is not None:
        times = pd.to_datetime(df["time"]).values
        target = np.datetime64(pd.to_datetime(as_of_date))
        idx = int(np.searchsorted(times, target))
        if idx < 30:
            return {"is_pullback": False, "score": 0.0, "reason": "Dữ liệu trước ngày chỉ định không đủ"}
        hist = df.iloc[:idx]
    else:
        hist = df

    close_series = hist["close"]
    vol_series = hist["volume"]
    high_series = hist["high"] if "high" in hist else close_series
    low_series = hist["low"] if "low" in hist else close_series

    c = float(close_series.iloc[-1])
    h = float(high_series.iloc[-1])
    l = float(low_series.iloc[-1])
    v = float(vol_series.iloc[-1])

    # 1. Đường trung bình động
    sma20 = float(close_series.tail(20).mean())
    sma50 = float(close_series.tail(50).mean()) if len(close_series) >= 50 else sma20
    sma20_vol = float(vol_series.tail(20).mean()) if len(vol_series) >= 20 else (v or 1.0)

    # 2. Kiểm tra Uptrend trung hạn
    if c < sma50 * 0.98:
        return {
            "is_pullback": False,
            "score": 0.0,
            "dist_sma20_pct": round((c / sma20 - 1.0) * 100, 2),
            "reason": f"Giá ({c:,.0f}) nằm dưới SMA50 ({sma50:,.0f}), xu hướng trung hạn không đạt.",
        }

    # 3. Khoảng cách tới SMA20
    dist_sma20_pct = (c / sma20 - 1.0) * 100.0

    # Retest hợp lệ: giá nằm trong vùng [-1.5%, +3.5%] so với SMA20, hoặc bóng nến Low chạm SMA20
    retested_sma20 = (-1.5 <= dist_sma20_pct <= 3.5) or (l <= sma20 <= c)

    if not retested_sma20:
        if dist_sma20_pct > 3.5:
            reason = f"Giá cách quá xa SMA20 (+{dist_sma20_pct:.1f}%), chưa có nhịp điều chỉnh lành mạnh."
        else:
            reason = f"Giá thủng sâu dưới SMA20 ({dist_sma20_pct:.1f}%), rủi ro gãy hỗ trợ."
        return {
            "is_pullback": False,
            "score": 0.0,
            "dist_sma20_pct": round(dist_sma20_pct, 2),
            "reason": reason,
        }

    # 4. Kiểm tra Khối lượng Cạn kiệt (Volume Contraction / Dry-up)
    vol_ratio = (v / sma20_vol) if sma20_vol > 0 else 1.0
    vol_cạn_kiệt = vol_ratio < 0.90

    # 5. Kiểm tra Nến rút chân hoặc co hẹp biên độ
    candle_spread = (h - l) / c if c > 0 else 0.0
    lower_shadow = (min(c, float(hist["open"].iloc[-1])) - l) / c if c > 0 else 0.0
    has_support_bounce = (l <= sma20) and (c >= sma20) and (lower_shadow >= 0.005)

    # 6. Tính điểm chất lượng nhịp Pullback (Thang điểm 0 - 100)
    score = 50.0  # Điểm cơ bản khi đã thỏa mãn hỗ trợ SMA20

    # Điểm cộng khối lượng cạn kiệt
    if vol_ratio <= 0.65:
        score += 25.0  # Khối lượng cực cạn, áp lực bán biến mất
    elif vol_ratio <= 0.85:
        score += 15.0  # Khối lượng thấp hơn trung bình
    elif vol_ratio > 1.20:
        score -= 20.0  # Khối lượng bán lớn tại vùng hỗ trợ -> Rủi ro thủng

    # Điểm cộng nến phản ứng tại hỗ trợ
    if has_support_bounce:
        score += 15.0
    elif c >= float(hist["open"].iloc[-1]):
        score += 10.0  # Nến đóng cửa xanh nhẹ

    # Điểm xu hướng SMA20 > SMA50
    if sma20 >= sma50:
        score += 10.0

    score = float(np.clip(score, 0.0, 100.0))
    is_valid = (score >= 60.0) and (vol_ratio <= 1.05)

    return {
        "is_pullback": is_valid,
        "score": round(score, 2),
        "dist_sma20_pct": round(dist_sma20_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "has_bounce": has_support_bounce,
        "reason": (
            f"Retest SMA20 thành công ({dist_sma20_pct:+.1f}%), "
            f"Khối lượng cạn {vol_ratio:.2f}x SMA20_Vol. Điểm chất lượng: {score:.1f}/100"
        ),
    }


class PullbackAdvisor(BaseAdvisor):
    """Cố vấn Chiến lược Kéo ngược & Tái kiểm định Hỗ trợ (Pullback/Retest)."""

    def __init__(self):
        super().__init__(
            name="Pullback_Retest",
            description="Kéo Ngược Hỗ Trợ SMA20 - Khối Lượng Cạn Kiệt (Low-Risk Entry)",
            rebalance_days=10,  # Chu kỳ rà soát 2 tuần ngắn gọn
            portfolio_size=5,
            allocation_method=AllocationMethod.RANK_LADDER,
            genome={
                "w_momentum_20d": 0.15,
                "w_momentum_60d": 0.10,
                "w_trend_alignment": 0.30,  # Ưu tiên xu hướng vững chắc
                "w_vol_breakout": -0.15,   # Trừ điểm khi volume quá lớn (ưu tiên volume cạn kiệt)
                "w_relative_strength": 0.20,
                "w_low_volatility": 0.15,  # Ưu tiên biên độ nến hẹp
                "w_mean_reversion": 0.05,
                "w_drawdown_recovery": 0.05,
            },
        )

    def score_symbol(
        self,
        symbol: str,
        df: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp] = None,
        benchmark_df: Optional[pd.DataFrame] = None,
    ) -> float:
        """Chấm điểm định lượng kết hợp bộ lọc mẫu hình Kéo ngược."""
        base_score = super().score_symbol(symbol, df, as_of_date=as_of_date, benchmark_df=benchmark_df)
        if base_score <= -900.0:
            return base_score

        # Áp dụng thuật toán kiểm định Pullback
        setup = detect_pullback_setup(df, as_of_date=as_of_date)
        if not setup["is_pullback"]:
            # Nếu không ở trạng thái pullback hợp lệ, lọc bỏ để tập trung vào mã đang pullback
            return -999.0

        # Cộng thưởng điểm chất lượng pullback (thang 0-100 chuyển thành 0-0.5)
        pullback_bonus = (setup["score"] / 100.0) * 0.5
        return float(base_score + pullback_bonus)
