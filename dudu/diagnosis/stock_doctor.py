"""Bộ Máy Chẩn Đoán Sức Khỏe Toàn Diện Cổ Phiếu (Stock Health Diagnosis Doctor).

Kế thừa từ vn-stock-ai-advisors:
Cung cấp góc nhìn 360 độ về một mã cổ phiếu:
- Sức mạnh giá tương đối (RS Rating 1-99 vs VN-Index)
- Cấu trúc xu hướng đa khung thời gian (SMA20 / SMA50 / SMA200)
- Động lượng RSI & Dòng tiền bùng nổ (Volume Flow vs SMA20 Vol)
- Vị trí trong Kênh Donchian 55 phiên
- Điểm số và Khuyến nghị chi tiết từ 6 Chuyên Gia AI
- Kết luận chẩn đoán (Health Verdict & Actionable Advice)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from dudu.advisors.council import AdvisorCouncil
from dudu.advisors.pullback import detect_pullback_setup


@dataclass
class StockDiagnosisReport:
    symbol: str
    price: float
    change_pct: float
    rs_rating: float
    trend_state: str
    rsi_14: float
    volume_surge_ratio: float
    donchian_dist_high: float
    donchian_dist_low: float
    advisor_opinions: Dict[str, float]
    consensus_score: float
    health_verdict: str
    recommendation: str
    strengths: List[str]
    warnings: List[str]


class StockDoctor:
    """Bác sĩ định lượng khám sức khỏe cổ phiếu 1-click."""

    def __init__(self, council: Optional[AdvisorCouncil] = None):
        self.council = council or AdvisorCouncil()

    def diagnose(
        self,
        symbol: str,
        df: pd.DataFrame,
        benchmark_df: Optional[pd.DataFrame] = None,
    ) -> StockDiagnosisReport:
        if df is None or len(df) < 20:
            raise ValueError(f"Không đủ dữ liệu để chẩn đoán cho mã {symbol}")

        c = float(df["close"].iloc[-1])
        prev_c = float(df["close"].iloc[-2]) if len(df) >= 2 else c
        chg = (c / prev_c - 1.0) if prev_c > 0 else 0.0

        # 1. Tính toán Xu Hướng SMA
        sma20 = float(df["close"].tail(20).mean())
        sma50 = float(df["close"].tail(50).mean()) if len(df) >= 50 else sma20
        sma200 = float(df["close"].tail(200).mean()) if len(df) >= 200 else sma50

        if c > sma20 and sma20 > sma50 and sma50 > sma200:
            trend_state = "Uptrend Hoàn Hảo (Bullish Alignment)"
        elif c > sma50:
            trend_state = "Xu Hướng Tăng Trung Hạn (Trên SMA50)"
        elif c < sma50 and c < sma20:
            trend_state = "Downtrend Nguy Hiểm (Dưới SMA20 & SMA50)"
        else:
            trend_state = "Tích Lũy / Đi Ngang (Sideway)"

        # 2. RSI (14)
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).tail(14).mean()
        loss = (-delta.where(delta < 0, 0)).tail(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = float(100.0 - (100.0 / (1.0 + rs)))

        # 3. Khối lượng & Dòng tiền
        v = float(df["volume"].iloc[-1])
        vol_sma20 = float(df["volume"].tail(20).mean()) if len(df) >= 20 else v
        vol_surge = (v / vol_sma20) if vol_sma20 > 0 else 1.0

        # 4. Kênh Donchian (55 high, 20 low)
        h55 = float(df["high"].tail(55).max()) if "high" in df and len(df) >= 55 else c
        l20 = float(df["low"].tail(20).min()) if "low" in df and len(df) >= 20 else c
        dist_h55 = (c / h55 - 1.0) * 100.0 if h55 > 0 else 0.0
        dist_l20 = (c / l20 - 1.0) * 100.0 if l20 > 0 else 0.0

        # 5. RS Rating
        rs_rating = float(df.iloc[-1].get("rs_rating", 50.0))

        # 6. Đánh giá từ Hội Đồng AI
        opinions: Dict[str, float] = {}
        for adv in self.council.advisors:
            s = adv.score_symbol(symbol, df, benchmark_df=benchmark_df)
            opinions[adv.name] = round(s, 3)

        valid_scores = [s for s in opinions.values() if s > -900]
        consensus = float(np.mean(valid_scores)) if valid_scores else -1.0

        # 7. Tổng hợp ưu điểm & cảnh báo
        strengths: List[str] = []
        warnings: List[str] = []

        if rs_rating >= 80.0:
            strengths.append(f"Sức mạnh giá RS vượt trội ({rs_rating:.0f}/100) — Top 20% thị trường")
        if vol_surge >= 1.50:
            strengths.append(f"Dòng tiền bùng nổ mạnh mẽ (Vol gấp {vol_surge:.1f}x trung bình 20 phiên)")
        if c > sma50 and sma20 > sma50:
            strengths.append("Cấu trúc xu hướng tăng giá vững chắc")
        if dist_h55 >= -1.0:
            strengths.append("Đang áp sát hoặc vượt đỉnh 55 phiên (Chuẩn Donchian S2)")

        # Kiểm tra mẫu hình Kéo ngược (Pullback Retest)
        pullback_check = detect_pullback_setup(df)
        if pullback_check.get("is_pullback"):
            strengths.append(f"Mẫu hình Kéo ngược (Pullback) lý tưởng: {pullback_check.get('reason')}")

        if c < sma50:
            warnings.append("Giá nằm dưới đường SMA50 phiên — rủi ro suy yếu xu hướng")
        if rsi >= 75.0:
            warnings.append(f"Động lượng RSI quá mua ({rsi:.1f}) — cảnh giác nhịp rung lắc ngắn hạn")
        elif rsi <= 30.0:
            warnings.append(f"RSI đi vào vùng quá bán ({rsi:.1f}) — đang chịu áp lực giải chấp")
        if dist_l20 <= 2.0:
            warnings.append("Rất gần đáy 20 phiên — nguy cơ kích hoạt dừng lỗ Trailing Stop")

        # 8. Kết luận chẩn đoán (Health Verdict)
        if consensus >= 0.25 and not (c < sma50):
            verdict = "XUẤT SẮC"
            recom = "MUA MẠNH / NẮM GIỮ TỶ TRỌNG CAO"
        elif consensus >= 0.10:
            verdict = "TÍCH CỰC"
            recom = "MUA TÍCH LŨY HOẶC TIẾP TỤC NẮM GIỮ"
        elif consensus >= -0.10:
            verdict = "TRUNG LẬP"
            recom = "QUAN SÁT THẬN TRỌNG, CHỜ ĐỢI TÍN HIỆU ĐỘT PHÁ"
        else:
            verdict = "TIÊU CỰC"
            recom = "HẠ TỶ TRỌNG / CẮT LỖ BẢO TOÀN VỐN"

        return StockDiagnosisReport(
            symbol=symbol,
            price=c,
            change_pct=chg,
            rs_rating=rs_rating,
            trend_state=trend_state,
            rsi_14=round(rsi, 1),
            volume_surge_ratio=round(vol_surge, 2),
            donchian_dist_high=round(dist_h55, 2),
            donchian_dist_low=round(dist_l20, 2),
            advisor_opinions=opinions,
            consensus_score=round(consensus, 3),
            health_verdict=verdict,
            recommendation=recom,
            strengths=strengths,
            warnings=warnings,
        )
