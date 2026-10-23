"""Chuyên gia Bùng Nổ Dòng Tiền CANSLIM / VSA (Canslim Advisor).

Khẩu vị: Nhà đầu tư tăng trưởng, săn tìm siêu cổ phiếu vượt đỉnh có khối lượng đột biến.
Chu kỳ tái cấu trúc: 2 tuần / lần (10 ngày giao dịch).
Phương pháp phân bổ: Rank Ladder (30-25-20-15-10%).
Bộ gene: Tối đa hóa Bùng nổ khối lượng (Volume Surge >= 1.5x SMA20 Vol), RS Rating > 80, và Động lượng bứt phá.
"""

from __future__ import annotations

from typing import Optional, Dict
from .base import BaseAdvisor, AllocationMethod


class CanslimAdvisor(BaseAdvisor):
    def __init__(self, genome: Optional[Dict[str, float]] = None):
        default_genome = {
            "w_momentum_20d": 0.20,
            "w_momentum_60d": 0.15,
            "w_trend_alignment": 0.15,
            "w_vol_breakout": 0.30,
            "w_relative_strength": 0.20,
            "w_low_volatility": 0.00,
            "w_mean_reversion": 0.00,
            "w_drawdown_recovery": 0.00,
        }
        super().__init__(
            name="AI_Advisor_CANSLIM_Breakout",
            description="Chiến lược CANSLIM VSA (Vượt đỉnh khối lượng lớn, RS dẫn dắt)",
            rebalance_days=10,
            portfolio_size=5,
            allocation_method=AllocationMethod.RANK_LADDER,
            genome=genome or default_genome,
        )
