"""Bộ Động Cơ Phân Bổ Tỷ Trọng Vốn Động (Dynamic Volatility Targeting & Conviction Sizer).

Tối ưu hóa quản lý danh mục định lượng:
1. Inverse Volatility Targeting (Mục tiêu biến động nghịch đảo / Risk Parity):
   - Cổ phiếu có biến động ATR chuẩn hóa thấp nhận tỷ trọng lớn hơn, cổ phiếu biến động cao bị co hẹp.
2. Council Conviction Multiplier (Hệ số khuếch đại theo độ tin cậy Hội đồng AI):
   - Mã đạt sự đồng thuận cao từ nhiều chuyên gia (5-7 phiếu) được ưu tiên tỷ trọng vượt trội.
3. Đồng bộ hóa với Macro Cash Defense:
   - Tự động co hẹp tổng tỷ trọng cổ phiếu về 30% NAV khi VN-Index vào Bear Market.
4. Ràng buộc Vi cấu trúc sàn HOSE:
   - Khống chế trần tỷ trọng tối đa 20% NAV/mã.
   - Giới hạn thanh khoản tối đa 3% ADTV ngày.
   - Làm tròn xuống bội số lô chẵn 100 cổ phiếu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


@dataclass
class AllocationTarget:
    """Kết quả phân bổ tỷ trọng cho một cổ phiếu."""
    symbol: str
    price: float
    atr: float
    volatility_pct: float
    votes: int
    consensus_score: float
    target_weight_pct: float
    target_value: float
    target_shares: int
    adtv_capped: bool = False
    notes: str = ""


@dataclass
class PortfolioAllocationResult:
    """Kết quả phân bổ toàn bộ danh mục."""
    total_nav: float
    market_regime: str
    target_cash_pct: float
    target_equity_pct: float
    actual_allocated_value: float
    actual_allocated_pct: float
    actual_cash_value: float
    actual_cash_pct: float
    allocations: List[AllocationTarget] = field(default_factory=list)


class DynamicCapitalAllocator:
    """Bộ tối ưu hóa phân bổ vốn định lượng cho Hội đồng AI."""

    def __init__(
        self,
        max_position_pct: float = 0.20,     # Tối đa 20% NAV cho 1 mã
        min_position_pct: float = 0.05,     # Tối thiểu 5% NAV nếu được chọn
        lot_size: int = 100,                # Lô chẵn HOSE
        adtv_cap_pct: float = 0.03,         # Tối đa 3% thanh khoản ADTV
        total_advisors: int = 7,            # Tổng số chuyên gia trong Hội đồng
    ):
        self.max_position_pct = max_position_pct
        self.min_position_pct = min_position_pct
        self.lot_size = lot_size
        self.adtv_cap_pct = adtv_cap_pct
        self.total_advisors = total_advisors

    def allocate(
        self,
        nav: float,
        candidates: List[Dict[str, Any]],
        regime_info: Optional[Dict[str, Any]] = None,
    ) -> PortfolioAllocationResult:
        """Thực hiện tối ưu hóa phân bổ vốn cho danh sách ứng viên.
        
        Args:
            nav: Tổng giá trị tài sản ròng (VND).
            candidates: Danh sách dict [{'symbol', 'price', 'atr', 'votes', 'score', 'adtv'}].
            regime_info: Thông tin trạng thái vĩ mô từ AdvisorCouncil.detect_market_regime.
        """
        if nav <= 0 or not candidates:
            return PortfolioAllocationResult(
                total_nav=nav,
                market_regime="UNKNOWN",
                target_cash_pct=1.0,
                target_equity_pct=0.0,
                actual_allocated_value=0.0,
                actual_allocated_pct=0.0,
                actual_cash_value=nav,
                actual_cash_pct=1.0,
                allocations=[],
            )

        # 1. Xác định Ngân sách Cổ phiếu theo Macro Regime
        regime_info = regime_info or {"regime": "NEUTRAL", "cash_pct": 0.20, "equity_pct": 0.80}
        regime_name = regime_info.get("regime", "NEUTRAL")
        target_cash_pct = float(regime_info.get("cash_pct", 0.20))
        target_equity_pct = float(1.0 - target_cash_pct)

        # 2. Tính toán độ biến động chuẩn hóa và hệ số niềm tin
        clean_candidates = []
        for c in candidates:
            price = float(c.get("price", 0))
            if price <= 0:
                continue
            atr = float(c.get("atr", price * 0.025))
            vol_pct = (atr / price) if price > 0 else 0.025
            vol_pct = max(0.005, vol_pct)  # Tránh chia cho 0 hoặc biến động âm
            
            votes = int(c.get("votes", 1))
            score = float(c.get("score", 0.5))
            adtv = float(c["adtv"]) if ("adtv" in c and c["adtv"] is not None) else None

            # Hệ số niềm tin (Conviction Multiplier)
            # Thang điểm [0.6 -> 1.3] tùy theo số phiếu và điểm đồng thuận
            vote_factor = min(1.0, votes / self.total_advisors)
            conviction = 0.60 + 0.40 * vote_factor + 0.30 * np.clip(score, 0.0, 1.0)

            inv_vol = 1.0 / vol_pct
            raw_weight = inv_vol * conviction

            clean_candidates.append({
                "symbol": c["symbol"],
                "price": price,
                "atr": atr,
                "vol_pct": vol_pct,
                "votes": votes,
                "score": score,
                "adtv": adtv,
                "raw_weight": raw_weight,
            })

        if not clean_candidates:
            return PortfolioAllocationResult(
                total_nav=nav,
                market_regime=regime_name,
                target_cash_pct=target_cash_pct,
                target_equity_pct=target_equity_pct,
                actual_allocated_value=0.0,
                actual_allocated_pct=0.0,
                actual_cash_value=nav,
                actual_cash_pct=1.0,
                allocations=[],
            )

        # 3. Chuẩn hóa trọng số sao cho tổng bằng target_equity_pct
        sum_raw = sum(c["raw_weight"] for c in clean_candidates)
        for c in clean_candidates:
            c["norm_weight"] = (c["raw_weight"] / sum_raw) * target_equity_pct

        # 4. Áp dụng trần tỷ trọng tối đa và tái phân bổ phần dư
        for _ in range(3):  # 3 vòng lặp để phân phối mượt phần dôi dư
            excess = 0.0
            unlocked_count = 0
            for c in clean_candidates:
                if c["norm_weight"] > self.max_position_pct:
                    excess += (c["norm_weight"] - self.max_position_pct)
                    c["norm_weight"] = self.max_position_pct
                else:
                    unlocked_count += 1
            if excess <= 0 or unlocked_count == 0:
                break
            for c in clean_candidates:
                if c["norm_weight"] < self.max_position_pct:
                    c["norm_weight"] += excess / unlocked_count

        # 5. Định cỡ số lượng cổ phiếu (Shares) & Ràng buộc thanh khoản ADTV
        allocations: List[AllocationTarget] = []
        actual_total_val = 0.0

        for c in clean_candidates:
            weight = c["norm_weight"]
            target_val = nav * weight
            price = c["price"]

            # Giới hạn theo ADTV (nếu có cung cấp dữ liệu thanh khoản)
            if c["adtv"] is not None and c["adtv"] > 0:
                max_shares_adtv = int((c["adtv"] * self.adtv_cap_pct) / price)
            else:
                max_shares_adtv = 999_999_999
            ideal_shares = target_val / price
            
            # Làm tròn lô chẵn 100
            lot_shares = int(np.floor(ideal_shares / self.lot_size)) * self.lot_size
            final_shares = min(lot_shares, int(np.floor(max_shares_adtv / self.lot_size)) * self.lot_size)
            final_shares = max(0, final_shares)

            actual_val = final_shares * price
            actual_total_val += actual_val
            is_adtv_cap = (final_shares < lot_shares)

            notes = []
            if is_adtv_cap:
                notes.append("Bị chặn trần bởi thanh khoản 3% ADTV")
            if c["votes"] >= 4:
                notes.append(f"Đồng thuận cao ({c['votes']}/{self.total_advisors} phiếu)")

            allocations.append(AllocationTarget(
                symbol=c["symbol"],
                price=price,
                atr=round(c["atr"], 2),
                volatility_pct=round(c["vol_pct"] * 100, 2),
                votes=c["votes"],
                consensus_score=round(c["score"], 3),
                target_weight_pct=round((actual_val / nav) * 100, 2) if nav > 0 else 0.0,
                target_value=round(actual_val, 0),
                target_shares=final_shares,
                adtv_capped=is_adtv_cap,
                notes="; ".join(notes) if notes else "Tỷ trọng tối ưu theo biến động ATR",
            ))

        actual_allocated_pct = actual_total_val / nav if nav > 0 else 0.0
        actual_cash_val = nav - actual_total_val
        actual_cash_pct = actual_cash_val / nav if nav > 0 else 0.0

        return PortfolioAllocationResult(
            total_nav=nav,
            market_regime=regime_name,
            target_cash_pct=round(target_cash_pct * 100, 2),
            target_equity_pct=round(target_equity_pct * 100, 2),
            actual_allocated_value=round(actual_total_val, 0),
            actual_allocated_pct=round(actual_allocated_pct * 100, 2),
            actual_cash_value=round(actual_cash_val, 0),
            actual_cash_pct=round(actual_cash_pct * 100, 2),
            allocations=allocations,
        )
