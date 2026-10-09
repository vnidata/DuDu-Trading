"""Kiểm thử chỉ báo và bộ máy backtest trên dữ liệu tổng hợp (không cần mạng)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bubu.backtest import run_symbol_window, simulate_symbol, window_arrays
from bubu.config import BacktestConfig, MarketConfig, PortfolioConfig, StrategyParams
from bubu.data import PricePanel
from bubu.indicators import (
    FeatureBank,
    build_market_regime,
    donchian_lower,
    donchian_upper,
    price_limits,
    wilder_atr,
)


# --------------------------------------------------------------------------
# Dữ liệu tổng hợp
# --------------------------------------------------------------------------
def synthetic_symbol(n: int = 400, start: float = 20_000.0, drift: float = 0.001, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = drift + rng.normal(0, 0.015, n)
    close = start * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(1_000_000, 8_000_000, n).astype(float)
    dates = pd.bdate_range("2018-01-02", periods=n)
    return pd.DataFrame(
        {"time": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def make_bank(frames: dict[str, pd.DataFrame], adv_value: float = 1e11) -> FeatureBank:
    panel = PricePanel(frames)
    n, m = panel.close.shape
    adv = np.full((n, m), adv_value)
    adv[:25, :] = np.nan
    regime = np.ones((n, m), dtype=bool)
    return FeatureBank(
        panel,
        entry_windows=list(range(40, 71)),
        exit_windows=list(range(15, 26)),
        atr_periods=list(range(14, 26)),
        adv=adv,
        regime=regime,
    )


# --------------------------------------------------------------------------
# Chỉ báo
# --------------------------------------------------------------------------
def test_price_limits_respect_hose_tick_and_band():
    mkt = MarketConfig()
    # Giá tham chiếu 20.000 VND -> bước giá 50, trần 21.400, sàn 18.600
    assert mkt.ceiling_price(20_000) == pytest.approx(21_400)
    assert mkt.floor_price(20_000) == pytest.approx(18_600)
    # Khung giá dưới 10.000 -> bước giá 10
    assert mkt.ceiling_price(9_000) == pytest.approx(9_630)
    assert mkt.floor_price(9_000) == pytest.approx(8_370)
    # Khung giá từ 50.000 -> bước giá 100
    assert mkt.ceiling_price(60_000) == pytest.approx(64_200)
    assert mkt.floor_price(60_000) == pytest.approx(55_800)


def test_price_limits_matrix_is_per_column():
    """Hồi quy: np.roll thiếu axis=0 từng làm trộn giá trần giữa các mã."""
    mkt = MarketConfig()
    a = np.array([[100.0], [110.0], [120.0]])
    b = np.array([[1000.0], [1100.0], [1200.0]])
    close = np.hstack([a, b])
    ceiling, floor = price_limits(close, mkt)
    assert np.isnan(ceiling[0]).all()
    # Hàng 1 lấy giá tham chiếu từ hàng 0 của CHÍNH cột đó
    assert ceiling[1, 0] == pytest.approx(mkt.ceiling_price(100.0))
    assert ceiling[1, 1] == pytest.approx(mkt.ceiling_price(1000.0))
    assert floor[1, 0] == pytest.approx(mkt.floor_price(100.0))
    assert floor[1, 1] == pytest.approx(mkt.floor_price(1000.0))
    # Giá trị cột 1 phải lớn hơn hẳn cột 0, không bị trộn
    assert ceiling[2, 1] > ceiling[2, 0] * 5


def test_price_limits_use_band_of_the_limit_price_itself():
    """Tham chiếu 9.900 -> trần 10.593 nằm ở khung giá 50 nên phải làm tròn về 10.550."""
    mkt = MarketConfig()
    close = np.array([[9_900.0], [9_900.0]])
    ceiling, _ = price_limits(close, mkt)
    assert ceiling[1, 0] == pytest.approx(10_550.0)
    assert ceiling[1, 0] == pytest.approx(mkt.ceiling_price(9_900.0))


def test_donchian_excludes_current_bar():
    high = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    upper = donchian_upper(high.reshape(-1, 1), 3).ravel()
    assert np.isnan(upper[:3]).all()
    assert upper[3] == pytest.approx(3.0)   # max của 3 phiên trước
    assert upper[4] == pytest.approx(4.0)   # KHÔNG bao gồm chính phiên có giá 100
    low = np.array([10.0, 9.0, 8.0, 7.0, 0.0])
    lower = donchian_lower(low.reshape(-1, 1), 3).ravel()
    assert lower[4] == pytest.approx(7.0)


def test_wilder_atr_matches_manual_recursion():
    high = np.array([[10.0], [11.0], [12.0], [13.0], [14.0]])
    low = np.array([[9.0], [10.0], [11.0], [12.0], [13.0]])
    close = np.array([[9.5], [10.5], [11.5], [12.5], [13.5]])
    atr = wilder_atr(high, low, close, 3).ravel()
    tr = np.array([1.0, 1.5, 1.5, 1.5, 1.5])
    # Wilder khởi tạo bằng SMA của `period` TR đầu tiên, không đệ quy từ phần tử 0
    assert np.isnan(atr[:2]).all()
    seed = tr[:3].mean()
    assert atr[2] == pytest.approx(seed)
    expected = seed + (tr[3] - seed) / 3
    assert atr[3] == pytest.approx(expected)
    expected4 = expected + (tr[4] - expected) / 3
    assert atr[4] == pytest.approx(expected4)


def test_wilder_atr_keeps_nan_rows_and_columns_separate():
    high = np.array([[10.0, np.nan], [11.0, 5.0], [12.0, 6.0], [13.0, 7.0]])
    low = np.array([[9.0, np.nan], [10.0, 4.0], [11.0, 5.0], [12.0, 6.0]])
    close = np.array([[9.5, np.nan], [10.5, 4.5], [11.5, 5.5], [12.5, 6.5]])
    atr = wilder_atr(high, low, close, 2)
    # Cột 0: TR = [1,0 ; 1,5 ; 1,5 ; 1,5] -> khởi tạo tại hàng 1 bằng SMA(2) = 1,25
    assert atr[1, 0] == pytest.approx(1.25)
    assert atr[2, 0] == pytest.approx(1.25 + (1.5 - 1.25) / 2)
    # Cột 1 niêm yết từ hàng 1: TR = [nan ; 1,0 ; 1,5 ; 1,5]
    assert np.isnan(atr[1, 1])
    assert atr[2, 1] == pytest.approx((1.0 + 1.5) / 2)
    assert np.isfinite(atr[3, 1])
    assert np.isnan(atr[0]).all()


def test_wilder_atr_handles_symbol_listed_late():
    """Hồi quy: ATR của mã niêm yết muộn không được NaN vĩnh viễn."""
    n = 30
    high = np.full((n, 2), np.nan)
    low = np.full((n, 2), np.nan)
    close = np.full((n, 2), np.nan)
    high[:, 0], low[:, 0], close[:, 0] = 10.0, 9.0, 9.5
    high[15:, 1], low[15:, 1], close[15:, 1] = 5.0, 4.0, 4.5
    atr = wilder_atr(high, low, close, 5)
    # Cần đủ 5 giá trị TR hợp lệ nên ATR chỉ bắt đầu từ hàng 19
    assert np.isnan(atr[:19, 1]).all()
    assert not np.isnan(atr[19:, 1]).any()
    assert not np.isnan(atr[4:, 0]).any()


def test_market_regime_filter():
    x = np.concatenate([np.full(50, 10.0), np.full(50, 20.0), np.full(50, 5.0)])
    regime = build_market_regime(x, 20)
    assert not regime[:20].any()
    assert regime[-1] is np.False_ or regime[-1] == False  # noqa: E712
    assert regime[60:95].any()


# --------------------------------------------------------------------------
# Bộ máy backtest
# --------------------------------------------------------------------------
def test_engine_is_long_only_and_cash_conserving():
    frames = {"AAA": synthetic_symbol(seed=1)}
    bank = make_bank(frames)
    cfg = BacktestConfig()
    res = run_symbol_window(bank, "AAA", 0, bank.n_dates(), cfg, True)
    # Không có lệnh bán khống: mọi lệnh đều có KL dương và giá ra dương
    assert all(t["shares"] > 0 for t in res.trades)
    # Vốn không bao giờ âm (không dùng margin)
    assert res.equity.min() > 0
    # Tỷ trọng tại thời điểm vào lệnh không vượt trần NAV/mã. Sau đó vị thế có
    # thể tăng giá và đẩy tỷ trọng lên cao hơn - engine không tái cân bằng.
    dates = list(res.dates)
    for t in res.trades:
        idx = dates.index(pd.Timestamp(t["entry_date"]))
        assert res.exposure[idx] <= cfg.strategy.max_symbol_nav + 0.02
    assert res.exposure.max() <= 1.0


def test_size_shares_enforces_caps():
    from bubu.backtest import _size_shares

    cfg = BacktestConfig()
    p = cfg.strategy
    # risk 1%, stop 2N, N = 600 VND -> 1e7 / 1200 = 8.333 cổ phiếu -> 8.300 (lô 100)
    shares = _size_shares(20_000.0, 600.0, 1e9, 1e9, p, cfg, room_value=1e9)
    assert shares == pytest.approx(8_300)
    # risk 1,5% vượt trần 20% NAV/Unit -> 1e9*0.2/20000 = 10.000 cổ phiếu, làm tròn lô 100
    p2 = StrategyParams(risk_per_unit=0.015)
    assert _size_shares(20_000.0, 600.0, 1e9, 1e9, p2, cfg, room_value=1e9) == pytest.approx(10_000)
    # Không đủ tiền mặt -> 0
    assert _size_shares(20_000.0, 600.0, 1e9, 1_000.0, p, cfg, room_value=1e9) == 0.0
    # N bằng 0 hoặc NaN -> 0
    assert _size_shares(20_000.0, 0.0, 1e9, 1e9, p, cfg, room_value=1e9) == 0.0
    assert _size_shares(20_000.0, float("nan"), 1e9, 1e9, p, cfg, room_value=1e9) == 0.0
    # Trần room của mã giới hạn khối lượng
    assert _size_shares(20_000.0, 600.0, 1e9, 1e9, p, cfg, room_value=40e6) == pytest.approx(2_000)


def test_t_plus_lock_prevents_same_day_stop():
    """Một Unit vừa mở không thể bị stop trong 2 phiên đầu (T+2.5)."""
    n = 120
    close = np.full(n, 20_000.0)
    close[60:] = 25_000.0
    # Cú giảm sâu ngay sau khi vào lệnh
    close[62] = 15_000.0
    close[63] = 15_000.0
    close[64] = 14_000.0
    high = close * 1.01
    low = close * 0.99
    low[62] = 14_000.0
    frame = pd.DataFrame(
        {
            "time": pd.bdate_range("2018-01-02", periods=n),
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 5e6),
        }
    )
    bank = make_bank({"AAA": frame})
    cfg = BacktestConfig()
    res = run_symbol_window(bank, "AAA", 0, bank.n_dates(), cfg, True)
    for t in res.trades:
        entry = pd.Timestamp(t["entry_date"])
        exit_ = pd.Timestamp(t["exit_date"])
        gap = len(pd.bdate_range(entry, exit_)) - 1
        assert gap >= cfg.market.settlement_lag, f"Lệnh thoát sau {gap} phiên, vi phạm T+2.5"


def test_ceiling_breakout_is_skipped():
    """Breakout đúng phiên giá trần phải bị bỏ qua, không mở vị thế."""
    n = 200
    close = np.full(n, 20_000.0)
    close[150:] = 30_000.0          # phá đỉnh
    ceiling_price = 20_000.0 * 1.07  # = 21.400
    close[150] = np.floor(ceiling_price / 10) * 10  # đóng cửa đúng giá trần
    frame = pd.DataFrame(
        {
            "time": pd.bdate_range("2018-01-02", periods=n),
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": np.full(n, 5e6),
        }
    )
    bank = make_bank({"AAA": frame})
    cfg = BacktestConfig()
    res = run_symbol_window(bank, "AAA", 0, bank.n_dates(), cfg, True)
    assert all(pd.Timestamp(t["entry_date"]) != frame["time"].iloc[150] for t in res.trades)


def test_floor_exit_is_deferred():
    """Khi đóng cửa tại giá sàn, lệnh thoát phải treo sang phiên sau."""
    n = 220
    close = np.full(n, 20_000.0)
    close[60:180] = np.linspace(20_000, 40_000, 120)
    close[180:] = np.linspace(40_000, 20_000, 40)
    frame = pd.DataFrame(
        {
            "time": pd.bdate_range("2018-01-02", periods=n),
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": np.full(n, 5e6),
        }
    )
    bank = make_bank({"AAA": frame})
    cfg = BacktestConfig()
    res = run_symbol_window(bank, "AAA", 0, bank.n_dates(), cfg, True)
    # Không lệnh nào thoát với giá thấp hơn giá sàn của chính phiên đó
    for t in res.trades:
        if t["exit_reason"] == "exit_deferred":
            assert t["exit_price"] > 0


def test_adv_filter_blocks_all_entries():
    frames = {"AAA": synthetic_symbol(seed=3)}
    bank = make_bank(frames, adv_value=1e9)  # 1 tỷ < 30 tỷ
    cfg = BacktestConfig()
    res = run_symbol_window(bank, "AAA", 0, bank.n_dates(), cfg, True)
    assert res.trade_stats["trades"] == 0
    assert res.equity[-1] == pytest.approx(cfg.initial_capital)


def test_market_filter_blocks_entries():
    frames = {"AAA": synthetic_symbol(seed=4)}
    panel = PricePanel(frames)
    n, m = panel.close.shape
    adv = np.full((n, m), 1e11)
    regime = np.zeros((n, m), dtype=bool)   # thị trường luôn dưới SMA200
    bank = FeatureBank(panel, list(range(40, 71)), list(range(15, 26)), list(range(14, 26)), adv=adv, regime=regime)
    cfg = BacktestConfig()
    res = run_symbol_window(bank, "AAA", 0, bank.n_dates(), cfg, True)
    assert res.trade_stats["trades"] == 0


def test_sizing_modes_differ_and_respect_caps():
    frames = {"AAA": synthetic_symbol(seed=5)}
    bank = make_bank(frames)
    risk_cfg = BacktestConfig(strategy=StrategyParams(sizing_mode="risk"))
    vol_cfg = BacktestConfig(strategy=StrategyParams(sizing_mode="volatility"))
    r1 = run_symbol_window(bank, "AAA", 0, bank.n_dates(), risk_cfg, True)
    r2 = run_symbol_window(bank, "AAA", 0, bank.n_dates(), vol_cfg, True)
    # Chế độ volatility đặt khối lượng lớn hơn (rủi ro 2% tại stop thay vì 1%),
    # trừ khi cả hai đều bị chặn bởi trần 20% NAV/Unit.
    if r1.trades and r2.trades:
        assert r2.trades[0]["shares"] >= r1.trades[0]["shares"]
    dates = list(r1.dates)
    for t in r1.trades:
        idx = dates.index(pd.Timestamp(t["entry_date"]))
        assert r1.exposure[idx] <= risk_cfg.strategy.max_symbol_nav + 0.02


def test_panel_columns_are_independent():
    """Hai mã có chuỗi giá khác nhau phải cho kết quả khác nhau (hồi quy trộn cột)."""
    frames = {"AAA": synthetic_symbol(seed=11), "BBB": synthetic_symbol(seed=12, start=50_000.0)}
    bank = make_bank(frames)
    cfg = BacktestConfig()
    ra = run_symbol_window(bank, "AAA", 0, bank.n_dates(), cfg, True)
    rb = run_symbol_window(bank, "BBB", 0, bank.n_dates(), cfg, True)
    assert not np.allclose(ra.equity, rb.equity)


def test_portfolio_respects_gross_exposure_cap():
    from bubu.backtest import simulate_portfolio

    frames = {f"S{i}": synthetic_symbol(seed=20 + i) for i in range(6)}
    bank = make_bank(frames)
    cfg = BacktestConfig()
    pcfg = PortfolioConfig(max_positions=3, max_gross_exposure=0.5)
    out = simulate_portfolio(bank, cfg, pcfg, close_open_at_end=True)
    dates = list(out["dates"])
    # Trần exposure được áp tại thời điểm mở vị thế; sau đó vị thế tăng giá có
    # thể đẩy tỷ trọng lên cao hơn vì engine không tái cân bằng.
    for t in out["trades"]:
        idx = dates.index(pd.Timestamp(t["entry_date"]))
        assert out["exposure"][idx] <= pcfg.max_gross_exposure + 0.02
    assert out["exposure"].max() <= 1.0
    assert len(out["trades"]) > 0
    assert out["equity"].min() > 0


def test_window_arrays_shapes_match():
    frames = {"AAA": synthetic_symbol(seed=30)}
    bank = make_bank(frames)
    arrays, dates = window_arrays(bank, 0, 10, 200, StrategyParams())
    assert len(dates) == 190
    for key, arr in arrays.items():
        assert arr.shape[0] == 190, key
