"""Điều phối toàn bộ pipeline nghiên cứu DuDu-Trading.

Bảy bước theo quy trình triển khai:

1. Chọn universe (VN100) và lọc thanh khoản ADV ≥ 30 tỷ/phiên.
2. Dựng panel OHLCV và ngân hàng đặc trưng.
3. Backtest cấu hình Donchian-55 mặc định trên toàn bộ universe.
4. Phân tích loại bỏ (ablation) để đo đóng góp từng ràng buộc Việt Nam.
5. GA tối ưu tham số theo từng mã, kiểm định out-of-sample 30% dữ liệu cuối.
6. GA trên rổ mã để chọn một bộ tham số dùng chung cho danh mục.
7. Walk-forward 252/63 và mô phỏng danh mục chia sẻ vốn.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .backtest import run_panel, run_symbol_window, simulate_portfolio
from .config import (
    BENCHMARK_SYMBOL,
    DATA_START,
    GAConfig,
    ParamSpace,
    PortfolioConfig,
    WalkForwardConfig,
    BacktestConfig,
)
from .data import CachePolicy, PricePanel, compute_adv, load_benchmark, load_many
from .ga import Genome, GAResult, evaluate_genome, run_ga
from .indicators import FeatureBank, build_market_regime
from .metrics import summarize
from .utils import safe_float, utc_now_iso
from .walkforward import run_walkforward_panel

log = logging.getLogger(__name__)

ENTRY_GRID = list(range(40, 71))
EXIT_GRID = list(range(15, 26))
ATR_GRID = list(range(14, 26))


# --------------------------------------------------------------------------
# Bước 1-2: dữ liệu và đặc trưng
# --------------------------------------------------------------------------
def build_bank(
    symbols: Sequence[str],
    start: str = DATA_START,
    end: str | None = None,
    benchmark: str = BENCHMARK_SYMBOL,
    market_sma: int = 200,
    adv_window: int = 20,
    refresh: bool = False,
    sleep_between: float = 0.0,
) -> tuple[FeatureBank, dict[str, Any]]:
    """Tải dữ liệu, dựng PricePanel và FeatureBank."""
    t0 = time.time()
    policy = CachePolicy(refresh=refresh, sleep_between=sleep_between)
    data = load_many(symbols, start=start, end=end, policy=policy)
    bench = load_benchmark(benchmark, start="2016-01-01", end=end, policy=policy)
    panel = PricePanel(data)
    close_bench = bench.set_index("time")["close"].reindex(panel.dates).ffill().to_numpy()
    regime_1d = build_market_regime(close_bench, market_sma)
    regime = np.repeat(regime_1d[:, None], len(panel.symbols), axis=1)
    adv = compute_adv(panel, adv_window)
    bank = FeatureBank(panel, ENTRY_GRID, EXIT_GRID, ATR_GRID, adv=adv, regime=regime)
    meta = {
        "symbols": list(panel.symbols),
        "n_symbols": len(panel.symbols),
        "n_sessions": len(panel.dates),
        "date_start": str(panel.dates[0].date()),
        "date_end": str(panel.dates[-1].date()),
        "benchmark": benchmark,
        "bench_close": close_bench,
        "regime_share": safe_float(float(np.mean(regime_1d))),
        "build_seconds": round(time.time() - t0, 1),
    }
    log.info(
        "FeatureBank: %d mã, %d phiên (%s -> %s) trong %.1fs",
        meta["n_symbols"],
        meta["n_sessions"],
        meta["date_start"],
        meta["date_end"],
        meta["build_seconds"],
    )
    return bank, meta


def liquidity_report(bank: FeatureBank, min_adv: float = 30e9) -> pd.DataFrame:
    """ADV bình quân 20 phiên gần nhất của từng mã, kèm cờ đạt ngưỡng."""
    adv = np.nanmedian(bank.adv[-252:, :], axis=0)
    price = bank.panel.close[-1, :]
    rows = [
        {
            "symbol": sym,
            "adv_median_1y": safe_float(adv[j]),
            "adv_billion": safe_float(adv[j] / 1e9),
            "last_price": safe_float(price[j]),
            "passes_adv": bool(safe_float(adv[j]) >= min_adv),
        }
        for j, sym in enumerate(bank.panel.symbols)
    ]
    return pd.DataFrame(rows).sort_values("adv_median_1y", ascending=False).reset_index(drop=True)


def liquidity_coverage(bank: FeatureBank, thresholds: Sequence[float] = (10e9, 30e9, 50e9)) -> dict[str, Any]:
    """Tỷ lệ symbol-day đạt từng ngưỡng ADV, theo năm và theo mã.

    Đây là bằng chứng định lượng cho luận điểm "thanh khoản phân tán": một
    ngưỡng tuyệt đối 30 tỷ/phiên gần như khoá toàn bộ tín hiệu giai đoạn
    2016-2019 và chỉ mở dần từ 2021.
    """
    adv = bank.adv
    years = pd.DatetimeIndex(bank.panel.dates).year
    finite = np.isfinite(adv)
    by_year: list[dict[str, Any]] = []
    for y in sorted(set(int(v) for v in years)):
        mask = (years == y)[:, None] & finite
        if not mask.any():
            continue
        row: dict[str, Any] = {"year": y, "symbol_days": int(mask.sum())}
        for th in thresholds:
            row[f"share_adv_{int(th / 1e9)}bn"] = safe_float(float(np.mean((adv >= th)[mask])))
        by_year.append(row)
    per_symbol = [
        {
            "symbol": sym,
            "share_adv_30bn": safe_float(float(np.mean((adv[:, j] >= 30e9)[finite[:, j]]))) if finite[:, j].any() else 0.0,
            "adv_median": safe_float(float(np.nanmedian(adv[:, j]))),
        }
        for j, sym in enumerate(bank.panel.symbols)
    ]
    return {
        "thresholds_billion": [int(t / 1e9) for t in thresholds],
        "by_year": by_year,
        "per_symbol": sorted(per_symbol, key=lambda r: -r["share_adv_30bn"]),
        "overall": {
            f"share_adv_{int(t / 1e9)}bn": safe_float(float(np.mean((adv >= t)[finite]))) for t in thresholds
        },
    }


# --------------------------------------------------------------------------
# Bước 3: backtest cấu hình mặc định
# --------------------------------------------------------------------------
def default_backtest(bank: FeatureBank, cfg: BacktestConfig) -> dict[str, Any]:
    results = run_panel(bank, cfg, close_open_at_end=True)
    per_symbol = {s: r.to_summary() for s, r in results.items()}
    return {
        "per_symbol": per_symbol,
        "summary": summarize(per_symbol),
        "params": cfg.strategy.to_dict(),
        "results": results,
    }


# --------------------------------------------------------------------------
# Bước 4: ablation các ràng buộc Việt Nam
# --------------------------------------------------------------------------
ABLATION_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("full", {"label": "Đầy đủ ràng buộc Việt Nam (ADV ≥ 30 tỷ)"}),
    ("no_market_filter", {"label": "Bỏ lọc VN-Index > SMA200", "use_market_filter": False}),
    ("adv_10bn", {"label": "Nới ADV xuống 10 tỷ/phiên", "adv_min": 10e9}),
    ("no_adv_filter", {"label": "Bỏ hẳn lọc thanh khoản ADV", "adv_min": 0.0}),
    ("no_ceiling_rule", {"label": "Bỏ luật tránh giá trần", "avoid_ceiling_entry": False}),
    ("no_t2_lock", {"label": "Bỏ khoá T+2.5 (bán ngay)", "_settlement_lag": 0}),
    ("no_pyramid", {"label": "Không gia tăng Unit", "max_units": 1}),
    ("s1_fast", {"label": "Turtle S1 (entry 20, exit 10)", "entry_window": 20, "exit_window": 10}),
    ("unfiltered", {
        "label": "Bỏ toàn bộ bộ lọc Việt Nam (long-only thuần)",
        "use_market_filter": False,
        "adv_min": 0.0,
        "avoid_ceiling_entry": False,
        "block_floor_exit": False,
    }),
]


def run_ablation(bank: FeatureBank, cfg: BacktestConfig) -> list[dict[str, Any]]:
    """Đo đóng góp của từng ràng buộc đặc thù thị trường Việt Nam."""
    out: list[dict[str, Any]] = []
    for key, spec in ABLATION_VARIANTS:
        strat = replace(cfg.strategy, **{k: v for k, v in spec.items() if k != "label" and not k.startswith("_")})
        market = cfg.market
        if spec.get("_settlement_lag") == 0:
            market = replace(cfg.market, settlement_lag=0)
        sub = replace(cfg, strategy=strat, market=market)
        res = run_panel(bank, sub, close_open_at_end=True)
        per_symbol = {s: r.to_summary() for s, r in res.items()}
        summary = summarize(per_symbol)
        out.append(
            {
                "key": key,
                "label": spec["label"],
                "params": strat.to_dict(),
                "summary": summary,
                "calmar_median": safe_float(summary.get("calmar", {}).get("median", 0.0)),
                "sharpe_median": safe_float(summary.get("sharpe", {}).get("median", 0.0)),
                "cagr_median": safe_float(summary.get("cagr", {}).get("median", 0.0)),
                "max_dd_median": safe_float(summary.get("max_dd", {}).get("median", 0.0)),
                "trades_per_year_median": safe_float(summary.get("trades_per_year", {}).get("median", 0.0)),
                "cagr_positive_share": safe_float(summary.get("cagr", {}).get("positive_share", 0.0)),
            }
        )
        log.info("Ablation %-18s Calmar(med) %6.2f  Sharpe(med) %6.2f", key, out[-1]["calmar_median"], out[-1]["sharpe_median"])
    return out


# --------------------------------------------------------------------------
# Bước 5: GA theo từng mã + kiểm định out-of-sample
# --------------------------------------------------------------------------
_CTX: dict[str, Any] = {}


def _init_ctx(bank: FeatureBank, cfg: BacktestConfig, space: ParamSpace, ga_cfg: GAConfig, split: float) -> None:
    _CTX.clear()
    _CTX.update(bank=bank, cfg=cfg, space=space, ga_cfg=ga_cfg, split=split, n=bank.n_dates())


def _symbol_ga_task(symbol: str) -> dict[str, Any]:
    bank: FeatureBank = _CTX["bank"]
    cfg: BacktestConfig = _CTX["cfg"]
    space: ParamSpace = _CTX["space"]
    ga_cfg: GAConfig = _CTX["ga_cfg"]
    n: int = _CTX["n"]
    cut = int(n * _CTX["split"])

    ga: GAResult = run_ga(bank, [symbol], 0, cut, cfg, space=space, ga_cfg=ga_cfg, aggregate="median")
    best = ga.best
    is_cfg = replace(cfg, strategy=best.to_params(cfg.strategy))
    is_res = run_symbol_window(bank, symbol, 0, cut, is_cfg, True)
    oos_res = run_symbol_window(bank, symbol, cut, n, is_cfg, True)
    base_cfg = replace(cfg, strategy=cfg.strategy)
    base_is = run_symbol_window(bank, symbol, 0, cut, base_cfg, True)
    base_oos = run_symbol_window(bank, symbol, cut, n, base_cfg, True)

    def pack(r) -> dict[str, float]:
        d = dict(r.metrics)
        d.update(r.trade_stats)
        return d

    is_m, oos_m = pack(is_res), pack(oos_res)
    oos_base = pack(base_oos)
    accepted = (
        safe_float(oos_m.get("calmar")) > 0.5
        and safe_float(oos_m.get("trades_per_year")) < 20
        and safe_float(oos_m.get("trades")) > 0
        and oos_res.equity[-1] > 0
    )
    return {
        "symbol": symbol,
        "split_index": cut,
        "ga": {
            "best": best.to_dict(),
            "best_outcome": ga.best_outcome.to_dict(),
            "history": ga.history,
            "population": ga.population,
            "evaluations": ga.evaluations,
            "generations": ga.generations,
        },
        "in_sample": is_m,
        "out_of_sample": oos_m,
        "baseline_in_sample": pack(base_is),
        "baseline_out_of_sample": oos_base,
        "oos_accepted": bool(accepted),
        "overfit_gap_calmar": safe_float(is_m.get("calmar", 0) - oos_m.get("calmar", 0)),
    }


def run_per_symbol_ga(
    bank: FeatureBank,
    cfg: BacktestConfig,
    space: ParamSpace | None = None,
    ga_cfg: GAConfig | None = None,
    split: float = 0.7,
    n_jobs: int = 10,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """GA riêng cho từng mã: tối ưu trên 70% đầu, kiểm định trên 30% cuối."""
    space = space or ParamSpace()
    ga_cfg = ga_cfg or GAConfig()
    syms = list(symbols or bank.panel.symbols)
    n = bank.n_dates()
    cut = int(n * split)
    log.info("GA theo mã: %d mã, train %d phiên, OOS %d phiên", len(syms), cut, n - cut)

    t0 = time.time()
    if n_jobs <= 1 or len(syms) == 1:
        _init_ctx(bank, cfg, space, ga_cfg, split)
        rows = [_symbol_ga_task(s) for s in syms]
    else:
        with ProcessPoolExecutor(
            max_workers=n_jobs, initializer=_init_ctx, initargs=(bank, cfg, space, ga_cfg, split)
        ) as ex:
            rows = list(ex.map(_symbol_ga_task, syms, chunksize=1))

    oos_calmar = np.array([safe_float(r["out_of_sample"].get("calmar")) for r in rows])
    is_calmar = np.array([safe_float(r["in_sample"].get("calmar")) for r in rows])
    base_oos_calmar = np.array([safe_float(r["baseline_out_of_sample"].get("calmar")) for r in rows])
    accepted = sum(1 for r in rows if r["oos_accepted"])
    summary = {
        "n_symbols": len(rows),
        "train_sessions": cut,
        "oos_sessions": n - cut,
        "split": split,
        "accepted_symbols": accepted,
        "acceptance_rate": safe_float(accepted / len(rows)) if rows else 0.0,
        "is_calmar_median": safe_float(np.median(is_calmar)) if rows else 0.0,
        "oos_calmar_median": safe_float(np.median(oos_calmar)) if rows else 0.0,
        "oos_calmar_positive_share": safe_float((oos_calmar > 0).mean()) if rows else 0.0,
        "oos_calmar_gt_0_5_share": safe_float((oos_calmar > 0.5).mean()) if rows else 0.0,
        "baseline_oos_calmar_median": safe_float(np.median(base_oos_calmar)) if rows else 0.0,
        "ga_edge_oos_calmar": safe_float(np.median(oos_calmar) - np.median(base_oos_calmar)) if rows else 0.0,
        "overfit_gap_median": safe_float(np.median([r["overfit_gap_calmar"] for r in rows])) if rows else 0.0,
        "runtime_seconds": round(time.time() - t0, 1),
    }
    log.info(
        "GA theo mã xong trong %.0fs: chấp nhận %d/%d (%.1f%%), OOS Calmar trung vị %.2f",
        summary["runtime_seconds"],
        accepted,
        len(rows),
        100 * summary["acceptance_rate"],
        summary["oos_calmar_median"],
    )
    return {"per_symbol": {r["symbol"]: r for r in rows}, "summary": summary}


# --------------------------------------------------------------------------
# Bước 6: GA trên rổ mã (một bộ tham số dùng chung cho danh mục)
# --------------------------------------------------------------------------
def run_basket_ga(
    bank: FeatureBank,
    cfg: BacktestConfig,
    space: ParamSpace | None = None,
    ga_cfg: GAConfig | None = None,
    split: float = 0.7,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    space = space or ParamSpace()
    ga_cfg = ga_cfg or GAConfig()
    syms = list(symbols or bank.panel.symbols)
    n = bank.n_dates()
    cut = int(n * split)
    t0 = time.time()
    ga = run_ga(bank, syms, 0, cut, cfg, space=space, ga_cfg=ga_cfg, aggregate="trimmed")
    best_cfg = replace(cfg, strategy=ga.best.to_params(cfg.strategy))
    oos = {}
    for s in syms:
        r = run_symbol_window(bank, s, cut, n, best_cfg, True)
        d = dict(r.metrics)
        d.update(r.trade_stats)
        oos[s] = d
    base_cfg = replace(cfg, strategy=cfg.strategy)
    base_oos = {}
    for s in syms:
        r = run_symbol_window(bank, s, cut, n, base_cfg, True)
        d = dict(r.metrics)
        d.update(r.trade_stats)
        base_oos[s] = d
    out = {
        "best": ga.best.to_dict(),
        "best_outcome": ga.best_outcome.to_dict(),
        "history": ga.history,
        "population": ga.population,
        "evaluations": ga.evaluations,
        "generations": ga.generations,
        "train_sessions": cut,
        "oos_sessions": n - cut,
        "oos_summary": summarize({s: {**oos[s], "symbol": s} for s in oos}),
        "baseline_oos_summary": summarize({s: {**base_oos[s], "symbol": s} for s in base_oos}),
        "runtime_seconds": round(time.time() - t0, 1),
    }
    log.info(
        "GA rổ mã: Calmar(train) %.2f, OOS Calmar trung vị %.2f (mặc định %.2f) trong %.0fs",
        ga.best_outcome.calmar,
        safe_float(out["oos_summary"].get("calmar", {}).get("median", 0)),
        safe_float(out["baseline_oos_summary"].get("calmar", {}).get("median", 0)),
        out["runtime_seconds"],
    )
    return out


# --------------------------------------------------------------------------
# Bước 7: danh mục
# --------------------------------------------------------------------------
def run_portfolio_suite(
    bank: FeatureBank,
    cfg: BacktestConfig,
    portfolio_cfg: PortfolioConfig,
    basket_params: dict[str, float] | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    syms = list(symbols or bank.panel.symbols)
    out: dict[str, Any] = {}
    variants: list[tuple[str, BacktestConfig]] = [("default", cfg)]
    if basket_params:
        variants.append(("ga_basket", replace(cfg, strategy=cfg.strategy.from_dict(basket_params))))
    for key, sub in variants:
        res = simulate_portfolio(bank, sub, portfolio_cfg, symbols=syms, close_open_at_end=True)
        out[key] = {
            "metrics": res["metrics"],
            "trade_stats": res["trade_stats"],
            "dates": res["dates"],
            "equity": res["equity"],
            "exposure": res["exposure"],
            "drawdown": res["drawdown"],
            "trades": res["trades"],
            "params": sub.strategy.to_dict(),
        }
        log.info(
            "Danh mục %-10s CAGR %6.2f%%  Sharpe %5.2f  MaxDD %6.2f%%  trades %d (%.1f/năm)",
            key,
            res["metrics"]["cagr"] * 100,
            res["metrics"]["sharpe"],
            res["metrics"]["max_dd"] * 100,
            res["trade_stats"]["trades"],
            res["trade_stats"]["trades_per_year"],
        )
    return out


# --------------------------------------------------------------------------
# Bước 7b: walk-forward
# --------------------------------------------------------------------------
def run_walkforward(
    bank: FeatureBank,
    cfg: BacktestConfig,
    wf_cfg: WalkForwardConfig | None = None,
    ga_cfg: GAConfig | None = None,
    n_jobs: int = 10,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    wf_cfg = wf_cfg or WalkForwardConfig()
    syms = list(symbols or bank.panel.symbols)
    log.info("Walk-forward: %d mã, train %d phiên, test %d phiên", len(syms), wf_cfg.train_sessions, wf_cfg.test_sessions)
    return run_walkforward_panel(bank, syms, cfg, wf_cfg, ParamSpace(), ga_cfg, n_jobs=n_jobs)


# --------------------------------------------------------------------------
# Bước 4b: quét tham số cho bản đồ nhiệt
# --------------------------------------------------------------------------
def parameter_heatmap(
    bank: FeatureBank,
    cfg: BacktestConfig,
    split: float = 0.7,
    exit_window: int = 20,
    atr_period: int = 20,
    symbols: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    syms = list(symbols or bank.panel.symbols)
    n = bank.n_dates()
    cut = int(n * split)
    cfg_ga = GAConfig()
    rows: list[dict[str, Any]] = []
    for w in ENTRY_GRID:
        gen = Genome(entry_window=w, exit_window=exit_window, atr_period=atr_period)
        out = evaluate_genome(bank, syms, gen, 0, cut, cfg, cfg_ga, aggregate="trimmed")
        rows.append({"entry_window": w, **out.to_dict()})
    return rows
