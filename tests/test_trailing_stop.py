"""Kiểm định Cơ chế Chốt lời / Cắt lỗ Động theo Biến động ATR (Dynamic Chandelier Exit)."""

from __future__ import annotations

import pytest
from dudu.execution.trailing_stop import DynamicChandelierExit, PositionExitState


def test_initialize_position_clamped():
    """Initial stop-loss phải được khống chế an toàn trong biên độ [3.5%, 8.0%]."""
    manager = DynamicChandelierExit(k_stop=2.0, min_risk_pct=0.035, max_risk_pct=0.080)
    
    # 1. Cổ phiếu bluechip biến động cực thấp: ATR = 1.0 trên giá 100 -> raw risk = 2.0% -> Clamp lên 3.5%
    state_low = manager.initialize_position("VNM", entry_price=100.0, atr=1.0, shares=1000)
    assert state_low.initial_stop_price == 96.5  # 100 - 3.5%

    # 2. Cổ phiếu đầu cơ biến động cực cao: ATR = 6.0 trên giá 100 -> raw risk = 12% -> Clamp xuống 8.0%
    state_high = manager.initialize_position("DIG", entry_price=100.0, atr=6.0, shares=1000)
    assert state_high.initial_stop_price == 92.0  # 100 - 8.0%


def test_t25_rule_blocks_early_exit():
    """Tại T+1 hoặc T+2, dù giá có chạm stop-loss vẫn không thể bán theo luật T+2.5 HOSE."""
    manager = DynamicChandelierExit()
    state = manager.initialize_position("FPT", entry_price=100.0, atr=3.0, shares=1000)
    # Stop price ban đầu khoảng 93.4 (100 - 2.2 * 3.0 = 93.4)

    # Phiên 1 (T+1): Giá sập sàn về 90.0 (thủng stop)
    state, act1 = manager.update_position(state, current_high=98.0, current_low=90.0, current_close=91.0)
    assert act1["action"] == "HOLD"
    assert "chưa đủ T+2.5" in act1.get("warning", "")
    assert state.shares_remaining == 1000  # Vẫn giữ nguyên cổ phiếu


def test_breakeven_lock_triggered():
    """Khi lợi nhuận đạt >= 8%, Stop-loss tự động dời lên điểm hòa vốn có tính phí."""
    manager = DynamicChandelierExit(breakeven_gain_pct=0.08)
    state = manager.initialize_position("MWG", entry_price=100.0, atr=2.5, shares=1000)
    assert state.current_stop_price < 100.0

    # Giá tăng lên 109.0 (lãi +9%)
    state, act = manager.update_position(state, current_high=110.0, current_low=102.0, current_close=109.0)
    assert state.is_breakeven_locked is True
    # Breakeven price = 100 * (1 + 0.007) = 100.7
    assert state.current_stop_price >= 100.7


def test_chandelier_trailing_stop_ratchet():
    """Đường dừng lỗ Chandelier bám đỉnh và chỉ dịch chuyển lên (Ratchet mechanism)."""
    manager = DynamicChandelierExit(k_trail=2.5)
    state = manager.initialize_position("SSI", entry_price=100.0, atr=2.0, shares=1000)

    # Phiên 1: Giá lên 110 (High 112)
    state, _ = manager.update_position(state, current_high=112.0, current_low=101.0, current_close=110.0, current_atr=2.0)
    stop_p1 = state.current_stop_price
    # Highest high = 112, chandelier = 112 - 2.5 * 2.0 = 107.0
    assert stop_p1 == 107.0

    # Phiên 2: Giá lên tiếp 120 (High 122)
    state, _ = manager.update_position(state, current_high=122.0, current_low=109.0, current_close=120.0, current_atr=2.0)
    stop_p2 = state.current_stop_price
    # Chandelier = 122 - 5.0 = 117.0
    assert stop_p2 == 117.0
    assert stop_p2 > stop_p1

    # Phiên 3: Giá điều chỉnh giảm nhẹ về 118 (High chỉ 119) -> Stop-loss KHÔNG được hạ xuống
    state, _ = manager.update_position(state, current_high=119.0, current_low=117.5, current_close=118.0, current_atr=2.0)
    assert state.current_stop_price == 117.0  # Không bị hạ


def test_tiered_partial_take_profit_and_exit():
    """Chốt lời 50% khi đạt mục tiêu và thoát toàn bộ khi gãy stop sau T+2.5."""
    manager = DynamicChandelierExit(partial_tp_gain_pct=0.15, min_hold_days=3)
    state = manager.initialize_position("HPG", entry_price=100.0, atr=2.0, shares=1000)

    # Trải qua 3 phiên cho đủ T+2.5
    state, _ = manager.update_position(state, 105.0, 99.0, 104.0)
    state, _ = manager.update_position(state, 110.0, 103.0, 109.0)

    # Phiên 3: Đạt lãi +16% (Close 116) -> Kích hoạt chốt lời 50%
    state, act_tp = manager.update_position(state, 117.0, 109.0, 116.0)
    assert act_tp["action"] == "TAKE_PARTIAL"
    assert act_tp["shares_to_sell"] == 500
    assert state.shares_remaining == 500
    assert state.is_partial_taken is True

    # Phiên 4: Giá đảo chiều sập thủng Stop-loss -> Bán nốt 500 cổ phiếu còn lại
    current_stop = state.current_stop_price
    state, act_exit = manager.update_position(state, current_stop + 1.0, current_stop - 2.0, current_stop - 1.0)
    assert act_exit["action"] == "EXIT_ALL"
    assert act_exit["shares_to_sell"] == 500
    assert state.shares_remaining == 0
