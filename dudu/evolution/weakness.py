"""Hệ thống Khám Nghiệm Tử Thi Sai Lầm & Chẩn Đoán Điểm Yếu (Forensic Weakness Autopsy).

Kế thừa từ vn-stock-ai-advisors:
Chẩn đoán các lỗ hổng vận hành và thống kê của các chiến lược/chuyên gia AI:
- Sụt giảm sâu (Fatal Drawdowns > -22%)
- Bào mòn chi phí giao dịch quá mức (High Turnover > 25x/năm)
- Bẫy bứt phá giả (False Breakout Traps)
- Bắt dao rơi ngược xu hướng (Falling Knives)
- Tỷ lệ Lời/Lỗ bất đối xứng (Profit Factor < 1.10)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


@dataclass
class WeaknessReport:
    advisor_name: str
    primary_flaws: List[str]
    root_cause_diagnosis: str
    remedy_recommendations: List[str]
    penalize_factors: List[str]
    boost_factors: List[str]
    metrics_summary: Dict[str, float]


class WeaknessAnalyzer:
    """Khám nghiệm chuyên sâu các chuyên gia AI hoạt động kém hiệu quả."""

    def analyze(self, metrics: Dict[str, Any], advisor_name: str = "Candidate_Advisor") -> WeaknessReport:
        flaws: List[str] = []
        penalize: List[str] = []
        boost: List[str] = []
        remedies: List[str] = []

        mdd = float(metrics.get("max_drawdown_pct", metrics.get("max_drawdown", 0.0)))
        if mdd > 0: # trường hợp mdd được ghi dưới dạng số dương
            mdd = -mdd

        cagr = float(metrics.get("cagr_pct", metrics.get("cagr", 0.0)))
        alpha = float(metrics.get("alpha_annual_pct", metrics.get("alpha", 0.0)))
        win_rate = float(metrics.get("win_rate_pct", metrics.get("win_rate", 0.0)))
        profit_factor = float(metrics.get("profit_factor", 1.0))
        turnover = float(metrics.get("turnover_per_year", metrics.get("turnover", 10.0)))
        cost_drag = float(metrics.get("annual_cost_drag_pct", 1.5))

        # 1. Kiểm tra Mức Sụt Giảm Tài Sản (Drawdown)
        if mdd < -22.0:
            flaws.append(f"Mức sụt giảm tối đa nghiêm trọng (MDD: {mdd:.1f}% > -22%)")
            penalize.extend(["w_mean_reversion", "w_momentum_20d"])
            boost.extend(["w_low_volatility", "w_trend_alignment"])
            remedies.append("Tăng cường tỷ trọng Biến động thấp (Low Volatility) và bảo vệ vốn khi gãy MA50.")

        # 2. Kiểm tra Vòng Quay Vốn & Bào Mòn Phí Giao Dịch
        if turnover > 25.0 or cost_drag > 2.5:
            flaws.append(f"Giao dịch quá mức bào mòn lợi nhuận (Vòng quay: {turnover:.1f}x/năm, Phí: {cost_drag:.2f}%)")
            remedies.append("Kéo dài chu kỳ tái cấu trúc (từ 2W sang 1M hoặc 3M) để tối ưu chi phí thuế phí.")

        # 3. Kiểm tra Tỷ Lệ Thắng & Hệ Số Lời/Lỗ
        if win_rate < 42.0:
            flaws.append(f"Tỷ lệ thắng thấp (Win Rate: {win_rate:.1f}% < 42%)")
            boost.append("w_relative_strength")
            remedies.append("Siết chặt bộ lọc Sức mạnh giá tương đối (RS Rating > 75) trước khi giải ngân.")

        if profit_factor < 1.10:
            flaws.append(f"Hệ số Lời/Lỗ kém hiệu quả (Profit Factor: {profit_factor:.2f} < 1.10)")
            remedies.append("Áp dụng quy tắc cắt lỗ chủ động -7% và kéo trailing stop theo đáy Donchian.")

        # 4. Kiểm tra Alpha Âm so với Chỉ Số
        if alpha < 0.0:
            flaws.append(f"Hiệu suất thua kém VN-Index (Alpha âm: {alpha:.1f}%/năm)")
            penalize.append("w_mean_reversion")
            boost.extend(["w_trend_alignment", "w_momentum_60d"])
            remedies.append("Loại bỏ chiến lược bắt dao rơi ngược xu hướng, tập trung vào dòng tiền dẫn dắt.")

        if not flaws:
            flaws.append("Hiệu suất trung bình, chưa bộc lộ ưu thế Alpha vượt trội so với thị trường.")
            remedies.append("Tối ưu hóa lại ma trận trọng số nhân tố và ngưỡng cắt lỗ biến thiên ATR.")

        root_cause = f"Chẩn đoán cho {advisor_name}: " + "; ".join(flaws)

        return WeaknessReport(
            advisor_name=advisor_name,
            primary_flaws=flaws,
            root_cause_diagnosis=root_cause,
            remedy_recommendations=remedies,
            penalize_factors=list(set(penalize)),
            boost_factors=list(set(boost)),
            metrics_summary={
                "mdd": mdd,
                "cagr": cagr,
                "alpha": alpha,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "turnover": turnover,
            },
        )
