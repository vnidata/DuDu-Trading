"""Chạy toàn bộ pipeline nghiên cứu và kết xuất dữ liệu cho website.

Dùng:
    python scripts/run_research.py --limit 12 --fast        # chạy thử nhanh
    python scripts/run_research.py                          # VN100 đầy đủ
    python scripts/run_research.py --skip-walkforward
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bubu.config import (
    DATA_START,
    DEFAULT_UNIVERSE_GROUP,
    GAConfig,
    RESULTS_DIR,
    ParamSpace,
    PortfolioConfig,
    BacktestConfig,
    WalkForwardConfig,
)
from bubu.data import fetch_universe
from bubu.metrics import equity_metrics
from bubu.pipeline import (
    build_bank,
    default_backtest,
    liquidity_coverage,
    liquidity_report,
    parameter_heatmap,
    run_ablation,
    run_basket_ga,
    run_per_symbol_ga,
    run_portfolio_suite,
    run_walkforward,
)
from bubu.report import (
    build_ablation_payload,
    build_curves,
    build_ga_payload,
    build_meta,
    build_portfolio_payload,
    build_symbol_rows,
    build_walkforward_payload,
    write_site_data,
)
from bubu.utils import setup_logging, write_json_gz

log = logging.getLogger("run_research")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path.cwd(), text=True).strip()
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline nghiên cứu BuBu-Trading")
    ap.add_argument("--group", default=DEFAULT_UNIVERSE_GROUP)
    ap.add_argument("--start", default=DATA_START)
    ap.add_argument("--end", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--split", type=float, default=0.7, help="Tỷ lệ train cho kiểm định OOS")
    ap.add_argument("--fast", action="store_true", help="GA nhỏ để chạy thử")
    ap.add_argument("--no-ga", action="store_true")
    ap.add_argument("--no-walkforward", action="store_true")
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    setup_logging()
    t_start = time.time()

    symbols = fetch_universe(args.group)
    if args.limit:
        symbols = symbols[: args.limit]
    log.info("Universe %s: %d mã", args.group, len(symbols))

    bank, bank_meta = build_bank(
        symbols, start=args.start, end=args.end, refresh=args.refresh, sleep_between=0.0
    )

    cfg = BacktestConfig()
    space = ParamSpace()
    ga_cfg = (
        GAConfig(population=24, generations=12, n_jobs=args.jobs)
        if args.fast
        else GAConfig(population=48, generations=28, n_jobs=args.jobs)
    )
    wf_ga_cfg = (
        GAConfig(population=18, generations=10, n_jobs=1)
        if args.fast
        else GAConfig(population=36, generations=20, n_jobs=1)
    )
    wf_cfg = WalkForwardConfig()
    portfolio_cfg = PortfolioConfig()

    # ---- Bước 3: backtest mặc định ----
    log.info("[3/7] Backtest cấu hình Donchian-55 mặc định")
    default = default_backtest(bank, cfg)

    # ---- Bước 4: ablation ----
    ablation = None
    if not args.no_ablation:
        log.info("[4/7] Phân tích loại bỏ các ràng buộc Việt Nam")
        ablation = run_ablation(bank, cfg)

    # ---- Bước 5: GA theo mã + OOS ----
    ga_symbol = None
    if not args.no_ga:
        log.info("[5/7] GA theo từng mã (train %.0f%%, OOS %.0f%%)", args.split * 100, (1 - args.split) * 100)
        ga_symbol = run_per_symbol_ga(bank, cfg, space, ga_cfg, split=args.split, n_jobs=args.jobs)

    # ---- Bước 6: GA rổ mã ----
    basket = None
    if not args.no_ga:
        log.info("[6/7] GA trên rổ mã cho danh mục")
        basket = run_basket_ga(bank, cfg, space, ga_cfg, split=args.split)

    # ---- Bước 7: danh mục + walk-forward ----
    log.info("[7/7] Mô phỏng danh mục")
    portfolio = run_portfolio_suite(
        bank, cfg, portfolio_cfg, basket_params=(basket or {}).get("best")
    )

    wf = None
    if not args.no_walkforward:
        log.info("[7/7] Walk-forward 252/63")
        wf = run_walkforward(bank, cfg, wf_cfg, wf_ga_cfg, n_jobs=args.jobs)

    log.info("Quét lưới entry_window cho bản đồ nhiệt")
    heatmap = parameter_heatmap(bank, cfg, split=args.split)

    # ---- Kết xuất ----
    liq = liquidity_report(bank, cfg.strategy.adv_min)
    coverage = liquidity_coverage(bank)
    adv_map = {r["symbol"]: r["adv_median_1y"] for r in liq.to_dict("records")}
    last_price = {
        s: float(bank.panel.close[-1, j]) for s, j in bank.panel.symbol_index.items()
    }
    bench_norm = bank_meta.pop("bench_close", None)

    symbol_rows = build_symbol_rows(
        default["results"],
        ga_rows=(ga_symbol or {}).get("per_symbol"),
        adv=adv_map,
        last_price=last_price,
    )
    curves = build_curves(bank, default["results"], portfolio, benchmark=bench_norm)
    portfolio_payload = build_portfolio_payload(portfolio)
    ga_payload = build_ga_payload(ga_symbol, basket)
    wf_payload = build_walkforward_payload(wf)
    ablation_payload = build_ablation_payload(ablation)

    repo_url = "https://github.com/vnidata/BuBu-Trading"
    meta = build_meta(
        bank_meta=bank_meta,
        cfg=cfg,
        ga_cfg=ga_cfg,
        wf_cfg=wf_cfg,
        portfolio_cfg=portfolio_cfg,
        space=space,
        symbol_summary=default["summary"],
        ga_summary=(ga_symbol or {}).get("summary"),
        portfolio_payload=portfolio_payload,
        wf_payload=wf_payload,
        git_sha=git_sha(),
        repo_url=repo_url,
        pages_url="https://vnidata.github.io/BuBu-Trading/",
        runtime_seconds=time.time() - t_start,
    )

    # Chỉ số mua-và-giữ của chỉ số tham chiếu để đối chiếu trực tiếp với danh mục
    if bench_norm is not None:
        bm = equity_metrics(np.asarray(bench_norm, dtype=float), cfg.trading_days)
        meta["headline"].update(
            benchmark_symbol=cfg and bank_meta.get("benchmark", "VNINDEX"),
            benchmark_cagr=round(bm["cagr"], 4),
            benchmark_sharpe=round(bm["sharpe"], 4),
            benchmark_max_dd=round(bm["max_dd"], 4),
            benchmark_calmar=round(bm["calmar"], 4),
            portfolio_excess_cagr=round(
                float(portfolio_payload.get("default", {}).get("metrics", {}).get("cagr", 0.0)) - bm["cagr"], 4
            ),
        )
        if ga_payload.get("basket"):
            meta["headline"]["ga_basket_params"] = ga_payload["basket"].get("best")

    files = write_site_data(
        meta=meta,
        symbol_rows=symbol_rows,
        curves=curves,
        portfolio_payload=portfolio_payload,
        ga_payload=ga_payload,
        walkforward_payload=wf_payload,
        ablation_payload=ablation_payload,
        heatmap=heatmap,
        liquidity={"symbols": liq.to_dict("records"), "coverage": coverage},
    )

    # Bản đầy đủ lưu trong results/ (nén) để tái lập và kiểm toán
    write_json_gz(
        {
            "meta": meta,
            "default_summary": default["summary"],
            "symbol_rows": symbol_rows,
            "ablation": ablation,
            "ga_symbol_summary": (ga_symbol or {}).get("summary"),
            "ga_basket": basket,
            "portfolio_metrics": {k: v["metrics"] | v["trade_stats"] for k, v in portfolio.items()},
            "walkforward_summary": (wf or {}).get("summary"),
            "heatmap": heatmap,
            "liquidity": liq.to_dict("records"),
        },
        RESULTS_DIR / "research_full.json.gz",
    )

    log.info("Hoàn tất trong %.0f giây. %d tệp dữ liệu website.", time.time() - t_start, len(files))
    print("\n=== KẾT QUẢ CHÍNH ===")
    for k, v in meta["headline"].items():
        print(f"  {k:38s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
