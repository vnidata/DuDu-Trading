"""Quy tắc khớp lệnh và mô hình vi cấu trúc thị trường chứng khoán HOSE.

Kế thừa từ chuẩn mực định chế của VN-SWING:
- Ràng buộc biên độ trần/sàn ±7%
- Chu kỳ thanh toán T+2.5 (giữ tối thiểu 3 phiên)
- Lô chẵn 100 cổ phiếu
- Trượt giá theo thanh khoản ADTV
- Chi phí giao dịch: 0.3% mua, 0.4% bán (thuế + phí)
- Chiết khấu thanh lý mã hủy niêm yết (delist haircut)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


@dataclass
class HoseMarketRules:
    """Tham số vi cấu trúc giao dịch sàn HOSE."""
    limit: float = 0.07                # Biên độ dao động giá ±7%
    min_hold: int = 3                  # Giữ tối thiểu 3 phiên (T+2.5)
    lot: int = 100                     # Lô chẵn 100 cổ phiếu
    buy_cost: float = 0.0030           # Phí mua 0.30%
    sell_cost: float = 0.0040          # Phí + Thuế bán 0.40%
    max_w: float = 0.15                # Giới hạn tỷ trọng tối đa 15% NAV/mã
    max_pos: int = 10                  # Tối đa 10 vị thế đồng thời
    adtv_frac: float = 0.03            # Giới hạn tham gia tối đa 3% ADTV phiên
    min_adtv: float = 1e6              # Thanh khoản tối thiểu
    delist_haircut: float = 0.50       # Chiết khấu 50% khi mã hủy niêm yết
    ato_fill_prob: float = 1.0         # Xác suất khớp lệnh ATO


def can_fill_buy_ato(open_px: float, prev_close: float, limit: float = 0.07) -> bool:
    """Kiểm tra điều kiện khớp mua ATO. Mở cửa ở giá trần -> Không mua được."""
    if np.isnan(open_px) or np.isnan(prev_close) or prev_close <= 0:
        return False
    ceiling_px = prev_close * (1.0 + limit - 0.002)
    return open_px < ceiling_px


def can_fill_sell_ato(open_px: float, prev_close: float, limit: float = 0.07) -> bool:
    """Kiểm tra điều kiện khớp bán ATO. Mở cửa ở giá sàn -> Không bán được."""
    if np.isnan(open_px) or np.isnan(prev_close) or prev_close <= 0:
        return False
    floor_px = prev_close * (1.0 - limit + 0.002)
    return open_px > floor_px


def calculate_position_size(
    equity: float,
    price: float,
    atr: float,
    k_stop: float = 3.0,
    risk_pct: float = 0.01,
    max_w: float = 0.15,
    adtv: Optional[float] = None,
    adtv_frac: float = 0.03,
    lot: int = 100,
) -> int:
    """Tính số lượng cổ phiếu vào lệnh theo quản trị rủi ro ATR và giới hạn tỷ trọng."""
    if price <= 0 or atr <= 0:
        return 0
    risk_ps = k_stop * atr
    if risk_ps <= 0:
        return 0
    # 1. Định cỡ theo rủi ro (Risk-based sizing)
    raw_shares = (risk_pct * equity) / risk_ps

    # 2. Giới hạn tỷ trọng vốn tối đa
    max_shares_cap = (equity * max_w) / price
    raw_shares = min(raw_shares, max_shares_cap)

    # 3. Giới hạn theo thanh khoản ADTV nếu có
    if adtv is not None and adtv > 0:
        adtv_shares_cap = (adtv * adtv_frac) / price
        raw_shares = min(raw_shares, adtv_shares_cap)

    # 4. Làm tròn xuống bội số của lô
    shares = int(np.floor(raw_shares / lot)) * lot
    return max(0, shares)


class ExecutionSimulator:
    """Bộ mô phỏng thực thi lệnh định chế."""

    def __init__(self, rules: Optional[HoseMarketRules] = None):
        self.rules = rules or HoseMarketRules()

    def simulate_trade(
        self,
        entry_price: float,
        exit_price: float,
        holding_days: int,
        is_delisted: bool = False,
    ) -> Dict[str, Any]:
        """Tính toán kết quả giao dịch sau thuế, phí và trượt giá."""
        r = self.rules
        if is_delisted:
            realized_exit = exit_price * (1.0 - r.delist_haircut)
        else:
            realized_exit = exit_price

        # Giá vốn mua thực tế sau phí
        cost_basis = entry_price * (1.0 + r.buy_cost)
        # Giá thu về sau thuế phí bán
        net_proceeds = realized_exit * (1.0 - r.sell_cost)

        pnl_pct = (net_proceeds / cost_basis) - 1.0

        return {
            "entry_price": entry_price,
            "exit_price": realized_exit,
            "cost_basis": cost_basis,
            "net_proceeds": net_proceeds,
            "pnl_pct": pnl_pct,
            "holding_days": holding_days,
            "is_delisted": is_delisted,
        }


def simulate_order_fill(
    side: str,
    open_px: float,
    prev_close: float,
    limit: float = 0.07,
) -> bool:
    """Hàm kiểm tra khớp lệnh nhanh."""
    if side.upper() == "BUY":
        return can_fill_buy_ato(open_px, prev_close, limit)
    elif side.upper() == "SELL":
        return can_fill_sell_ato(open_px, prev_close, limit)
    return False
