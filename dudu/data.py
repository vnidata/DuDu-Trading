"""Tầng dữ liệu: universe từ VCI, OHLCV qua vnstock, cache cục bộ.

Nguồn dữ liệu: Vnstock 3.x (nhà cung cấp VCI - Vietcap). Mọi dữ liệu giá được
lưu cache dạng CSV nén trong `data/raw/` để pipeline chạy lại không cần tải
mạng, đồng thời bảo đảm tính tái lập của kết quả nghiên cứu.

Lưu ý phương pháp luận: danh sách VN100 lấy tại thời điểm chạy là danh sách
hiện hành, không phải danh sách point-in-time. Điều này tạo survivorship bias
nhất định và được nêu rõ trong `METHODOLOGY.md`.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .config import BENCHMARK_SYMBOL, DATA_START, RAW_DIR
from .utils import inject_truststore, read_gzip_csv, write_gzip_csv

log = logging.getLogger(__name__)

VCI_GROUP_URL = "https://trading.vietcap.com.vn/api/price/symbols/getByGroup?group={group}"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; DuDu-Trading/1.0)"}

OHLCV_COLUMNS = ["time", "open", "high", "low", "close", "volume"]


# --------------------------------------------------------------------------
# Điều tiết nhịp gọi API
# --------------------------------------------------------------------------
class RateLimiter:
    """Giới hạn số request trong cửa sổ trượt 60 giây.

    Thư viện `vnai` đi kèm vnstock áp trần 60 request/phút cho nguồn VCI và
    gọi thẳng `sys.exit()` khi vượt trần, khiến toàn bộ tiến trình bị hủy giữa
    chừng. Vì vậy phía client phải tự điều tiết nhịp xuống dưới ngưỡng đó.
    """

    def __init__(self, max_per_minute: int = 48, window: float = 60.0) -> None:
        self.max_per_minute = max_per_minute
        self.window = window
        self._times: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self._times and now - self._times[0] > self.window:
            self._times.popleft()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._trim(now)
            while len(self._times) >= self.max_per_minute:
                wait = self.window - (now - self._times[0]) + 0.75
                if wait > 0:
                    log.info("Điều tiết API: chờ %.1fs để giữ dưới %d request/phút", wait, self.max_per_minute)
                    time.sleep(wait)
                now = time.monotonic()
                self._trim(now)
            self._times.append(time.monotonic())

    def usage(self) -> int:
        with self._lock:
            self._trim(time.monotonic())
            return len(self._times)


LIMITER = RateLimiter(max_per_minute=48)


class DataFetchInterrupted(RuntimeError):
    """vnstock thoát tiến trình do vượt rate limit; cần chạy lại để tiếp tục."""


# --------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------
def fetch_universe(group: str = "VN100", retries: int = 3) -> list[str]:
    """Lấy danh sách mã theo nhóm chỉ số từ API VCI (nguồn dữ liệu của vnstock).

    Trả về danh sách mã đã sắp xếp. Ném lỗi nếu không lấy được để tránh âm
    thầm chạy trên universe rỗng.
    """
    inject_truststore()
    import requests

    url = VCI_GROUP_URL.format(group=group)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_UA, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            symbols = sorted({str(row["symbol"]).upper() for row in payload if row.get("symbol")})
            if not symbols:
                raise ValueError(f"Nhóm {group} trả về danh sách rỗng")
            log.info("Universe %s: %d mã", group, len(symbols))
            return symbols
        except Exception as exc:  # pragma: no cover - phụ thuộc mạng
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Không lấy được universe {group}: {last_err}")


# --------------------------------------------------------------------------
# OHLCV
# --------------------------------------------------------------------------
@dataclass
class CachePolicy:
    refresh: bool = False          # tải lại kể cả khi đã có cache
    max_age_days: int = 3          # cache cũ hơn ngưỡng này sẽ được tải lại
    sleep_between: float = 0.35    # giãn nhịp gọi API, tránh rate limit


def _cache_path(symbol: str, start: str) -> Path:
    return RAW_DIR / f"{symbol.upper()}_{start[:4]}.csv.gz"


def _fetch_remote(symbol: str, start: str, end: str | None, retries: int = 3) -> pd.DataFrame:
    inject_truststore()
    logging.getLogger("vnstock").setLevel(logging.ERROR)
    logging.getLogger("vnai").setLevel(logging.ERROR)
    from vnstock import Quote

    last_err: Exception | None = None
    for attempt in range(retries):
        LIMITER.acquire()
        try:
            quote = Quote(symbol=symbol.upper(), source="VCI")
            df = quote.history(start=start, end=end or None, interval="1D")
            if df is None or len(df) == 0:
                raise ValueError("chuỗi rỗng")
            return _normalize(df, symbol)
        except SystemExit as exc:  # vnai gọi sys.exit khi vượt rate limit
            raise DataFetchInterrupted(f"vnstock dừng tiến trình: {exc}") from None
        except Exception as exc:  # pragma: no cover - phụ thuộc mạng
            last_err = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"Không tải được {symbol}: {last_err}")


def _normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    out = df.copy()
    lower = {c: str(c).lower() for c in out.columns}
    out = out.rename(columns=lower)
    if "time" not in out.columns and out.index.name:
        out = out.reset_index().rename(columns={out.index.name: "time"})
    for col in OHLCV_COLUMNS:
        if col not in out.columns:
            raise ValueError(f"{symbol}: thiếu cột {col}")
    out = out[OHLCV_COLUMNS].copy()
    out["time"] = pd.to_datetime(out["time"]).dt.tz_localize(None).dt.normalize()
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = (
        out.dropna(subset=["close"])
        .drop_duplicates(subset="time", keep="last")
        .sort_values("time")
        .reset_index(drop=True)
    )
    # Vnstock trả giá theo nghìn VND cho một số nguồn; VCI trả VND thực.
    # Chuẩn hoá về VND: nếu giá < 1000 thì gần như chắc chắn là đơn vị nghìn VND.
    med = float(out["close"].median())
    if 0 < med < 1000:
        for col in ("open", "high", "low", "close"):
            out[col] = out[col] * 1000.0
    out["volume"] = out["volume"].fillna(0.0)
    return out


def load_ohlcv(
    symbol: str,
    start: str = DATA_START,
    end: str | None = None,
    policy: CachePolicy | None = None,
) -> pd.DataFrame:
    """Đọc OHLCV từ cache, tải mới nếu cache thiếu hoặc đã cũ."""
    policy = policy or CachePolicy()
    path = _cache_path(symbol, start)

    if path.exists() and not policy.refresh:
        age_days = (time.time() - path.stat().st_mtime) / 86400.0
        if age_days <= policy.max_age_days:
            df = read_gzip_csv(path)
            df["time"] = pd.to_datetime(df["time"])
            return _apply_end(df, end)

    try:
        df = _fetch_remote(symbol, start, end)
    except DataFetchInterrupted:
        raise
    except RuntimeError:
        if not path.exists():
            raise
        log.warning("%s: tải mạng thất bại, dùng cache cũ", symbol)
        df = read_gzip_csv(path)
        df["time"] = pd.to_datetime(df["time"])
        return _apply_end(df, end)

    write_gzip_csv(df, path)
    return _apply_end(df, end)


def _apply_end(df: pd.DataFrame, end: str | None) -> pd.DataFrame:
    if end:
        df = df[df["time"] <= pd.Timestamp(end)].reset_index(drop=True)
    return df


def load_many(
    symbols: Sequence[str],
    start: str = DATA_START,
    end: str | None = None,
    policy: CachePolicy | None = None,
) -> dict[str, pd.DataFrame]:
    """Tải tuần tự nhiều mã.

    Nếu chạm trần rate limit của nhà cung cấp, dừng lại và phát lại
    `DataFetchInterrupted`. Cache trên đĩa bảo đảm lần chạy kế tiếp chỉ tải
    phần còn thiếu, nên chỉ cần gọi lại là tiếp tục được.
    """
    policy = policy or CachePolicy()
    out: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        try:
            df = load_ohlcv(sym, start=start, end=end, policy=policy)
            if len(df) < 120:
                log.warning("%s: chỉ có %d phiên, bỏ qua", sym, len(df))
            else:
                out[sym] = df
        except DataFetchInterrupted as exc:
            log.warning("Dừng tải tại %s (%d/%d mã đã có): %s", sym, i - 1, len(symbols), exc)
            raise DataFetchInterrupted(
                f"Đã tải {len(out)}/{len(symbols)} mã. Chạy lại lệnh để tiếp tục từ cache."
            ) from None
        except Exception as exc:
            log.error("%s: bỏ qua (%s)", sym, exc)
        if policy.sleep_between:
            time.sleep(policy.sleep_between)
        if i % 10 == 0:
            log.info("Tiến độ tải dữ liệu: %d/%d (điều tiết: %d req/phút)", i, len(symbols), LIMITER.usage())
    return out


def load_benchmark(
    symbol: str = BENCHMARK_SYMBOL,
    start: str = DATA_START,
    end: str | None = None,
    policy: CachePolicy | None = None,
) -> pd.DataFrame:
    """Tải chỉ số tham chiếu (mặc định VN-Index) cho bộ lọc xu hướng thị trường."""
    return load_ohlcv(symbol, start=start, end=end, policy=policy)


# --------------------------------------------------------------------------
# Panel tiện dụng
# --------------------------------------------------------------------------
class PricePanel:
    """Bọc từ điển DataFrame thành ma trận numpy căn thẳng theo ngày.

    Mọi chỉ báo đều được tính trên ma trận này để backtest chỉ còn thao tác
    cắt mảng, nhờ đó GA có thể chạy hàng nghìn lần đánh giá.
    """

    def __init__(self, data: dict[str, pd.DataFrame]) -> None:
        if not data:
            raise ValueError("PricePanel cần ít nhất một mã")
        self.symbols: list[str] = sorted(data)
        idx = sorted({ts for df in data.values() for ts in df["time"]})
        self.dates = pd.DatetimeIndex(idx)
        n, m = len(self.dates), len(self.symbols)
        self.close = np.full((n, m), np.nan)
        self.open = np.full((n, m), np.nan)
        self.high = np.full((n, m), np.nan)
        self.low = np.full((n, m), np.nan)
        self.volume = np.full((n, m), np.nan)
        self.listed = np.zeros((n, m), dtype=bool)
        pos = {ts: i for i, ts in enumerate(self.dates)}
        for j, sym in enumerate(self.symbols):
            df = data[sym]
            rows = df["time"].map(pos).to_numpy()
            self.close[rows, j] = df["close"].to_numpy()
            self.open[rows, j] = df["open"].to_numpy()
            self.high[rows, j] = df["high"].to_numpy()
            self.low[rows, j] = df["low"].to_numpy()
            self.volume[rows, j] = df["volume"].to_numpy()
            self.listed[rows, j] = True
        # Nội suy khoảng trống niêm yết bằng giá gần nhất để chỉ báo liên tục.
        self.close = _ffill_nan(self.close)
        self.open = np.where(np.isnan(self.open), self.close, self.open)
        self.high = np.where(np.isnan(self.high), self.close, self.high)
        self.low = np.where(np.isnan(self.low), self.close, self.low)
        self.volume = np.nan_to_num(self.volume, nan=0.0)

    def __len__(self) -> int:
        return len(self.dates)

    @property
    def symbol_index(self) -> dict[str, int]:
        return {s: j for j, s in enumerate(self.symbols)}

    def slice_dates(self, start: int, stop: int) -> "DateWindow":
        return DateWindow(self, start, stop)


class DateWindow:
    """Cửa sổ ngày trên PricePanel (dùng cho walk-forward)."""

    def __init__(self, panel: PricePanel, start: int, stop: int) -> None:
        self.panel = panel
        self.start = start
        self.stop = stop

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.panel.dates[self.start : self.stop]

    def __len__(self) -> int:
        return max(0, self.stop - self.start)


def _ffill_nan(a: np.ndarray) -> np.ndarray:
    out = a.copy()
    n, m = out.shape
    for j in range(m):
        last = np.nan
        for i in range(n):
            v = out[i, j]
            if np.isnan(v):
                out[i, j] = last
            else:
                last = v
    return out


def compute_adv(panel: PricePanel, window: int = 20) -> np.ndarray:
    """Giá trị giao dịch bình quân (VND/phiên), dịch 1 phiên để chống look-ahead."""
    turnover = panel.close * panel.volume
    df = pd.DataFrame(turnover)
    adv = df.rolling(window, min_periods=max(5, window // 3)).mean().shift(1)
    return adv.to_numpy()
