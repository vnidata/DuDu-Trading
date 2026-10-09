"""Chạy lại riêng bước walk-forward và cập nhật `site/data/walkforward.json`.

Dùng khi chỉ cần làm mới phần walk-forward (ví dụ sau khi sửa logic báo cáo)
mà không muốn chạy lại toàn bộ GA:

    python scripts/rebuild_walkforward.py --jobs 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bubu.config import (
    GAConfig,
    RESULTS_DIR,
    SITE_DATA_DIR,
    BacktestConfig,
    WalkForwardConfig,
)
from bubu.pipeline import build_bank, run_walkforward
from bubu.report import build_walkforward_payload
from bubu.utils import setup_logging, write_json, write_json_gz

import gzip
import logging

log = logging.getLogger("rebuild_walkforward")


def main() -> int:
    ap = argparse.ArgumentParser(description="Chạy lại bước walk-forward")
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--from-cache", action="store_true", help="Dùng lại kết quả thô đã lưu")
    args = ap.parse_args()
    setup_logging()

    manifest = json.loads((SITE_DATA_DIR.parent.parent / "data" / "manifest.json").read_text(encoding="utf-8"))
    symbols = manifest["symbols"]
    bank, _ = build_bank(symbols, start=args.start)

    ga_cfg = GAConfig(population=18, generations=10, n_jobs=1) if args.fast else GAConfig(population=36, generations=20, n_jobs=1)
    t0 = time.time()
    raw_path = RESULTS_DIR / "walkforward_raw.json.gz"
    if args.from_cache and raw_path.exists():
        log.info("Đọc lại kết quả walk-forward thô từ %s", raw_path)
        with gzip.open(raw_path, "rt", encoding="utf-8") as fh:
            wf = json.load(fh)
    else:
        wf = run_walkforward(bank, BacktestConfig(), WalkForwardConfig(), ga_cfg, n_jobs=args.jobs)
        write_json_gz(wf, raw_path)
        log.info("Đã lưu kết quả thô vào %s", raw_path)
    if not wf.get("folds"):
        log.error("Walk-forward không sinh được fold nào — kiểm tra lỗi của từng mã.")
        return 1
    payload = build_walkforward_payload(wf)
    write_json(payload, SITE_DATA_DIR / "walkforward.json")
    log.info(
        "Đã ghi walkforward.json (%d fold hiển thị, %d fold tổng) trong %.0fs",
        len(payload.get("folds", [])),
        len(wf.get("folds", [])),
        time.time() - t0,
    )

    meta_path = SITE_DATA_DIR / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # Dùng summary của payload: summary thô chưa có các thống kê lợi nhuận test.
        s = payload.get("summary", wf.get("summary", {}))
        meta["headline"]["wf_acceptance_rate"] = round(float(s.get("acceptance_rate", 0.0)), 4)
        meta["headline"]["wf_acceptance_rate_traded"] = round(float(s.get("acceptance_rate_traded", 0.0)), 4)
        meta["headline"]["wf_traded_share"] = round(float(s.get("traded_share", 0.0)), 4)
        meta["headline"]["wf_oos_calmar_gt_threshold"] = round(float(s.get("oos_calmar_gt_threshold", 0.0)), 4)
        meta["headline"]["wf_ga_edge_vs_baseline"] = round(float(s.get("ga_edge_vs_baseline", 0.0)), 4)
        meta["headline"]["wf_ga_edge_vs_baseline_traded"] = round(
            float(s.get("ga_edge_vs_baseline_traded", 0.0)), 4
        )
        meta["headline"]["wf_oos_calmar_median"] = round(
            float(s.get("distribution", {}).get("calmar", {}).get("oos_median", 0.0)), 4
        )
        meta["headline"]["wf_oos_calmar_median_traded"] = round(
            float(s.get("distribution_traded", {}).get("calmar", {}).get("oos_median", 0.0)), 4
        )
        meta["headline"]["wf_oos_total_return_median_traded"] = round(
            float(s.get("oos_total_return_median_traded", 0.0)), 4
        )
        meta["headline"]["wf_oos_total_return_positive_share_traded"] = round(
            float(s.get("oos_total_return_positive_share_traded", 0.0)), 4
        )
        meta["headline"]["wf_ga_edge_total_return_traded"] = round(
            float(s.get("ga_edge_total_return_traded", 0.0)), 4
        )
        write_json(meta, meta_path)
        log.info("Đã cập nhật headline walk-forward trong meta.json")
    print(json.dumps(wf.get("summary", {}), ensure_ascii=False, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
