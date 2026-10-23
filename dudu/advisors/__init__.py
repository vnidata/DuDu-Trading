"""Hội đồng Đa Chuyên gia AI Quản lý Danh mục (Multi-Advisor AI Council).

Bao gồm:
- BaseAdvisor: Lớp cơ sở chuẩn hóa Genome và bộ lọc Point-in-Time
- ActiveAdvisor: Chiến lược Chủ Động (2 tuần, Rank Ladder, Động Lượng)
- HarmonyAdvisor: Chiến lược Nhịp Nhàng (1 tháng, Equal Weight, Xu Hướng)
- PersistentAdvisor: Chiến lược Bền Bỉ (3 tháng, Risk Parity, Thấp Biến Động)
- CanslimAdvisor: Chiến lược CANSLIM VSA (Vượt đỉnh khối lượng)
- MeanReversionAdvisor: Chiến lược Đảo Chiều Thống Kê (RSI quá bán)
- TurtleAdvisor: Chiến lược Turtle S2 (Donchian Breakout 55/20)
- PullbackAdvisor: Chiến lược Kéo Ngược & Kiểm Định Hỗ Trợ SMA20 (Tối ưu điểm vào)
- AdvisorCouncil: Hội đồng điều phối và quản trị phòng thủ tiền mặt (Cash Defense)
"""

from .base import BaseAdvisor, AllocationMethod
from .active import ActiveAdvisor
from .harmony import HarmonyAdvisor
from .persistent import PersistentAdvisor
from .canslim import CanslimAdvisor
from .mean_reversion import MeanReversionAdvisor
from .turtle import TurtleAdvisor
from .pullback import PullbackAdvisor, detect_pullback_setup
from .council import AdvisorCouncil

__all__ = [
    "BaseAdvisor",
    "AllocationMethod",
    "ActiveAdvisor",
    "HarmonyAdvisor",
    "PersistentAdvisor",
    "CanslimAdvisor",
    "MeanReversionAdvisor",
    "TurtleAdvisor",
    "PullbackAdvisor",
    "detect_pullback_setup",
    "AdvisorCouncil",
]
