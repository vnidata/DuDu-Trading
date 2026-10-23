"""Chuyên gia Chiến Lược Bền Bỉ (Persistent Advisor).

Khẩu vị: Nhà đầu tư Thận trọng / Tổ chức / NAV lớn, ưu tiên bảo toàn vốn và kiểm soát drawdown.
Chu kỳ tái cấu trúc: 3 tháng / lần (63 ngày giao dịch).
Phương pháp phân bổ: Risk Parity (tỷ trọng nghịch đảo mức biến động ATR).
Bộ gene: Đề cao Biến động thấp (Low Volatility), Xu hướng dài hạn vững chắc và Phục hồi sau sụt giảm.
"""

from __future__ import annotations

from typing import Optional, Dict
from .base import BaseAdvisor, AllocationMethod


class PersistentAdvisor(BaseAdvisor):
    def __init__(self, genome: Optional[Dict[str, float]] = None):
        default_genome = {
            "w_momentum_20d": 0.05,
            "w_momentum_60d": 0.15,
            "w_trend_alignment": 0.30,
            "w_vol_breakout": 0.05,
            "w_relative_strength": 0.15,
            "w_low_volatility": 0.25,
            "w_mean_reversion": 0.00,
            "w_drawdown_recovery": 0.05,
        }
        super().__init__(
            name="AI_Advisor_BenBi_3M",
            description="Chiến lược Bền Bỉ (3 tháng, Risk Parity, Phòng Thủ Biến Động Thấp)",
            rebalance_days=63,
            portfolio_size=5,
            allocation_method=AllocationMethod.RISK_PARITY,
            genome=genome or default_genome,
        )
