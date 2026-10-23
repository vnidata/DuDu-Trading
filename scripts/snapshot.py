"""Làm mới dữ liệu và ghi ảnh chụp thị trường trong phiên.

Chạy 6 lần mỗi ngày theo nhịp phiên HOSE (giờ Việt Nam):
09:45, 10:00, 11:30, 13:30, 14:00, 15:00.

    python scripts/snapshot.py                     # dùng ngưỡng cache 5 phút
    python scripts/snapshot.py --refresh           # buộc tải lại toàn bộ
    python scripts/snapshot.py --offline           # chỉ đọc cache, không gọi mạng
    python scripts/snapshot.py --at "2026-10-12T10:00:00+07:00"   # mô phỏng mốc giờ

Ghi ra:
    site/data/snapshot.json          ảnh chụp đầy đủ của lần chạy gần nhất
    site/data/snapshot_history.json  lịch sử rút gọn để vẽ diễn biến trong ngày
"""

from __future__ import annotations

import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dudu.config import BENCHMARK_SYMBOL, DATA_DIR, DATA_START, DEFAULT_UNIVERSE_GROUP, SITE_DATA_DIR
from dudu.data import (
    CachePolicy,
    DataFetchInterrupted,
    PricePanel,
    compute_adv,
    load_benchmark,
    load_many,
)
from dudu.indicators import FeatureBank, build_market_regime
from dudu.pipeline import ATR_GRID, ENTRY_GRID, EXIT_GRID
from dudu.snapshot import (
    SESSION_LABELS,
    SnapshotContext,
    append_history,
    build_snapshot,
    history_entry,
    session_of,
    vn_now,
)
from dudu.utils import read_json, setup_logging, utc_now_iso, write_json

import logging

log = logging.getLogger("snapshot")

HISTORY_PATH_NAME = "snapshot_history.json"


def load_universe(group: str) -> list[str]:
    """Đọc danh sách mã đã lưu; nếu chưa có thì lấy từ API."""
    p = DATA_DIR / f"universe_{group}.json"
    if p.exists():
        payload = read_json(p)
        syms = payload.get("symbols") or []
        if syms:
            return list(syms)
    from dudu.data import fetch_universe

    return fetch_universe(group)


def build_features(
    symbols: list[str],
    start: str,
    policy: CachePolicy,
    benchmark: str,
    market_sma: int = 200,
    adv_window: int = 20,
) -> tuple[FeatureBank, dict]:
    data = load_many(symbols, start=start, policy=policy)
    if not data:
        raise RuntimeError("Không có mã nào tải được.")
    bench = load_benchmark(benchmark, start="2016-01-01", policy=policy)
    panel = PricePanel(data)
    bench_close = bench.set_index("time")["close"].reindex(panel.dates).ffill().to_numpy()
    regime_1d = build_market_regime(bench_close, market_sma)
    regime = np.repeat(regime_1d[:, None], len(panel.symbols), axis=1)
    adv = compute_adv(panel, adv_window)
    bank = FeatureBank(panel, ENTRY_GRID, EXIT_GRID, ATR_GRID, adv=adv, regime=regime)
    return bank, {"bench_close": bench_close, "n_symbols": len(panel.symbols), "n_sessions": len(panel.dates)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ảnh chụp thị trường trong phiên")
    ap.add_argument("--group", default=DEFAULT_UNIVERSE_GROUP)
    ap.add_argument("--symbol", default=BENCHMARK_SYMBOL)
    ap.add_argument("--start", default=DATA_START)
    ap.add_argument("--max-age-minutes", type=float, default=5.0)
    ap.add_argument("--refresh", action="store_true", help="Buộc tải lại toàn bộ")
    ap.add_argument("--offline", action="store_true", help="Chỉ đọc cache, không gọi mạng")
    ap.add_argument("--at", default=None, help="Mốc thời gian ISO để mô phỏng (mặc định: bây giờ)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    setup_logging(logging.WARNING if args.quiet else logging.INFO)
    t0 = time.time()

    now = datetime.fromisoformat(args.at) if args.at else vn_now()
    symbols = load_universe(args.group)
    log.info("Ảnh chụp %s | %s | %d mã", now.isoformat(timespec="seconds"), SESSION_LABELS[session_of(now)], len(symbols))

    if args.offline:
        policy = CachePolicy(refresh=False, max_age_days=3650)
    else:
        policy = CachePolicy(refresh=args.refresh, max_age_minutes=args.max_age_minutes, sleep_between=0.0)

    try:
        bank, ctx = build_features(symbols, args.start, policy, args.symbol)
    except DataFetchInterrupted as exc:
        log.error("Dừng do rate limit: %s", exc)
        return 3

    manifest_path = DATA_DIR / "manifest.json"
    dataset_generated_at = None
    if manifest_path.exists():
        dataset_generated_at = read_json(manifest_path).get("generated_at")

    snap = build_snapshot(
        bank,
        SnapshotContext(universe_group=args.group, benchmark=args.symbol),
        now=now,
        bench_close=ctx["bench_close"],
        dataset_generated_at=dataset_generated_at,
    )
    snap["runtime_seconds"] = round(time.time() - t0, 1)
    write_json(snap, SITE_DATA_DIR / "snapshot.json")

    hist_path = SITE_DATA_DIR / HISTORY_PATH_NAME
    history = read_json(hist_path) if hist_path.exists() else []
    if not isinstance(history, list):
        history = []
    history = append_history(history, history_entry(snap))
    write_json(history, hist_path)

    # Cập nhật mốc làm mới gần nhất trong manifest để website biết dữ liệu mới cỡ nào
    if manifest_path.exists():
        man = read_json(manifest_path)
        man["last_snapshot_at"] = snap["as_of"]
        man["last_snapshot_bar_date"] = snap["bar_date"]
        man["last_snapshot_session"] = snap["session"]
        write_json(man, manifest_path, indent=2)

    b = snap["benchmark"]
    log.info(
        "%s | VNINDEX %s (%+.2f%%) | độ rộng tăng %.0f%% | GTGD %.0f tỷ | %d/%d mã đạt ADV | tín hiệu vào %d, ra %d | bar %s%s",
        snap["session_label"],
        b.get("close"),
        (b.get("change_pct") or 0) * 100,
        snap["breadth"]["up_share"] * 100,
        snap["liquidity"]["turnover_total_bn"],
        snap["liquidity"]["n_passes_adv"],
        snap["n_symbols"],
        snap["signals"]["n_entry"],
        snap["signals"]["n_exit"],
        snap["bar_date"],
        "" if snap["is_final"] else " (CHƯA CHỐT)",
    )
    if not args.quiet:
        print(json.dumps({k: v for k, v in snap.items() if k not in ("symbols", "leaders")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
