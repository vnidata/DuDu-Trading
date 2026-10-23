"""Base AI Advisor class và cơ chế chấm điểm nhân tố đa chiều (Multi-Factor Scoring).

Kế thừa từ vn-stock-ai-advisors:
- Chuẩn hóa bộ gene định lượng (Quantitative Factor Genome)
- Chống nhìn trước tương lai (Point-in-Time Safe)
- Bộ lọc Macro Cash Defense Rule (chuyển tỷ trọng sang tiền mặt khi VN-Index gãy MA50)
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


class AllocationMethod(str, Enum):
    EQUAL_WEIGHT = "Equal Weight (20%)"
    RANK_LADDER = "Rank Ladder (30-25-20-15-10%)"
    RISK_PARITY = "Risk Parity (Nghịch đảo ATR)"


class BaseAdvisor(ABC):
    """Lớp cơ sở trừu tượng cho mọi Chuyên gia AI Quản lý Danh mục."""

    def __init__(
        self,
        name: str,
        description: str,
        rebalance_days: int = 21,
        portfolio_size: int = 5,
        allocation_method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT,
        genome: Optional[Dict[str, float]] = None,
    ):
        self.name = name
        self.description = description
        self.rebalance_days = rebalance_days
        self.portfolio_size = portfolio_size
        self.allocation_method = allocation_method

        self.genome: Dict[str, float] = genome or {
            "w_momentum_20d": 0.20,
            "w_momentum_60d": 0.15,
            "w_trend_alignment": 0.20,
            "w_vol_breakout": 0.15,
            "w_relative_strength": 0.15,
            "w_low_volatility": 0.05,
            "w_mean_reversion": 0.05,
            "w_drawdown_recovery": 0.05,
        }
        self.normalize_genome()

    def normalize_genome(self) -> None:
        """Chuẩn hóa trọng số gene sao cho tổng bằng 1.0."""
        total = sum(self.genome.values())
        if total > 0:
            self.genome = {k: v / total for k, v in self.genome.items()}

    def score_symbol(
        self,
        symbol: str,
        df: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp] = None,
        benchmark_df: Optional[pd.DataFrame] = None,
    ) -> float:
        """Chấm điểm định lượng Point-in-Time cho một mã cổ phiếu tại ngày chỉ định."""
        if df is None or len(df) < 30:
            return -999.0

        if as_of_date is not None:
            # Lọc dữ liệu nghiêm ngặt trước ngày as_of_date
            times = pd.to_datetime(df["time"]).values
            target = np.datetime64(pd.to_datetime(as_of_date))
            idx = int(np.searchsorted(times, target))
            if idx < 30:
                return -999.0
            hist = df.iloc[:idx]
        else:
            hist = df

        latest = hist.iloc[-1]
        c = float(latest.get("close", 0))
        if c <= 0:
            return -999.0

        # ---------------------------------------------------------------------
        # Gate 1: Macro Market Regime Check & Cash Defense
        # ---------------------------------------------------------------------
        if benchmark_df is not None and len(benchmark_df) > 50:
            if as_of_date is not None:
                bm_times = pd.to_datetime(benchmark_df["time"]).values
                bm_target = np.datetime64(pd.to_datetime(as_of_date))
                bm_idx = int(np.searchsorted(bm_times, bm_target))
                bm_hist = benchmark_df.iloc[:bm_idx] if bm_idx > 50 else benchmark_df
            else:
                bm_hist = benchmark_df

            if len(bm_hist) >= 50:
                bm_latest = bm_hist.iloc[-1]
                bm_close = float(bm_latest.get("close", 0))
                bm_sma50 = float(bm_latest.get("sma_50", bm_hist["close"].tail(50).mean()))
                bm_sma20 = float(bm_latest.get("sma_20", bm_hist["close"].tail(20).mean()))

                is_bear = (bm_close < bm_sma50 and bm_close < bm_sma20)
                if is_bear:
                    # Trong Bear Market, chỉ chấp nhận mã có RS > 65 hoặc gần SMA50
                    rs = float(latest.get("rs_rating", 50.0))
                    sma50 = float(latest.get("sma_50", hist["close"].tail(50).mean())) if len(hist) >= 50 else c
                    if "Mean_Reversion" not in self.name:
                        if rs < 60.0 or c < sma50 * 0.95:
                            return -999.0

        # ---------------------------------------------------------------------
        # Tính toán các nhân tố định lượng (Factors)
        # ---------------------------------------------------------------------
        close_series = hist["close"]
        vol_series = hist["volume"]

        # 1. Momentum 20d & 60d
        mom20 = (c / float(close_series.iloc[-21]) - 1.0) if len(close_series) >= 21 else 0.0
        mom60 = (c / float(close_series.iloc[-61]) - 1.0) if len(close_series) >= 61 else 0.0

        # 2. Trend Alignment (SMA20 > SMA50 > SMA200)
        sma20 = float(close_series.tail(20).mean())
        sma50 = float(close_series.tail(50).mean()) if len(close_series) >= 50 else sma20
        sma200 = float(close_series.tail(200).mean()) if len(close_series) >= 200 else sma50

        trend_score = 0.0
        if c > sma20:
            trend_score += 0.3
        if sma20 > sma50:
            trend_score += 0.4
        if sma50 > sma200:
            trend_score += 0.3

        # 3. Volume Breakout (Vol so với SMA20 Volume)
        v = float(latest.get("volume", 0))
        sma_vol = float(vol_series.tail(20).mean()) if len(vol_series) >= 20 else (v or 1.0)
        vol_ratio = (v / sma_vol) if sma_vol > 0 else 1.0
        vol_score = min(2.0, max(0.0, (vol_ratio - 1.0) / 1.0)) # 1.0 -> 0.0, 2.0x -> 1.0

        # 4. Relative Strength (RS Rating)
        rs_rating = float(latest.get("rs_rating", 50.0))
        rs_score = np.clip(rs_rating / 100.0, 0.0, 1.0)

        # 5. Low Volatility (Nghịch đảo biến động)
        ret20 = close_series.pct_change().tail(20).dropna()
        volatility = float(ret20.std() * np.sqrt(252)) if len(ret20) >= 5 else 0.30
        low_vol_score = np.clip(1.0 - (volatility / 0.60), 0.0, 1.0)

        # 6. Mean Reversion (RSI quá bán phục hồi)
        rsi = float(latest.get("rsi", 50.0))
        if rsi < 35.0:
            mr_score = 1.0
        elif rsi < 50.0:
            mr_score = (50.0 - rsi) / 15.0
        else:
            mr_score = 0.0

        # 7. Drawdown Recovery (Khoảng cách tới đỉnh 60 phiên)
        high60 = float(hist["high"].tail(60).max()) if "high" in hist and len(hist) >= 60 else c
        dd60 = (c / high60 - 1.0) if high60 > 0 else 0.0
        dd_score = np.clip(1.0 + dd60, 0.0, 1.0)

        # ---------------------------------------------------------------------
        # Tổng hợp điểm số qua Genome
        # ---------------------------------------------------------------------
        g = self.genome
        score = (
            g.get("w_momentum_20d", 0) * np.clip(mom20 * 5.0, -1.0, 1.0) +
            g.get("w_momentum_60d", 0) * np.clip(mom60 * 2.5, -1.0, 1.0) +
            g.get("w_trend_alignment", 0) * (trend_score * 2.0 - 1.0) +
            g.get("w_vol_breakout", 0) * (vol_score * 2.0 - 1.0) +
            g.get("w_relative_strength", 0) * (rs_score * 2.0 - 1.0) +
            g.get("w_low_volatility", 0) * (low_vol_score * 2.0 - 1.0) +
            g.get("w_mean_reversion", 0) * (mr_score * 2.0 - 1.0) +
            g.get("w_drawdown_recovery", 0) * (dd_score * 2.0 - 1.0)
        )
        return float(score)
