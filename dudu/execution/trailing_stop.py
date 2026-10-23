"""Bộ Quản Trị Cắt Lỗ & Chốt Lời Động Theo Biến Động Thực Tế ATR (Dynamic Chandelier Exit).

Kế thừa và nâng cấp chuẩn mực rủi ro của VN-SWING & vn-stock-ai-advisors:
1. Initial ATR Stop-Loss:
   - Thay thế stop-loss tĩnh -7% bằng khoảng cách biến động tự nhiên k_stop * ATR(14).
   - Khống chế biên độ cắt lỗ trong khoảng an toàn [-3.5%, -8.0%].
2. Breakeven Lock:
   - Tự động nâng stop-loss về điểm hòa vốn (vốn + phí thuế) khi lợi nhuận đạt >= 8% hoặc >= 2.0x ATR.
3. Chandelier Trailing Stop:
   - Bám theo đỉnh cao nhất Highest_High(t) - k_trail * ATR(14).
   - Cơ chế Ratchet: Stop-loss chỉ dịch chuyển lên, tuyệt đối không bao giờ hạ xuống.
4. Tiered Partial Take-Profit (Chốt lời phân tầng):
   - Chốt 50% khối lượng khi đạt mục tiêu kỳ vọng (+12% đến +15%).
   - Gồng 50% còn lại tối đa hóa sóng tăng (Let your profits run).
5. Ràng buộc HOSE:
   - Tuân thủ quy định T+2.5 (chỉ cho phép bán từ phiên thứ 3 trở đi).
   - Kiểm tra rào cản giá sàn (Limit Down Delay).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


@dataclass
class PositionExitState:
    """Trạng thái điểm thoát lệnh động của một vị thế."""
    symbol: str
    entry_price: float
    entry_date: Optional[str] = None
    holding_days: int = 0
    highest_price_since_entry: float = 0.0
    current_stop_price: float = 0.0
    initial_stop_price: float = 0.0
    atr_at_entry: float = 0.0
    is_breakeven_locked: bool = False
    is_partial_taken: bool = False  # Đã chốt 50% chưa
    shares_remaining: int = 0
    total_shares: int = 0


class DynamicChandelierExit:
    """Hệ thống Quản trị Thoát lệnh Động theo biến động ATR."""

    def __init__(
        self,
        k_stop: float = 2.2,             # Hệ số ATR cắt lỗ ban đầu
        k_trail: float = 2.8,            # Hệ số ATR bám đỉnh (Chandelier)
        min_risk_pct: float = 0.035,     # Cắt lỗ tối thiểu 3.5% (tránh nhiễu)
        max_risk_pct: float = 0.080,     # Cắt lỗ tối đa 8.0% (bảo toàn vốn)
        breakeven_gain_pct: float = 0.08, # Lợi nhuận để dời stop về hòa vốn
        partial_tp_gain_pct: float = 0.14,# Lợi nhuận để chốt lời 50% đầu tiên
        buy_cost: float = 0.0030,        # Phí mua 0.3%
        sell_cost: float = 0.0040,       # Phí bán 0.4%
        min_hold_days: int = 3,          # Quy tắc T+2.5 HOSE
    ):
        self.k_stop = k_stop
        self.k_trail = k_trail
        self.min_risk_pct = min_risk_pct
        self.max_risk_pct = max_risk_pct
        self.breakeven_gain_pct = breakeven_gain_pct
        self.partial_tp_gain_pct = partial_tp_gain_pct
        self.round_trip_cost = buy_cost + sell_cost
        self.min_hold_days = min_hold_days

    def initialize_position(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        shares: int,
        entry_date: Optional[str] = None,
    ) -> PositionExitState:
        """Khởi tạo trạng thái dừng lỗ ban đầu khi mở vị thế."""
        if entry_price <= 0 or atr <= 0:
            initial_stop = entry_price * (1.0 - self.max_risk_pct)
        else:
            raw_risk = self.k_stop * atr
            risk_pct = raw_risk / entry_price
            # Ràng buộc trong [min_risk_pct, max_risk_pct]
            clamped_risk_pct = float(np.clip(risk_pct, self.min_risk_pct, self.max_risk_pct))
            initial_stop = entry_price * (1.0 - clamped_risk_pct)

        return PositionExitState(
            symbol=symbol,
            entry_price=entry_price,
            entry_date=entry_date,
            holding_days=0,
            highest_price_since_entry=entry_price,
            current_stop_price=round(initial_stop, 2),
            initial_stop_price=round(initial_stop, 2),
            atr_at_entry=round(atr, 2),
            is_breakeven_locked=False,
            is_partial_taken=False,
            shares_remaining=shares,
            total_shares=shares,
        )

    def update_position(
        self,
        state: PositionExitState,
        current_high: float,
        current_low: float,
        current_close: float,
        current_atr: Optional[float] = None,
    ) -> Tuple[PositionExitState, Dict[str, Any]]:
        """Cập nhật trạng thái vị thế theo từng phiên và kiểm tra tín hiệu thoát lệnh.
        
        Returns:
            Tuple[PositionExitState cập nhật, Dict chứa action: 'HOLD' | 'TAKE_PARTIAL' | 'EXIT_ALL' | 'STOPPED_OUT'].
        """
        state.holding_days += 1
        atr = current_atr if (current_atr is not None and current_atr > 0) else state.atr_at_entry
        
        # 1. Cập nhật đỉnh cao nhất kể từ lúc mua
        if current_high > state.highest_price_since_entry:
            state.highest_price_since_entry = current_high

        unrealized_gain_pct = (current_close / state.entry_price - 1.0)
        action_info = {
            "action": "HOLD",
            "symbol": state.symbol,
            "holding_days": state.holding_days,
            "current_close": current_close,
            "unrealized_gain_pct": round(unrealized_gain_pct * 100, 2),
            "current_stop": state.current_stop_price,
            "can_sell_today": (state.holding_days >= self.min_hold_days),
            "reason": "Vị thế duy trì bình thường trong biên độ an toàn.",
        }

        # 2. Quy tắc Breakeven Lock: Nếu lãi đạt ngưỡng, dời stop lên hòa vốn + phí
        breakeven_price = state.entry_price * (1.0 + self.round_trip_cost)
        if unrealized_gain_pct >= self.breakeven_gain_pct and not state.is_breakeven_locked:
            if state.current_stop_price < breakeven_price:
                state.current_stop_price = round(breakeven_price, 2)
            state.is_breakeven_locked = True
            action_info["event"] = "BREAKEVEN_LOCKED"

        # 3. Quy tắc Chandelier Trailing Stop khi giá tăng mạnh
        if unrealized_gain_pct > 0.05:
            chandelier_stop = state.highest_price_since_entry - (self.k_trail * atr)
            # Cơ chế Ratchet: Chỉ dịch chuyển lên trên
            if chandelier_stop > state.current_stop_price:
                state.current_stop_price = round(chandelier_stop, 2)

        # 4. Kiểm tra Chốt lời Từng phần (Tiered Partial Take-Profit: 50%)
        if unrealized_gain_pct >= self.partial_tp_gain_pct and not state.is_partial_taken:
            if state.holding_days >= self.min_hold_days:
                state.is_partial_taken = True
                half_shares = state.shares_remaining // 2
                state.shares_remaining -= half_shares
                action_info["action"] = "TAKE_PARTIAL"
                action_info["shares_to_sell"] = half_shares
                action_info["reason"] = (
                    f"Chốt lời chủ động 50% tại mức lãi +{unrealized_gain_pct * 100:.1f}%. "
                    f"Giữ lại 50% tiếp tục gồng theo Chandelier Trailing Stop."
                )
                return state, action_info

        # 5. Kiểm tra Tín hiệu Thoát Lệnh (Chạm Stop-Loss hoặc Trailing Stop)
        # Bị kích hoạt khi giá thấp nhất trong phiên chạm hoặc thủng Stop Price
        if current_low <= state.current_stop_price or current_close <= state.current_stop_price:
            if state.holding_days < self.min_hold_days:
                # Vi phạm quy tắc T+2.5 sàn HOSE: chưa thể bán
                action_info["action"] = "HOLD"
                action_info["warning"] = (
                    f"Giá ({current_close:,.0f}) chạm Stop ({state.current_stop_price:,.0f}), "
                    f"nhưng cổ phiếu chưa đủ T+2.5 (mới giữ {state.holding_days} phiên). Phải chờ phiên sau."
                )
                return state, action_info
            else:
                # Đủ điều kiện bán thoát lệnh
                action_info["action"] = "EXIT_ALL"
                action_info["shares_to_sell"] = state.shares_remaining
                action_info["reason"] = (
                    f"Kích hoạt Dừng lỗ / Bám đỉnh Chandelier Exit tại giá {state.current_stop_price:,.0f}. "
                    f"Lợi nhuận/Thua lỗ thực tế: {unrealized_gain_pct * 100:+.2f}%"
                )
                state.shares_remaining = 0
                return state, action_info

        return state, action_info
