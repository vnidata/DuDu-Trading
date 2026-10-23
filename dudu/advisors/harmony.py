"""Chuyên gia Chiến Lược Nhịp Nhàng (Harmony Advisor).

Khẩu vị: Nhà đầu tư Cân bằng, tìm kiếm lợi nhuận ổn định đi kèm kiểm soát rủi ro.
Chu kỳ tái cấu trúc: 1 tháng / lần (21 ngày giao dịch).
Phương pháp phân bổ: Equal Weight (20% mỗi mã).
Bộ gene: Cân bằng giữa Xu hướng trung hạn, Động lượng và Sức mạnh giá tương đối.
"""

from __future__ import annotations

from typing import Optional, Dict
from .base import BaseAdvisor, AllocationMethod


class HarmonyAdvisor(BaseAdvisor):
    def __init__(self, genome: Optional[Dict[str, float]] = None):
        default_genome = {
            "w_momentum_20d": 0.15,
            "w_momentum_60d": 0.20,
            "w_trend_alignment": 0.25,
            "w_vol_breakout": 0.15,
            "w_relative_strength": 0.15,
            "w_low_volatility": 0.05,
            "w_mean_reversion": 0.00,
            "w_drawdown_recovery": 0.05,
        }
        super().__init__(
            name="AI_Advisor_NhipNhang_1M",
            description="Chiến lược Nhịp Nhàng (1 tháng, Equal Weight, Xu Hướng Bền Vững)",
            rebalance_days=21,
            portfolio_size=5,
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
            genome=genome or default_genome,
        )
