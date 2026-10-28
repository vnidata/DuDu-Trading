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
    """Lấy danh sách mã theo nhóm chỉ số từ vnstock 5.x hoặc API VCI dự phòng.

    Trả về danh sách mã đã sắp xếp. Ném lỗi nếu không lấy được để tránh âm
    thầm chạy trên universe rỗng.
    """
    # 1. Ưu tiên thư viện vnstock 5.x chính thức (từ https://vnstocks.com/download)
    try:
        from vnstock import Listing
        res = Listing().symbols_by_group(group)
        if res is not None:
            symbols = sorted({str(s).upper() for s in res.dropna().tolist() if str(s).strip()})
            if symbols:
                log.info("Universe %s (vnstock 5.x): %d mã", group, len(symbols))
                return symbols
    except Exception as exc:
        log.debug("vnstock 5.x Listing() nhóm %s: %s, chuyển sang API dự phòng", group, exc)

    # 2. Dự phòng API VCI trực tiếp
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
            log.info("Universe %s (VCI API): %d mã", group, len(symbols))
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
    max_age_minutes: float | None = None  # ngưỡng theo phút, ưu tiên hơn max_age_days
    sleep_between: float = 0.35    # giãn nhịp gọi API, tránh rate limit

    def is_fresh(self, path: Path, now: float | None = None) -> bool:
        """Cache còn dùng được không.

        `max_age_minutes` phục vụ các lần làm mới trong phiên giao dịch (6 mốc
        mỗi ngày), khi ngưỡng 3 ngày là quá thô.
        """
        if not path.exists():
            return False
        age = (now if now is not None else time.time()) - path.stat().st_mtime
        if self.max_age_minutes is not None:
            return age <= self.max_age_minutes * 60.0
        return age <= self.max_age_days * 86400.0


def _cache_path(symbol: str, start: str) -> Path:
    return RAW_DIR / f"{symbol.upper()}_{start[:4]}.csv.gz"


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
    # Vnstock/VNDirect trả giá theo nghìn VND cho một số nguồn; VCI trả VND thực.
    # Chuẩn hoá về VND: nếu giá < 1000 thì gần như chắc chắn là đơn vị nghìn VND.
    med = float(out["close"].median())
    if 0 < med < 1000:
        for col in ("open", "high", "low", "close"):
            out[col] = out[col] * 1000.0
    out["volume"] = out["volume"].fillna(0.0)
    return out


def _fetch_vndirect(symbol: str, start: str, end: str | None = None, timeout: float = 12.0) -> pd.DataFrame:
    """Tải lịch sử OHLCV trực tiếp từ VNDirect DChart API.

    Tốc độ cao (<200ms/mã), có nến ngày hiện tại (intraday) theo thời gian thực,
    xác thực TLS an toàn qua truststore hệ điều hành, không gặp lỗi rate limit.
    """
    import json
    import urllib.request
    from datetime import datetime

    inject_truststore()

    start_dt = datetime.fromisoformat(start) if isinstance(start, str) else datetime(2016, 1, 1)
    start_ts = int(start_dt.timestamp())
    if end:
        end_dt = datetime.fromisoformat(end) if isinstance(end, str) else datetime.now()
        end_ts = int(end_dt.timestamp())
    else:
        end_ts = int(time.time())

    sym = symbol.upper()
    if sym in ("VN-INDEX", "VNINDEX", "^VNINDEX"):
        sym = "VNINDEX"

    url = f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={sym}&from={start_ts}&to={end_ts}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        if payload.get("s") != "ok" or not payload.get("t"):
            raise ValueError(f"VNDirect không có dữ liệu cho {symbol}")
        df = pd.DataFrame(
            {
                "time": pd.to_datetime(payload["t"], unit="s"),
                "open": payload["o"],
                "high": payload["h"],
                "low": payload["l"],
                "close": payload["c"],
                "volume": payload["v"],
            }
        )
        return _normalize(df, symbol)


_VNSTOCK_AUTHED: bool | None = None


def _init_vnstock() -> None:
    global _VNSTOCK_AUTHED
    if _VNSTOCK_AUTHED is not None:
        return
    import os

    api_key = os.getenv("VNSTOCKS_API_KEY") or os.getenv("VNSTOCK_API_KEY")
    if api_key:
        try:
            import vnstock

            res = vnstock.login(api_key.strip())
            _VNSTOCK_AUTHED = True
            log.info("vnstock 5.x: Đăng nhập API key thành công (cấp: %s)", res.get("tier"))
        except Exception as exc:
            _VNSTOCK_AUTHED = False
            log.warning("vnstock 5.x: Đăng nhập API key thất bại (%s)", exc)
    else:
        _VNSTOCK_AUTHED = False


