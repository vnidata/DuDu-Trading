"""Hội Đồng Đa Chuyên Gia AI (Multi-Advisor AI Council).

Tổng hợp ý kiến từ 6 trường phái đầu tư:
1. Chủ Động (Active - 2W, Động Lượng)
2. Nhịp Nhàng (Harmony - 1M, Xu Hướng Bền Vững)
3. Bền Bỉ (Persistent - 3M, Phòng Thủ Biến Động Thấp)
4. CANSLIM Breakout (Bùng Nổ Khối Lượng)
5. Mean Reversion (Đảo Chiều Quá Bán)
6. Turtle Donchian S2 (Bứt Phá 55 Phiên)

Quản trị Macro Regime và kích hoạt Cash Defense Rule khi thị trường suy thoái.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .base import BaseAdvisor
from .active import ActiveAdvisor
from .harmony import HarmonyAdvisor
from .persistent import PersistentAdvisor
from .canslim import CanslimAdvisor
from .mean_reversion import MeanReversionAdvisor
from .turtle import TurtleAdvisor
from .pullback import PullbackAdvisor


class AdvisorCouncil:
    """Hội đồng Cố vấn AI điều phối chiến lược và phân bổ vốn danh mục."""

    def __init__(self, advisors: Optional[List[BaseAdvisor]] = None):
        self.advisors: List[BaseAdvisor] = advisors or [
            ActiveAdvisor(),
            HarmonyAdvisor(),
            PersistentAdvisor(),
            CanslimAdvisor(),
            MeanReversionAdvisor(),
            TurtleAdvisor(),
            PullbackAdvisor(),
        ]

    def detect_market_regime(self, benchmark_df: pd.DataFrame) -> Dict[str, Any]:
        """Xác định trạng thái vĩ mô của VN-Index và quy định tỷ lệ phòng thủ tiền mặt."""
        if benchmark_df is None or len(benchmark_df) < 50:
            return {"regime": "NEUTRAL", "cash_pct": 0.20, "equity_pct": 0.80, "reason": "Dữ liệu chỉ số hạn chế"}

        c = float(benchmark_df["close"].iloc[-1])
        sma20 = float(benchmark_df["close"].tail(20).mean())
        sma50 = float(benchmark_df["close"].tail(50).mean())
        sma200 = float(benchmark_df["close"].tail(200).mean()) if len(benchmark_df) >= 200 else sma50

        if c < sma50 and sma20 < sma50:
            # Bear Market rõ rệt: Kích hoạt Cash Defense bảo toàn vốn tối đa
            return {
                "regime": "BEAR",
                "is_bear": True,
                "cash_pct": 0.70,
                "equity_pct": 0.30,
                "reason": "VN-Index nằm dưới SMA50 và SMA20 hướng xuống. Kích hoạt phòng thủ tiền mặt (Cash Defense).",
            }
        elif c > sma50 and sma20 > sma50:
            # Uptrend lành mạnh
            return {
                "regime": "BULL",
                "is_bear": False,
                "cash_pct": 0.05,
                "equity_pct": 0.95,
                "reason": "VN-Index giữ vững trên SMA50 và SMA20. Thị trường thuận lợi giải ngân toàn diện.",
            }
        else:
            # Sideway biến động
            return {
                "regime": "SIDEWAY",
                "is_bear": False,
                "cash_pct": 0.30,
                "equity_pct": 0.70,
                "reason": "VN-Index đi ngang tích lũy quanh SMA50. Duy trì tỷ trọng cổ phiếu thận trọng.",
            }

    def evaluate_universe(
        self,
        symbol_data: Dict[str, pd.DataFrame],
        benchmark_df: Optional[pd.DataFrame] = None,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> Dict[str, Any]:
        """Đánh giá toàn bộ vũ trụ cổ phiếu và tổng hợp khuyến nghị của từng chuyên gia."""
        regime_info = self.detect_market_regime(benchmark_df) if benchmark_df is not None else {"regime": "NEUTRAL", "cash_pct": 0.10}

        results_by_advisor: Dict[str, List[Dict[str, Any]]] = {}
        symbol_consensus_scores: Dict[str, float] = {}
        symbol_vote_count: Dict[str, int] = {}

        for advisor in self.advisors:
            scored_symbols = []
            for sym, df in symbol_data.items():
                s = advisor.score_symbol(sym, df, as_of_date=as_of_date, benchmark_df=benchmark_df)
                if s > -900:  # Không vi phạm điều kiện lọc cứng
                    scored_symbols.append({"symbol": sym, "score": round(s, 4)})
                    symbol_consensus_scores[sym] = symbol_consensus_scores.get(sym, 0.0) + s
                    if s > 0.10:
                        symbol_vote_count[sym] = symbol_vote_count.get(sym, 0) + 1

            # Sắp xếp điểm giảm dần
            scored_symbols.sort(key=lambda x: x["score"], reverse=True)
            top_picks = scored_symbols[:advisor.portfolio_size]
            results_by_advisor[advisor.name] = {
                "advisor_name": advisor.name,
                "description": advisor.description,
                "rebalance_days": advisor.rebalance_days,
                "allocation_method": advisor.allocation_method.value,
                "top_picks": top_picks,
            }

        # Đồng thuận toàn hội đồng (Consensus Ranking)
        sorted_consensus = sorted(
            symbol_consensus_scores.items(), key=lambda x: x[1], reverse=True
        )
        council_top = [
            {
                "symbol": sym,
                "aggregate_score": round(score, 4),
                "votes": symbol_vote_count.get(sym, 0),
            }
            for sym, score in sorted_consensus[:10]
        ]

        return {
            "market_regime": regime_info,
            "advisors": results_by_advisor,
            "council_consensus_top": council_top,
        }
