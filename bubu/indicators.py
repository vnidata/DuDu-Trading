"""Chỉ báo kỹ thuật và ngân hàng đặc trưng tính trước cho GA.

Ý tưởng thiết kế: GA cần đánh giá hàng nghìn bộ tham số. Nếu mỗi lần đánh giá
lại tính lại chỉ báo thì chi phí bùng nổ. Vì vậy ta tính trước Donchian cho
toàn bộ cửa sổ ứng viên và ATR cho toàn bộ chu kỳ ứng viên, mỗi lần đánh giá
chỉ còn việc cắt mảng.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import MarketConfig
from .data import PricePanel


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """ATR theo đúng định nghĩa Wilder: khởi tạo bằng SMA rồi đệ quy làm mịn.

    Lưu ý 1: `np.roll` phải chỉ rõ `axis=0`; nếu bỏ trống, numpy làm phẳng mảng
    và dịch chuyển xuyên cột, khiến ATR của mọi mã trộn lẫn vào nhau.

    Lưu ý 2: `pandas.ewm(adjust=False)` không dùng giá trị mồi SMA mà khởi động
    đệ quy ngay từ phần tử đầu tiên. Sai khác chỉ nằm trong `period` phiên đầu,
    nhưng vì ATR là cơ sở của stop loss và position sizing nên bản này dùng
    đúng công thức gốc: ATR[period-1] = SMA(TR, period), sau đó
    ATR[t] = (ATR[t-1] × (period − 1) + TR[t]) / period.
    """
    prev_close = np.roll(close, 1, axis=0)
    prev_close[0, :] = np.nan
    # np.fmax bỏ qua NaN, tránh cảnh báo "All-NaN slice" ở các ô chưa niêm yết.
    tr = np.fmax(
        high - low,
        np.fmax(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    n, m = tr.shape
    atr = np.full((n, m), np.nan)
    if n < period:
        return atr
    valid = ~np.isnan(tr)
    cum = np.cumsum(valid, axis=0)
    has = cum[-1] >= period
    if not has.any():
        return atr
    # Phiên bắt đầu của từng cột: nơi đã tích luỹ đủ `period` giá trị TR hợp lệ.
    # Các mã niêm yết muộn vì thế có ATR bắt đầu đúng từ dữ liệu của chính nó
    # thay vì bị NaN vĩnh viễn.
    start = np.argmax(cum >= period, axis=0)
    start = np.where(has, start, -1)
    for j in range(m):
        if has[j]:
            s = int(start[j])
            window = tr[: s + 1, j]
            window = window[~np.isnan(window)]
            atr[s, j] = float(window.mean())
    inv = 1.0 / period
    for i in range(int(start[has].min()) + 1, n):
        prev = atr[i - 1]
        row = tr[i]
        nxt = prev + (row - prev) * inv
        upd = (i > start) & has
        atr[i] = np.where(upd, np.where(np.isnan(row), prev, nxt), atr[i])
    return atr


def donchian_upper(high: np.ndarray, window: int) -> np.ndarray:
    """Đỉnh cao nhất `window` phiên TRƯỚC ngày hiện tại (loại trừ ngày t)."""
    return pd.DataFrame(high).rolling(window, min_periods=window).max().shift(1).to_numpy()


def donchian_lower(low: np.ndarray, window: int) -> np.ndarray:
    """Đáy thấp nhất `window` phiên TRƯỚC ngày hiện tại (loại trừ ngày t)."""
    return pd.DataFrame(low).rolling(window, min_periods=window).min().shift(1).to_numpy()


def sma(x: np.ndarray, window: int) -> np.ndarray:
    return pd.DataFrame(x).rolling(window, min_periods=window).mean().to_numpy()


def price_limits(close: np.ndarray, market: MarketConfig) -> tuple[np.ndarray, np.ndarray]:
    """Ma trận giá trần / giá sàn theo giá tham chiếu = giá đóng cửa phiên trước."""
    ref = np.roll(close, 1, axis=0)
    ref[0, :] = np.nan
    n, m = close.shape
    ceiling = np.full((n, m), np.nan)
    floor = np.full((n, m), np.nan)
    for j in range(m):
        col = ref[:, j]
        valid = ~np.isnan(col)
        vals = col[valid]
        if vals.size == 0:
            continue
        # Bước giá xác định theo khung giá của chính mức giá trần/sàn, đúng quy
        # định HOSE. Dùng bước giá của giá tham chiếu sẽ sai lệch khi mức trần
        # vượt lên khung giá cao hơn (ví dụ tham chiếu 9.900 -> trần 10.593).
        up = vals * (1.0 + market.price_limit)
        dn = vals * (1.0 - market.price_limit)
        tick_up = np.where(up < 10_000, 10.0, np.where(up < 50_000, 50.0, 100.0))
        tick_dn = np.where(dn < 10_000, 10.0, np.where(dn < 50_000, 50.0, 100.0))
        ceiling[valid, j] = np.floor(up / tick_up) * tick_up
        floor[valid, j] = np.ceil(dn / tick_dn) * tick_dn
    return ceiling, floor


class FeatureBank:
    """Tập đặc trưng tính trước cho một PricePanel."""

    def __init__(
        self,
        panel: PricePanel,
        entry_windows: list[int],
        exit_windows: list[int],
        atr_periods: list[int],
        market: MarketConfig | None = None,
        adv: np.ndarray | None = None,
        regime: np.ndarray | None = None,
    ) -> None:
        self.panel = panel
        self.market = market or MarketConfig()
        self.upper = {w: donchian_upper(panel.high, w) for w in sorted(set(entry_windows))}
        self.lower = {w: donchian_lower(panel.low, w) for w in sorted(set(exit_windows))}
        self.atr = {
            p: wilder_atr(panel.high, panel.low, panel.close, p) for p in sorted(set(atr_periods))
        }
        self.ceiling, self.floor = price_limits(panel.close, self.market)
        self.adv = adv if adv is not None else np.full(panel.close.shape, np.nan)
        self.regime = regime if regime is not None else np.ones(panel.close.shape, dtype=bool)
        # Số phiên kể từ ngày niêm yết/ có dữ liệu, dùng để loại tín hiệu đầu chuỗi.
        self.age = np.cumsum(panel.listed.astype(int), axis=0)

    def n_dates(self) -> int:
        return self.panel.close.shape[0]

    def atr_ref(self, period: int) -> np.ndarray:
        """ATR gần nhất có trong bank (dùng khi GA trả về chu kỳ nằm ngoài lưới)."""
        if period in self.atr:
            return self.atr[period]
        nearest = min(self.atr, key=lambda p: abs(p - period))
        return self.atr[nearest]

    def upper_ref(self, window: int) -> np.ndarray:
        if window in self.upper:
            return self.upper[window]
        nearest = min(self.upper, key=lambda w: abs(w - window))
        return self.upper[nearest]

    def lower_ref(self, window: int) -> np.ndarray:
        if window in self.lower:
            return self.lower[window]
        nearest = min(self.lower, key=lambda w: abs(w - window))
        return self.lower[nearest]


def build_market_regime(bench_close: np.ndarray, sma_window: int = 200) -> np.ndarray:
    """True khi chỉ số tham chiếu đóng cửa trên SMA của chính nó."""
    ref = sma(bench_close.reshape(-1, 1), sma_window).ravel()
    return (bench_close > ref) & ~np.isnan(ref)
