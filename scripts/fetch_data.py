"""Tải universe VN100 và toàn bộ lịch sử OHLCV cần thiết.

Dùng:
    python scripts/fetch_data.py --group VN100 --start 2016-01-01
    python scripts/fetch_data.py --refresh          # tải lại bỏ qua cache
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dudu.config import BENCHMARK_SYMBOL, DATA_START, DEFAULT_UNIVERSE_GROUP, DATA_DIR
from dudu.data import (
    CachePolicy,
    DataFetchInterrupted,
    fetch_universe,
    load_benchmark,
    load_many,
)
from dudu.utils import setup_logging, utc_now_iso, write_json

import logging

log = logging.getLogger("fetch_data")


def main() -> int:
    ap = argparse.ArgumentParser(description="Tải dữ liệu VN100 qua vnstock")
    ap.add_argument("--group", default=DEFAULT_UNIVERSE_GROUP)
    ap.add_argument("--start", default=DATA_START)
    ap.add_argument("--end", default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=0, help="Giới hạn số mã (chạy thử)")
    ap.add_argument("--max-rounds", type=int, default=6, help="Số vòng thử lại khi chạm rate limit")
    args = ap.parse_args()

    setup_logging()
    t0 = time.time()
    symbols = fetch_universe(args.group)
    if args.limit:
        symbols = symbols[: args.limit]
    write_json(
        {
            "generated_at": utc_now_iso(),
            "group": args.group,
            "source": "https://trading.vietcap.com.vn/api/price/symbols/getByGroup",
            "count": len(symbols),
            "symbols": symbols,
        },
        DATA_DIR / f"universe_{args.group}.json",
        indent=2,
    )
    log.info("Bắt đầu tải %d mã từ %s", len(symbols), args.start)

    policy = CachePolicy(refresh=args.refresh, sleep_between=args.sleep)
    data: dict = {}
    for round_no in range(1, args.max_rounds + 1):
        try:
            data = load_many(symbols, start=args.start, end=args.end, policy=policy)
            break
        except DataFetchInterrupted as exc:
            log.warning("Vòng %d/%d: %s", round_no, args.max_rounds, exc)
            if round_no == args.max_rounds:
                log.error("Hết số vòng thử lại, còn thiếu %d mã", len(symbols) - 0)
                return 2
            log.info("Nghỉ 65 giây rồi tiếp tục từ cache...")
            time.sleep(65)
    else:  # pragma: no cover
        return 2

    log.info("Tải xong %d/%d mã trong %.0f giây", len(data), len(symbols), time.time() - t0)
    bench = load_benchmark(BENCHMARK_SYMBOL, start="2016-01-01", end=args.end, policy=policy)
    log.info(
        "Chỉ số tham chiếu %s: %d phiên (%s -> %s)",
        BENCHMARK_SYMBOL,
        len(bench),
        bench["time"].min().date(),
        bench["time"].max().date(),
    )

    missing = [s for s in symbols if s not in data]
    manifest = {
        "generated_at": utc_now_iso(),
        "group": args.group,
        "start": args.start,
        "end": args.end,
        "source": "vnstock 3.x / VCI (Vietcap)",
        "n_requested": len(symbols),
        "n_loaded": len(data),
        "missing": missing,
        "symbols": sorted(data),
        "sessions": {s: int(len(df)) for s, df in sorted(data.items())},
        "date_range": {
            "min": str(min(df["time"].min() for df in data.values()).date()),
            "max": str(max(df["time"].max() for df in data.values()).date()),
        },
        "benchmark": {"symbol": BENCHMARK_SYMBOL, "sessions": int(len(bench))},
    }
    write_json(manifest, DATA_DIR / "manifest.json", indent=2)
    log.info("Đã ghi %s", DATA_DIR / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
