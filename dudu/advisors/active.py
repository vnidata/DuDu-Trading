"""Chuyên gia Chiến Lược Chủ Động (Active Advisor).

Khẩu vị: Nhà đầu tư Táo bạo, chấp nhận biến động để tối đa hóa Alpha ngắn hạn.
Chu kỳ tái cấu trúc: 2 tuần / lần (10 ngày giao dịch).
Phương pháp phân bổ: Rank Ladder (30% - 25% - 20% - 15% - 10%).
Bộ gene: Ưu tiên Động lượng cao (Momentum 20D), Sức mạnh giá (RS Rating), và Bùng nổ khối lượng.
"""

from __future__ import annotations

from typing import Optional, Dict
from .base import BaseAdvisor, AllocationMethod


class ActiveAdvisor(BaseAdvisor):
    def __init__(self, genome: Optional[Dict[str, float]] = None):
        default_genome = {
            "w_momentum_20d": 0.30,
            "w_momentum_60d": 0.15,
            "w_trend_alignment": 0.15,
            "w_vol_breakout": 0.20,
            "w_relative_strength": 0.20,
            "w_low_volatility": 0.00,
            "w_mean_reversion": 0.00,
            "w_drawdown_recovery": 0.00,
        }
        super().__init__(
            name="AI_Advisor_ChuDong_2W",
            description="Chiến lược Chủ Động (2 tuần, Rank Ladder, Động Lượng Cao)",
            rebalance_days=10,
            portfolio_size=5,
            allocation_method=AllocationMethod.RANK_LADDER,
            genome=genome or default_genome,
        )
