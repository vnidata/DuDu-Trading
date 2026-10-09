"""Làm mới `site/data/meta.json` từ các tệp dữ liệu website đã có.

Dùng khi chỉ cần bổ sung/cập nhật phần thẻ tổng quan mà không muốn chạy lại
toàn bộ pipeline (vốn mất hàng chục phút):

    python scripts/refresh_meta.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dudu.config import BENCHMARK_SYMBOL, ROOT, SITE_DATA_DIR
from dudu.data import CachePolicy, load_benchmark
from dudu.metrics import equity_metrics
from dudu.utils import safe_float, setup_logging, utc_now_iso, write_json

import logging

log = logging.getLogger("refresh_meta")


def _read(name: str):
    p = SITE_DATA_DIR / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Làm mới meta.json")
    ap.add_argument("--benchmark", default=BENCHMARK_SYMBOL)
    args = ap.parse_args()
    setup_logging()

    meta = _read("meta.json")
    if meta is None:
        log.error("Không tìm thấy site/data/meta.json — chạy scripts/run_research.py trước.")
        return 1
    curves = _read("curves.json") or {}
    portfolio = _read("portfolio.json") or {}
    symbols = _read("symbols.json") or []
    ga = _read("ga.json") or {}
    wf = _read("walkforward.json") or {}

    # ---- Chỉ số tham chiếu ----
    dates = curves.get("dates") or []
    bench = curves.get("benchmark")
    if bench:
        # LƯU Ý: `curves["benchmark"]` đã được làm mảnh theo tuần (mỗi điểm cách
        # nhau 5 phiên). Không được tính chỉ số annual hoá trực tiếp trên chuỗi
        # này — phải đọc lại chuỗi giá NGÀY của chỉ số tham chiếu.
        symbol = meta["data"].get("benchmark", args.benchmark)
        start = meta["data"].get("date_start", "2016-01-01")
        end = meta["data"].get("date_end")
        daily = load_benchmark(symbol, start=start, end=end, policy=CachePolicy(sleep_between=0.0))
        eq = daily["close"].to_numpy(dtype=float)
        m = equity_metrics(eq, 252)
        meta["headline"]["benchmark_symbol"] = symbol
        meta["headline"]["benchmark_cagr"] = round(m["cagr"], 4)
        meta["headline"]["benchmark_sharpe"] = round(m["sharpe"], 4)
        meta["headline"]["benchmark_max_dd"] = round(m["max_dd"], 4)
        meta["headline"]["benchmark_calmar"] = round(m["calmar"], 4)
        meta["headline"]["benchmark_sessions"] = int(eq.size)
        meta["headline"]["portfolio_excess_cagr"] = round(
            safe_float(meta["headline"].get("portfolio_cagr")) - m["cagr"], 4
        )
        meta["headline"]["benchmark_note"] = (
            f"{symbol} mua-và-giữ trên {eq.size} phiên, không tính cổ tức tiền mặt."
        )
        log.info(
            "Tham chiếu %s: CAGR %.2f%%, Sharpe %.2f, MaxDD %.2f%% trên %d phiên",
            symbol,
            m["cagr"] * 100,
            m["sharpe"],
            m["max_dd"] * 100,
            eq.size,
        )

    # ---- Tham số GA trên rổ mã ----
    basket = (ga or {}).get("basket")
    if basket:
        meta["headline"]["ga_basket_params"] = basket.get("best")
        meta["headline"]["ga_basket_train_calmar"] = round(safe_float(basket["best_outcome"].get("calmar")), 4)
        oos = basket.get("oos_summary", {}).get("calmar", {})
        meta["headline"]["ga_basket_oos_calmar_median"] = round(safe_float(oos.get("median")), 4)

    # ---- Walk-forward ----
    s = (wf or {}).get("summary", {})
    if s:
        for key, src in (
            ("wf_acceptance_rate", "acceptance_rate"),
            ("wf_acceptance_rate_traded", "acceptance_rate_traded"),
            ("wf_traded_share", "traded_share"),
            ("wf_oos_calmar_gt_threshold", "oos_calmar_gt_threshold"),
            ("wf_ga_edge_vs_baseline", "ga_edge_vs_baseline"),
            ("wf_ga_edge_vs_baseline_traded", "ga_edge_vs_baseline_traded"),
        ):
            meta["headline"][key] = round(safe_float(s.get(src)), 4)
        meta["headline"]["wf_n_folds"] = int(s.get("n_folds", 0))
        d = s.get("distribution", {}).get("calmar", {})
        meta["headline"]["wf_oos_calmar_median"] = round(safe_float(d.get("oos_median")), 4)
        dt = s.get("distribution_traded", {}).get("calmar", {})
        meta["headline"]["wf_oos_calmar_median_traded"] = round(safe_float(dt.get("oos_median")), 4)

    # ---- Danh mục ----
    for key in list(portfolio):
        pf = portfolio[key]
        tag = "portfolio" if key == "default" else f"portfolio_{key}"
        for k in ("cagr", "sharpe", "calmar", "max_dd", "avg_exposure", "max_exposure"):
            if k in pf.get("metrics", {}):
                meta["headline"][f"{tag}_{k}" if key != "default" else f"portfolio_{k}"] = round(
                    safe_float(pf["metrics"][k]), 4
                )
        if "trades_per_year" in pf.get("trade_stats", {}):
            meta["headline"][f"{tag}_trades_per_year" if key != "default" else "portfolio_trades_per_year"] = round(
                safe_float(pf["trade_stats"]["trades_per_year"]), 2
            )

    if symbols:
        meta["headline"]["n_symbols_with_ga"] = int(sum(1 for r in symbols if r.get("ga_params")))
        meta["headline"]["n_symbols_oos_accepted"] = int(sum(1 for r in symbols if r.get("oos_accepted")))

    meta["meta_refreshed_at"] = utc_now_iso()
    # Nhúng commit hash hiện tại để website truy vết được đúng phiên bản mã nguồn
    try:
        import subprocess

        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        if sha:
            meta.setdefault("app", {})["git_sha"] = sha
    except Exception:
        pass
    write_json(meta, SITE_DATA_DIR / "meta.json")
    log.info("Đã ghi site/data/meta.json")
    for k, v in meta["headline"].items():
        print(f"  {k:38s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
