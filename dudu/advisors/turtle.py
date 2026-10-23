"""Chuyên gia Bứt Phá Kênh Donchian (Turtle S2 Advisor).

Khẩu vị: Bám sát xu hướng dài hạn (Trend Following) theo nguyên lý Turtle Trading System 2.
Chu kỳ: Donchian 55 phiên bứt phá đỉnh (Entry), 20 phiên thoát lệnh (Exit), Trailing Stop ATR.
Phương pháp phân bổ: Equal Weight / Volatility Adjusted.
Tích hợp trực tiếp với bộ máy cốt lõi của DuDu-Trading.
"""

from __future__ import annotations

from typing import Optional, Dict
import pandas as pd
from .base import BaseAdvisor, AllocationMethod


class TurtleAdvisor(BaseAdvisor):
    def __init__(self, genome: Optional[Dict[str, float]] = None):
        default_genome = {
            "w_momentum_20d": 0.15,
            "w_momentum_60d": 0.25,
            "w_trend_alignment": 0.25,
            "w_vol_breakout": 0.15,
            "w_relative_strength": 0.10,
            "w_low_volatility": 0.05,
            "w_mean_reversion": 0.00,
            "w_drawdown_recovery": 0.05,
        }
        super().__init__(
            name="AI_Advisor_Turtle_Donchian",
            description="Chiến lược Turtle S2 (Donchian Breakout 55/20, Bám Xu Hướng Dài Hạn)",
            rebalance_days=20,
            portfolio_size=5,
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
            genome=genome or default_genome,
        )

    def is_donchian_breakout(self, df: pd.DataFrame, window: int = 55) -> bool:
        """Kiểm tra giá hiện tại có vượt đỉnh Donchian 55 phiên hay không."""
        if df is None or len(df) < window + 1:
            return False
        high_prev = df["high"].iloc[-window - 1 : -1].max()
        current_close = df["close"].iloc[-1]
        return bool(current_close > high_prev)