def _fetch_vnstock(symbol: str, start: str, end: str | None = None, source: str = "KBS") -> pd.DataFrame:
    """Tải lịch sử OHLCV qua thư viện chính thức Vnstock 5.x (https://vnstocks.com/download).

    Tự động chuẩn hoá đơn vị giá và tương thích cả cổ phiếu (Quote) lẫn chỉ số (Market.index).
    """
    _init_vnstock()
    inject_truststore()
    logging.getLogger("vnstock").setLevel(logging.ERROR)
    sym = symbol.upper()

    try:
        from vnstock import Market, Quote
    except ImportError as exc:
        raise RuntimeError(
            "Chưa cài đặt vnstock 5.x: pip install -U --extra-index-url https://vnstocks.com/api/packages vnstock"
        ) from exc

    if sym in ("VN-INDEX", "VNINDEX", "^VNINDEX"):
        df = Market().index("VNINDEX").history(start=start, end=end or None, interval="1D")
    else:
        try:
            q = Quote(symbol=sym, source=source)
            df = q.history(start=start, end=end or None, interval="1D")
        except Exception:
            fallback_source = "VCI" if source.upper() == "KBS" else "KBS"
            q = Quote(symbol=sym, source=fallback_source)
            df = q.history(start=start, end=end or None, interval="1D")

    if df is None or len(df) == 0:
        raise ValueError(f"vnstock 5.x trả về chuỗi rỗng cho {symbol}")

    out = _normalize(df, symbol)
    # Kiểm tra xem có bị giới hạn 365 ngày của tài khoản guest không khi yêu cầu mốc thời gian xa hơn
    start_ts = pd.Timestamp(start)
    if (out["time"].min() - start_ts).days > 365:
        raise ValueError(
            f"vnstock 5.x cấp Khách bị giới hạn 365 ngày gần nhất (từ {out['time'].min().date()}), cần đủ từ {start}"
        )
    return out


def _fetch_remote(symbol: str, start: str, end: str | None, retries: int = 3) -> pd.DataFrame:
    """Tải dữ liệu từ xa: Thử thư viện chính thức Vnstock 5.x, kết hợp failover VNDirect DChart."""
    # 1. Thử tải qua Vnstock 5.x (phân phối chính thức https://vnstocks.com/download)
    try:
        return _fetch_vnstock(symbol, start, end)
    except Exception as exc:
        log.debug("%s: vnstock 5.x chưa hoàn tất (%s), chuyển sang VNDirect Real-time feed", symbol, exc)

    # 2. Dự phòng VNDirect DChart API (siêu tốc ~100ms/mã, có nến realtime, không vướng hạn ngạch guest)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return _fetch_vndirect(symbol, start, end)
        except Exception as exc:
            last_err = exc
            time.sleep(0.3 * (attempt + 1))

    raise RuntimeError(f"Không tải được {symbol}: {last_err}")


def _fetch_with_source(
    symbol: str,
    start: str,
    end: str | None,
    source: str = "auto",
) -> pd.DataFrame:
    """Tải nến giá từ Vnstock 5.x, VNDirect hoặc MCP (SSI, DNSE, VCBS) với cơ chế failover."""
    source_lower = source.lower()
    if source_lower in ("vnstock", "vnstock5"):
        return _fetch_vnstock(symbol, start, end)

    if source_lower in ("ssi", "dnse", "vcbs"):
        from .mcp_client import StockMCPClient

        client = StockMCPClient(provider=source_lower)
        return client.fetch_stock_candles(symbol, start, end)

    if source_lower == "mcp":
        from .mcp_client import MultiProviderMCPClient

        coordinator = MultiProviderMCPClient()
        return coordinator.fetch_stock_candles(symbol, start, end)

    if source_lower == "auto":
        # 1. Ưu tiên VNDirect DChart API (siêu tốc ~150ms/mã, có nến realtime hôm nay)
        try:
            return _fetch_vndirect(symbol, start, end)
        except Exception as exc:
            log.info("%s: VNDirect không khả dụng (%s), chuyển sang MCP/Vnstock", symbol, exc)

        # 2. Dự phòng MCP nếu có token
        from .mcp_auth import get_token
        from .mcp_client import MultiProviderMCPClient

        if any(get_token(p) for p in ("ssi", "dnse", "vcbs")):
            try:
                coordinator = MultiProviderMCPClient()
                return coordinator.fetch_stock_candles(symbol, start, end)
            except Exception as exc:
                log.info("MCP tải %s không thành công (%s), chuyển sang Vnstock", symbol, exc)

    return _fetch_remote(symbol, start, end)


def load_ohlcv(
    symbol: str,
    start: str = DATA_START,
    end: str | None = None,
    policy: CachePolicy | None = None,
    source: str = "auto",
) -> pd.DataFrame:
    """Đọc OHLCV từ cache, tải mới nếu cache thiếu hoặc đã cũ.

    Tham số `source`:
      - 'auto': Ưu tiên các máy chủ MCP (SSI, DNSE, VCBS) nếu có token xác thực;
                tự động fallback sang VCI (vnstock) nếu không có hoặc lỗi.
      - 'ssi' | 'dnse' | 'vcbs': Gọi chỉ định qua máy chủ MCP tương ứng.
      - 'vci': Tải trực tiếp qua vnstock VCI.
    """
    policy = policy or CachePolicy()
    path = _cache_path(symbol, start)

    if not policy.refresh and policy.is_fresh(path):
        df = read_gzip_csv(path)
        df["time"] = pd.to_datetime(df["time"])
        return _apply_end(df, end)

    try:
        df = _fetch_with_source(symbol, start, end, source=source)
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
    source: str = "auto",
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
            df = load_ohlcv(sym, start=start, end=end, policy=policy, source=source)
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
    def shape(self) -> tuple[int, int]:
        return self.close.shape

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
