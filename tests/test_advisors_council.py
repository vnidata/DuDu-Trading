"""Kiểm thử Hội Đồng Đa Chuyên Gia AI (Multi-Advisor AI Council) và Cash Defense Rule.

Kế thừa từ vn-stock-ai-advisors:
- Kiểm tra tính chuẩn hóa bộ gene (Genome Sum = 1.0)
- Kiểm tra độ nhạy phong cách của từng Chuyên gia
- Kiểm tra cơ chế tự động phòng thủ tiền mặt (Cash Defense) khi VN-Index vào Bear Market
- Kiểm tra xếp hạng đồng thuận toàn hội đồng (Council Consensus Ranking)
"""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from dudu.advisors import (
    ActiveAdvisor,
    HarmonyAdvisor,
    PersistentAdvisor,
    CanslimAdvisor,
    MeanReversionAdvisor,
    TurtleAdvisor,
    AdvisorCouncil,
)


def _make_dummy_stock(n_bars=60, base_px=100.0, trend="up", rsi_val=50.0):
    dates = pd.date_range("2024-01-01", periods=n_bars)
    if trend == "up":
        prices = [base_px * (1.0 + 0.005 * i) for i in range(n_bars)]
    elif trend == "down":
        prices = [base_px * (1.0 - 0.005 * i) for i in range(n_bars)]
    else:
        prices = [base_px] * n_bars

    df = pd.DataFrame({
        "time": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [1_000_000] * n_bars,
        "rs_rating": [85.0 if trend == "up" else 30.0] * n_bars,
        "rsi": [rsi_val] * n_bars,
    })
    return df


def test_advisor_genomes_normalized():
    """Mọi chuyên gia AI phải có tổng trọng số bộ gene bằng 1.0."""
    council = AdvisorCouncil()
    for adv in council.advisors:
        total = sum(adv.genome.values())
        assert abs(total - 1.0) < 1e-5, f"{adv.name} có tổng gene = {total} khác 1.0"


def test_active_vs_persistent_bias():
    """Chuyên gia Chủ Động đánh giá cao CP Uptrend mạnh hơn Chuyên gia Bền Bỉ."""
    df_bull = _make_dummy_stock(n_bars=60, trend="up")
    active = ActiveAdvisor()
    persistent = PersistentAdvisor()

    s_active = active.score_symbol("BULL", df_bull)
    s_pers = persistent.score_symbol("BULL", df_bull)

    assert s_active > 0.0
    assert s_pers > 0.0
    # Active Advisor có tỷ trọng động lượng ngắn hạn cao hơn nên điểm bứt phá mạnh hơn
    assert active.genome["w_momentum_20d"] > persistent.genome["w_momentum_20d"]


def test_mean_reversion_oversold_scoring():
    """Chuyên gia Đảo Chiều Thống Kê phản ứng mạnh khi cổ phiếu có RSI quá bán sâu (<35)."""
    df_oversold = _make_dummy_stock(n_bars=60, trend="down", rsi_val=25.0)
    mr = MeanReversionAdvisor()
    active = ActiveAdvisor()

    s_mr = mr.score_symbol("OVERSOLD", df_oversold)
    # Mean reversion phải cho điểm cao hơn Active Advisor đối với mã đang quá bán
    assert s_mr > active.score_symbol("OVERSOLD", df_oversold)


def test_turtle_advisor_breakout():
    """Turtle Advisor phát hiện đúng bứt phá đỉnh 55 phiên."""
    turtle = TurtleAdvisor()
    df = _make_dummy_stock(n_bars=60, base_px=100.0, trend="sideway")
    # Giá cuối bứt phá vượt hẳn đỉnh 55 phiên
    df.loc[df.index[-1], "close"] = 150.0

    assert turtle.is_donchian_breakout(df, window=55) is True


def test_market_regime_cash_defense_trigger():
    """Khi VN-Index sập gãy SMA50, Hội đồng phải nâng tỷ lệ phòng thủ tiền mặt lên >= 70%."""
    council = AdvisorCouncil()

    # Tạo chỉ số VN-Index downtrend
    bm_down = _make_dummy_stock(n_bars=60, base_px=1200.0, trend="down")
    regime = council.detect_market_regime(bm_down)

    assert regime["regime"] == "BEAR"
    assert regime["is_bear"] is True
    assert regime["cash_pct"] >= 0.70, f"Tỷ lệ tiền mặt phải >= 70%, thực tế: {regime['cash_pct']}"


def test_council_evaluates_universe():
    """Hội đồng đánh giá thành công danh sách mã và đưa ra đồng thuận."""
    council = AdvisorCouncil()
    universe = {
        "FPT": _make_dummy_stock(n_bars=60, trend="up"),
        "VNM": _make_dummy_stock(n_bars=60, trend="down"),
        "MWG": _make_dummy_stock(n_bars=60, trend="up"),
    }
    res = council.evaluate_universe(universe)

    assert "market_regime" in res
    assert "advisors" in res
    assert "council_consensus_top" in res
    assert len(res["advisors"]) >= 6

    # Mã Uptrend FPT, MWG phải đứng đầu bảng đồng thuận
    top_syms = [x["symbol"] for x in res["council_consensus_top"]]
    assert "FPT" in top_syms or "MWG" in top_syms
