"""Module quản trị thực thi định chế & kiểm soát rủi ro thị trường HOSE.

Kế thừa từ dự án VN-SWING:
- Quy tắc khớp lệnh vi cấu trúc HOSE (T+2.5, biên độ ±7%, trượt giá ADTV)
- Cơ chế khóa vùng Holdout (2025-nay) chống p-hacking
- Quản lý sổ lệnh thực tế (Human-in-the-loop)
"""

from .rules import ExecutionSimulator, HoseMarketRules, simulate_order_fill
from .holdout import HoldoutLock, check_holdout_boundary
from .ledger import LedgerManager, TradeRecord
from .trailing_stop import DynamicChandelierExit, PositionExitState
from .allocator import DynamicCapitalAllocator, AllocationTarget, PortfolioAllocationResult

__all__ = [
    "ExecutionSimulator",
    "HoseMarketRules",
    "simulate_order_fill",
    "HoldoutLock",
    "check_holdout_boundary",
    "LedgerManager",
    "TradeRecord",
    "DynamicChandelierExit",
    "PositionExitState",
    "DynamicCapitalAllocator",
    "AllocationTarget",
    "PortfolioAllocationResult",
]
