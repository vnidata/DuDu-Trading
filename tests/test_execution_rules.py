"""Kiểm thử bộ quy tắc vi cấu trúc giao dịch sàn HOSE (HOSE Execution Rules).

Kế thừa từ VN-SWING:
- Limit up: Không thể mua được khi mở cửa ở giá trần (+7%)
- Limit down: Không thể bán được khi mở cửa ở giá sàn (-7%), vị thế tiếp tục giữ
- Floor streak: Chuỗi sàn liên tiếp ghi nhận lỗ thực tế đầy đủ
- Min hold: Giữ vị thế tối thiểu 3 phiên (T+2.5) trước khi được khớp bán
- Cost accounting: Lỗ đúng bằng tổng thuế phí mua + bán
- Sizing arithmetic: Tỷ lệ phân bổ vốn theo ATR và mức chịu rủi ro
- Position caps: Giới hạn trần tỷ trọng NAV (max_w) và ADTV fraction
- Delisting: Thanh lý mã bị hủy niêm yết với mức chiết khấu delist_haircut
"""

from __future__ import annotations

import numpy as np
import pytest

from dudu.execution.rules import (
    HoseMarketRules,
    can_fill_buy_ato,
    can_fill_sell_ato,
    calculate_position_size,
    ExecutionSimulator,
    simulate_order_fill,
)


def test_limit_up_no_fill():
    """Mở cửa ở giá trần (+7% so với tham chiếu) -> Không mua được."""
    prev_close = 20000.0
    ceiling_px = prev_close * 1.07
    normal_px = 20500.0

    # Giá mở cửa tại trần -> không khớp
    assert can_fill_buy_ato(ceiling_px, prev_close) is False
    assert simulate_order_fill("BUY", ceiling_px, prev_close) is False

    # Giá mở cửa dưới trần -> khớp thành công
    assert can_fill_buy_ato(normal_px, prev_close) is True
    assert simulate_order_fill("BUY", normal_px, prev_close) is True


def test_limit_down_no_sell():
    """Mở cửa ở giá sàn (-7% so với tham chiếu) -> Không bán được."""
    prev_close = 20000.0
    floor_px = prev_close * 0.93
    normal_px = 19500.0

    # Giá mở cửa tại sàn -> không khớp bán
    assert can_fill_sell_ato(floor_px, prev_close) is False
    assert simulate_order_fill("SELL", floor_px, prev_close) is False

    # Giá mở cửa trên sàn -> khớp bán thành công
    assert can_fill_sell_ato(normal_px, prev_close) is True
    assert simulate_order_fill("SELL", normal_px, prev_close) is True


def test_floor_streak():
    """Chuỗi sàn 5 phiên liên tiếp -> Lỗ lũy kế thực tế được ghi nhận trung thực."""
    sim = ExecutionSimulator()
    entry_px = 20000.0

    # 5 phiên giảm sàn liên tiếp (-7% mỗi phiên)
    exit_px = entry_px * (0.93 ** 5)
    trade = sim.simulate_trade(entry_price=entry_px, exit_price=exit_px, holding_days=8)

    # Lỗ thực tế phải sâu hơn -30%
    assert trade["pnl_pct"] < -0.30
    assert trade["holding_days"] == 8


def test_min_hold():
    """Ràng buộc chu kỳ thanh toán T+2.5: Giữ tối thiểu 3 phiên."""
    rules = HoseMarketRules(min_hold=3)
    assert rules.min_hold == 3


def test_cost_accounting():
    """Một lệnh khứ hồi mua bán, giá đứng yên -> Lỗ đúng bằng phí mua + phí và thuế bán."""
    sim = ExecutionSimulator()
    px = 10000.0
    trade = sim.simulate_trade(entry_price=px, exit_price=px, holding_days=4)

    # Phí mua 0.3%, bán 0.4%
    # expected_ret = (10000 * 0.996) / (10000 * 1.003) - 1.0 = -0.6979%
    expected_ret = (10000.0 * (1.0 - 0.004)) / (10000.0 * (1.0 + 0.003)) - 1.0
    assert abs(trade["pnl_pct"] - expected_ret) < 1e-5


def test_sizing_arithmetic():
    """ATR = 3% giá, k=3, risk=1% vốn -> Quy mô vị thế xấp xỉ 11.11% vốn."""
    equity = 1_000_000_000.0
    px = 20000.0
    atr = 0.03 * px

    shares = calculate_position_size(
        equity=equity,
        price=px,
        atr=atr,
        k_stop=3.0,
        risk_pct=0.01,
        max_w=0.20,
        lot=100,
    )
    pos_val = shares * px
    pct_equity = pos_val / equity
    # Giá trị phải tiệm cận 1/9 vốn (khoảng 11.11%)
    assert abs(pct_equity - (1.0 / 9.0)) < 0.005


def test_position_caps():
    """Giới hạn tỷ trọng tối đa (max_w) và thanh khoản ADTV."""
    equity = 1_000_000_000.0
    px = 10000.0
    atr = 100.0  # ATR rất nhỏ dẫn đến risk sizing muốn mua cực nhiều

    # Giới hạn max_w = 15%
    shares = calculate_position_size(
        equity=equity,
        price=px,
        atr=atr,
        k_stop=1.0,
        risk_pct=0.10,
        max_w=0.15,
        lot=100,
    )
    pos_val = shares * px
    assert pos_val <= 0.15 * equity + 100.0

    # Giới hạn ADTV: 3% của 10 tỷ ADTV = 300 triệu
    adtv = 10_000_000_000.0
    shares_adtv = calculate_position_size(
        equity=equity,
        price=px,
        atr=atr,
        k_stop=1.0,
        risk_pct=0.50,
        max_w=0.50,
        adtv=adtv,
        adtv_frac=0.03,
        lot=100,
    )
    pos_val_adtv = shares_adtv * px
    assert pos_val_adtv <= 0.03 * adtv + 100.0


def test_delisting():
    """Cổ phiếu bị hủy niêm yết (delisted) chịu chiết khấu thanh lý haircut 50%."""
    sim = ExecutionSimulator()
    entry_px = 20000.0
    last_px = 20000.0

    trade = sim.simulate_trade(
        entry_price=entry_px,
        exit_price=last_px,
        holding_days=10,
        is_delisted=True,
    )
    # Lỗ phải sâu hơn 45% do mất 50% giá trị cộng thuế phí
    assert trade["pnl_pct"] < -0.45
