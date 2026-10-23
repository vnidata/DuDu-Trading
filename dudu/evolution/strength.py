"""Bóc Tách Nhân Tố Thành Công Của Chuyên Gia Dẫn Đầu (Strength Extractor).

Kế thừa từ vn-stock-ai-advisors:
Phân tích các chuyên gia có Alpha và Sharpe cao nhất để trích xuất các gene ưu tú:
- Động lực sinh lời vượt bậc (Alpha > 15%, CAGR > 15%)
- Tỷ lệ Sharpe & Calmar vượt trội
- Khả năng kiểm soát sụt giảm tài sản (MDD <= -22%)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class StrengthProfile:
    advisor_name: str
    dominant_strengths: List[str]
    winning_genome_factors: Dict[str, float]
    proven_rebalance_days: int
    proven_allocation_method: str
    sharpe_ratio: float
    cagr_pct: float
    alpha_pct: float


class StrengthExtractor:
    """Bóc tách các gen chiến lược thành công từ chuyên gia AI đạt thứ hạng cao."""

    def extract(self, advisor_obj: Any, metrics: Dict[str, Any]) -> StrengthProfile:
        strengths: List[str] = []

        alpha = float(metrics.get("alpha_annual_pct", metrics.get("alpha", 0.0)))
        sharpe = float(metrics.get("sharpe_ratio", metrics.get("sharpe", 0.0)))
        mdd = float(metrics.get("max_drawdown_pct", metrics.get("max_drawdown", 0.0)))
        if mdd > 0:
            mdd = -mdd
        win_rate = float(metrics.get("win_rate_pct", metrics.get("win_rate", 0.0)))
        profit_factor = float(metrics.get("profit_factor", 1.0))
        cagr = float(metrics.get("cagr_pct", metrics.get("cagr", 0.0)))

        if alpha > 15.0:
            strengths.append(f"Sinh Alpha xuất sắc (+{alpha:.1f}%/năm vượt VN-Index)")
        if sharpe > 1.0:
            strengths.append(f"Hiệu quả bù đắp rủi ro cao (Sharpe: {sharpe:.2f})")
        if abs(mdd) <= 22.0:
            strengths.append(f"Kiểm soát sụt giảm vốn đỉnh cao (MDD chỉ {mdd:.1f}%)")
        if win_rate >= 50.0:
            strengths.append(f"Xác suất sinh lời tin cậy (Win Rate: {win_rate:.1f}%)")
        if profit_factor >= 1.50:
            strengths.append(f"Tỷ lệ Lời/Lỗ lý tưởng (Profit Factor: {profit_factor:.2f})")

        if not strengths:
            strengths.append("Duy trì tăng trưởng ổn định và quản trị vốn kỷ luật.")

        genome = getattr(advisor_obj, "genome", {})
        sorted_genome = sorted(genome.items(), key=lambda x: x[1], reverse=True)
        top_factors = dict(sorted_genome[:4])

        return StrengthProfile(
            advisor_name=getattr(advisor_obj, "name", "Top_Advisor"),
            dominant_strengths=strengths,
            winning_genome_factors=top_factors,
            proven_rebalance_days=getattr(advisor_obj, "rebalance_days", 21),
            proven_allocation_method=str(getattr(advisor_obj, "allocation_method", "Equal Weight")),
            sharpe_ratio=sharpe,
            cagr_pct=cagr,
            alpha_pct=alpha,
        )
