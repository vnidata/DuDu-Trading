"""Chuyên gia Đảo Chiều Thống Kê (Mean Reversion Advisor).

Khẩu vị: Nhà đầu tư bắt đáy định lượng, tìm kiếm cổ phiếu quá bán (RSI < 35) có dấu hiệu phục hồi.
Chu kỳ tái cấu trúc: 20 ngày giao dịch.
Phương pháp phân bổ: Equal Weight (20% mỗi mã).
Bộ gene: Tối đa hóa Đảo chiều vùng quá bán (Mean Reversion), Khả năng phục hồi sau sụt giảm và RSI.
"""

from __future__ import annotations

from typing import Optional, Dict
from .base import BaseAdvisor, AllocationMethod


class MeanReversionAdvisor(BaseAdvisor):
    def __init__(self, genome: Optional[Dict[str, float]] = None):
        default_genome = {
            "w_momentum_20d": 0.05,
            "w_momentum_60d": 0.05,
            "w_trend_alignment": 0.10,
            "w_vol_breakout": 0.10,
            "w_relative_strength": 0.10,
            "w_low_volatility": 0.10,
            "w_mean_reversion": 0.35,
            "w_drawdown_recovery": 0.15,
        }
        super().__init__(
            name="AI_Advisor_Mean_Reversion",
            description="Chiến lược Đảo Chiều Thống Kê (Bắt đáy RSI quá bán, Phục hồi kỹ thuật)",
            rebalance_days=20,
            portfolio_size=5,
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
            genome=genome or default_genome,
        )
