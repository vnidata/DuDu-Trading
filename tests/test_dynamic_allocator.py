"""Kiểm định Động Cơ Phân Bổ Tỷ Trọng Vốn Động (Dynamic Volatility Targeting & Conviction Sizer)."""

from __future__ import annotations

import pytest
from dudu.execution.allocator import DynamicCapitalAllocator


def test_allocator_bear_market_cash_defense():
    """Trong Bear Market, tổng tỷ trọng cổ phiếu phải co hẹp tối đa 30%, bảo toàn 70% tiền mặt."""
    allocator = DynamicCapitalAllocator()
    candidates = [
        {"symbol": "FPT", "price": 100_000, "atr": 2000, "votes": 5, "score": 0.8},
        {"symbol": "VNM", "price": 70_000, "atr": 1000, "votes": 4, "score": 0.6},
        {"symbol": "MWG", "price": 50_000, "atr": 1200, "votes": 4, "score": 0.5},
    ]
    bear_regime = {"regime": "BEAR", "cash_pct": 0.70, "equity_pct": 0.30}
    res = allocator.allocate(nav=1_000_000_000, candidates=candidates, regime_info=bear_regime)

    assert res.market_regime == "BEAR"
    assert res.target_cash_pct == 70.0
    assert res.actual_allocated_pct <= 30.0
    assert res.actual_cash_pct >= 70.0


def test_allocator_inverse_volatility():
    """Mã biến động thấp (Low Volatility) phải được cấp tỷ trọng cao hơn mã biến động mạnh."""
    allocator = DynamicCapitalAllocator(max_position_pct=0.80)  # Nâng trần để quan sát sự phân hóa tỷ trọng
    candidates = [
        {"symbol": "LOW_VOL", "price": 100_000, "atr": 1_000, "votes": 3, "score": 0.5},  # Vol = 1%
        {"symbol": "HIGH_VOL", "price": 100_000, "atr": 6_000, "votes": 3, "score": 0.5}, # Vol = 6%
    ]
    bull_regime = {"regime": "BULL", "cash_pct": 0.05, "equity_pct": 0.95}
    res = allocator.allocate(nav=1_000_000_000, candidates=candidates, regime_info=bull_regime)

    w_low = next(a.target_weight_pct for a in res.allocations if a.symbol == "LOW_VOL")
    w_high = next(a.target_weight_pct for a in res.allocations if a.symbol == "HIGH_VOL")

    assert w_low > w_high
    assert w_low >= w_high * 2.0  # Tỷ trọng chênh lệch rõ rệt theo nghịch đảo biến động


def test_allocator_conviction_boost():
    """Mã có nhiều chuyên gia đồng thuận (Votes cao) được tăng cường tỷ trọng vốn."""
    allocator = DynamicCapitalAllocator(max_position_pct=0.40)
    candidates = [
        {"symbol": "CONSENSUS_HIGH", "price": 50_000, "atr": 1_500, "votes": 6, "score": 0.9},
        {"symbol": "CONSENSUS_LOW", "price": 50_000, "atr": 1_500, "votes": 1, "score": 0.1},
    ]
    res = allocator.allocate(nav=1_000_000_000, candidates=candidates)

    w_high = next(a.target_weight_pct for a in res.allocations if a.symbol == "CONSENSUS_HIGH")
    w_low = next(a.target_weight_pct for a in res.allocations if a.symbol == "CONSENSUS_LOW")

    assert w_high > w_low


def test_allocator_max_position_cap_and_lots():
    """Mọi vị thế không được vượt trần 20% NAV và số lượng cổ phiếu phải là bội số của 100."""
    allocator = DynamicCapitalAllocator(max_position_pct=0.20, lot_size=100)
    candidates = [
        {"symbol": "FPT", "price": 100_000, "atr": 1_000, "votes": 7, "score": 1.0},
        {"symbol": "VNM", "price": 70_000, "atr": 700, "votes": 7, "score": 1.0},
    ]
    res = allocator.allocate(nav=1_000_000_000, candidates=candidates)

    for item in res.allocations:
        assert item.target_weight_pct <= 20.01  # Không vượt quá trần 20%
        assert item.target_shares % 100 == 0   # Lô chẵn 100


def test_allocator_adtv_liquidity_cap():
    """Số lượng cổ phiếu không được vượt quá 3% thanh khoản ADTV."""
    allocator = DynamicCapitalAllocator(adtv_cap_pct=0.03, lot_size=100)
    # Mã thanh khoản yếu: chỉ có 200 triệu VND ADTV
    candidates = [
        {"symbol": "ILLIQUID", "price": 10_000, "atr": 200, "votes": 5, "score": 0.8, "adtv": 200_000_000},
    ]
    # NAV lớn 10 tỷ
    res = allocator.allocate(nav=10_000_000_000, candidates=candidates)
    item = res.allocations[0]

    # Max value by ADTV: 200M * 3% = 6M VND -> Max shares = 600 CP
    assert item.target_shares <= 600
    assert item.adtv_capped is True
    assert "thanh khoản" in item.notes
