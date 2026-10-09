"""Kết xuất kết quả nghiên cứu thành dữ liệu cho website GitHub Pages.

Nguyên tắc: website chỉ đọc JSON tĩnh, không có backend. Mọi phép tính nặng
đều nằm ở tầng Python. Dữ liệu được làm mảnh (downsample) theo tuần để tổng
dung lượng trang ở mức vài trăm KB, phù hợp giới hạn GitHub Pages.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .config import (
    BacktestConfig,
    GAConfig,
    ParamSpace,
    PortfolioConfig,
    SITE_DATA_DIR,
    WalkForwardConfig,
)
from .metrics import monthly_returns_table
from .utils import safe_float, utc_now_iso, write_json

log = logging.getLogger(__name__)

ROUND = 4


def _r(x: Any, nd: int = ROUND) -> float:
    v = safe_float(x)
    return round(v, nd)


def downsample(dates: Sequence[Any], values: np.ndarray, step: int = 5) -> tuple[list[str], list[float]]:
    """Làm mảnh chuỗi theo tuần, luôn giữ điểm cuối."""
    n = len(values)
    if n == 0:
        return [], []
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return [str(pd.Timestamp(dates[i]).date()) for i in idx], [_r(values[i], 4) for i in idx]


def normalize(equity: np.ndarray, base: float = 100.0) -> np.ndarray:
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0 or eq[0] <= 0:
        return eq
    return eq / eq[0] * base


def build_curves(
    bank,
    symbol_results: dict[str, Any],
    portfolio: dict[str, Any],
    step: int = 5,
    benchmark: np.ndarray | None = None,
) -> dict[str, Any]:
    """Chuẩn hoá đường vốn của mọi mã về cùng gốc 100 để vẽ biểu đồ."""
    dates = bank.panel.dates
    series: dict[str, list[float]] = {}
    index_dates: list[str] = []
    for sym, res in symbol_results.items():
        eq = normalize(res.equity)
        d, v = downsample(dates, eq, step)
        if not index_dates:
            index_dates = d
        series[sym] = v

    out: dict[str, Any] = {"dates": index_dates, "symbols": series}
    if benchmark is not None:
        d, v = downsample(dates, normalize(benchmark), step)
        out["benchmark"] = v
        out["benchmark_dates"] = d
    for key, payload in portfolio.items():
        d, v = downsample(payload["dates"], normalize(payload["equity"]), step)
        out[f"portfolio_{key}"] = v
        out.setdefault("portfolio_dates", d)
    return out


def build_symbol_rows(
    symbol_results: dict[str, Any],
    ga_rows: dict[str, Any] | None = None,
    adv: dict[str, float] | None = None,
    last_price: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Bảng kết quả theo mã, kèm kết quả GA và trạng thái kiểm định OOS."""
    ga_rows = ga_rows or {}
    adv = adv or {}
    last_price = last_price or {}
    rows: list[dict[str, Any]] = []
    for sym, res in symbol_results.items():
        m = res.metrics
        t = res.trade_stats
        row: dict[str, Any] = {
            "symbol": sym,
            "adv_billion": _r(adv.get(sym, 0.0), 1),
            "last_price": _r(last_price.get(sym, 0.0), 0),
            "cagr": _r(m.get("cagr", 0)),
            "sharpe": _r(m.get("sharpe", 0)),
            "sortino": _r(m.get("sortino", 0)),
            "calmar": _r(m.get("calmar", 0)),
            "max_dd": _r(m.get("max_dd", 0)),
            "max_dd_duration": _r(m.get("max_dd_duration", 0), 0),
            "vol_annual": _r(m.get("vol_annual", 0)),
            "avg_exposure": _r(m.get("avg_exposure", 0)),
            "trades": int(t.get("trades", 0)),
            "trades_per_year": _r(t.get("trades_per_year", 0), 2),
            "hit_rate": _r(t.get("hit_rate", 0)),
            "profit_factor": _r(t.get("profit_factor", 0), 2),
            "avg_r": _r(t.get("avg_r", 0), 2),
            "best_r": _r(t.get("best_r", 0), 2),
            "worst_r": _r(t.get("worst_r", 0), 2),
            "avg_holding_days": _r(t.get("avg_holding_days", 0), 0),
            "max_consecutive_losses": int(t.get("max_consecutive_losses", 0)),
            "total_fees_pct": _r(t.get("total_fees", 0) / 1e9, 4),
        }
        g = ga_rows.get(sym)
        if g:
            row["ga_params"] = {k: _r(v, 4) for k, v in g["ga"]["best"].items()}
            row["ga_in_sample"] = {
                "cagr": _r(g["in_sample"].get("cagr", 0)),
                "sharpe": _r(g["in_sample"].get("sharpe", 0)),
                "calmar": _r(g["in_sample"].get("calmar", 0)),
                "max_dd": _r(g["in_sample"].get("max_dd", 0)),
                "trades_per_year": _r(g["in_sample"].get("trades_per_year", 0), 2),
            }
            row["ga_out_of_sample"] = {
                "cagr": _r(g["out_of_sample"].get("cagr", 0)),
                "sharpe": _r(g["out_of_sample"].get("sharpe", 0)),
                "calmar": _r(g["out_of_sample"].get("calmar", 0)),
                "max_dd": _r(g["out_of_sample"].get("max_dd", 0)),
                "profit_factor": _r(g["out_of_sample"].get("profit_factor", 0), 2),
                "hit_rate": _r(g["out_of_sample"].get("hit_rate", 0)),
                "trades_per_year": _r(g["out_of_sample"].get("trades_per_year", 0), 2),
            }
            row["baseline_out_of_sample"] = {
                "cagr": _r(g["baseline_out_of_sample"].get("cagr", 0)),
                "sharpe": _r(g["baseline_out_of_sample"].get("sharpe", 0)),
                "calmar": _r(g["baseline_out_of_sample"].get("calmar", 0)),
                "max_dd": _r(g["baseline_out_of_sample"].get("max_dd", 0)),
                "trades_per_year": _r(g["baseline_out_of_sample"].get("trades_per_year", 0), 2),
            }
            row["overfit_gap_calmar"] = _r(g["overfit_gap_calmar"])
            row["oos_accepted"] = bool(g["oos_accepted"])
        rows.append(row)
    return sorted(rows, key=lambda r: -r["calmar"])


def build_distribution(values: Iterable[float], bins: int = 24, lo: float | None = None, hi: float | None = None) -> dict[str, Any]:
    arr = np.array([safe_float(v) for v in values], dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"edges": [], "counts": []}
    lo = float(arr.min()) if lo is None else lo
    hi = float(arr.max()) if hi is None else hi
    if hi - lo < 1e-9:
        hi = lo + 1.0
    counts, edges = np.histogram(arr, bins=bins, range=(lo, hi))
    return {
        "edges": [round(float(e), 4) for e in edges],
        "counts": [int(c) for c in counts],
        "mean": round(float(arr.mean()), 4),
        "median": round(float(np.median(arr)), 4),
        "p25": round(float(np.percentile(arr, 25)), 4),
        "p75": round(float(np.percentile(arr, 75)), 4),
        "n": int(arr.size),
    }


def build_ga_payload(per_symbol_ga: dict[str, Any] | None, basket_ga: dict[str, Any] | None, top_n: int = 12) -> dict[str, Any]:
    """Gói dữ liệu GA cho website: hội tụ, quần thể, tham số tối ưu."""
    out: dict[str, Any] = {"symbols": {}, "basket": None}
    if per_symbol_ga:
        rows = per_symbol_ga.get("per_symbol", {})
        ranked = sorted(rows.values(), key=lambda r: -safe_float(r["out_of_sample"].get("calmar")))[:top_n]
        for r in ranked:
            out["symbols"][r["symbol"]] = {
                "best": {k: _r(v, 4) for k, v in r["ga"]["best"].items()},
                "history": [
                    {k: _r(v, 4) for k, v in h.items()} for h in r["ga"]["history"]
                ],
                "population": [
                    {"genome": {k: _r(v, 4) for k, v in p["genome"].items()}, **{k: _r(v, 4) for k, v in p.items() if k != "genome"}}
                    for p in r["ga"]["population"][:24]
                ],
                "evaluations": r["ga"]["evaluations"],
                "in_sample": {k: _r(v, 4) for k, v in r["in_sample"].items()},
                "out_of_sample": {k: _r(v, 4) for k, v in r["out_of_sample"].items()},
                "baseline_out_of_sample": {k: _r(v, 4) for k, v in r["baseline_out_of_sample"].items()},
                "oos_accepted": r["oos_accepted"],
            }
        out["summary"] = per_symbol_ga.get("summary", {})
    if basket_ga:
        out["basket"] = {
            "best": {k: _r(v, 4) for k, v in basket_ga["best"].items()},
            "best_outcome": {k: _r(v, 4) for k, v in basket_ga["best_outcome"].items()},
            "history": [{k: _r(v, 4) for k, v in h.items()} for h in basket_ga["history"]],
            "population": [
                {"genome": {k: _r(v, 4) for k, v in p["genome"].items()}, **{k: _r(v, 4) for k, v in p.items() if k != "genome"}}
                for p in basket_ga["population"][:24]
            ],
            "evaluations": basket_ga["evaluations"],
            "generations": basket_ga["generations"],
            "oos_summary": basket_ga["oos_summary"],
            "baseline_oos_summary": basket_ga["baseline_oos_summary"],
            "runtime_seconds": basket_ga["runtime_seconds"],
        }
    return out


def build_walkforward_payload(wf: dict[str, Any] | None, max_folds: int = 260) -> dict[str, Any]:
    """Gói dữ liệu walk-forward.

    Bảng fold phải trải đều trên nhiều mã. `wf["folds"]` là danh sách nối tiếp
    theo từng mã, nên nếu chỉ cắt `[:N]` thì toàn bộ bảng sẽ chỉ thuộc về một
    mã duy nhất; hàm này lấy mẫu round-robin theo mã.
    """
    if not wf:
        return {}
    folds = wf.get("folds", [])
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for f in folds:
        by_symbol.setdefault(str(f.get("symbol", "?")), []).append(f)
    sampled: list[dict[str, Any]] = []
    depth = 0
    while len(sampled) < max_folds and by_symbol:
        added = False
        for bucket in by_symbol.values():
            if depth < len(bucket):
                sampled.append(bucket[depth])
                added = True
                if len(sampled) >= max_folds:
                    break
        if not added:
            break
        depth += 1

    traded_folds = [f for f in folds if safe_float(f["test"].get("trades")) > 0]
    tr_all = np.array([safe_float(f["test"].get("total_return")) for f in folds], dtype=float)
    tr_traded = np.array([safe_float(f["test"].get("total_return")) for f in traded_folds], dtype=float)
    base_tr = np.array([safe_float(f["test_baseline"].get("total_return")) for f in folds], dtype=float)

    summary = dict(wf.get("summary", {}))
    # Calmar trên cửa sổ test 63 phiên cực kỳ nhiễu (CAGR nội suy từ 3 tháng chia
    # cho một MaxDD rất nhỏ). Lợi nhuận tuyệt đối của chính cửa sổ test là thước đo
    # ổn định và dễ diễn giải hơn, nên được bổ sung vào phần tổng hợp.
    summary.update(
        oos_total_return_median=safe_float(np.median(tr_all)) if tr_all.size else 0.0,
        oos_total_return_mean=safe_float(tr_all.mean()) if tr_all.size else 0.0,
        oos_total_return_positive_share=safe_float((tr_all > 0).mean()) if tr_all.size else 0.0,
        oos_total_return_median_traded=safe_float(np.median(tr_traded)) if tr_traded.size else 0.0,
        oos_total_return_positive_share_traded=safe_float((tr_traded > 0).mean()) if tr_traded.size else 0.0,
        baseline_total_return_median=safe_float(np.median(base_tr)) if base_tr.size else 0.0,
        ga_edge_total_return_traded=safe_float(tr_traded.mean() - np.mean([
            safe_float(f["test_baseline"].get("total_return")) for f in traded_folds
        ])) if tr_traded.size else 0.0,
    )

    return {
        "summary": summary,
        "per_symbol": wf.get("per_symbol", {}),
        "symbols_run": wf.get("symbols_run", []),
        "folds": [
            {
                "fold": f["fold"],
                "symbol": f.get("symbol", "?"),
                "train_start": f["train_start"],
                "train_end": f["train_end"],
                "test_start": f["test_start"],
                "test_end": f["test_end"],
                "params": {k: _r(v, 4) for k, v in f["params"].items()},
                "train_calmar": _r(f["train"].get("calmar", 0)),
                "train_sharpe": _r(f["train"].get("sharpe", 0)),
                "test_return": _r(f["test"].get("total_return", 0)),
                "test_calmar": _r(f["test"].get("calmar", 0)),
                "test_sharpe": _r(f["test"].get("sharpe", 0)),
                "test_max_dd": _r(f["test"].get("max_dd", 0)),
                "test_cagr": _r(f["test"].get("cagr", 0)),
                "test_trades": int(safe_float(f["test"].get("trades", 0))),
                "test_trades_per_year": _r(f["test"].get("trades_per_year", 0), 2),
                "baseline_calmar": _r(f["test_baseline"].get("calmar", 0)),
                "baseline_return": _r(f["test_baseline"].get("total_return", 0)),
                "accepted": bool(f["accepted"]),
            }
            for f in sampled
        ],
        "distributions": {
            "oos_total_return": build_distribution(tr_all, bins=28),
            "oos_calmar": build_distribution([f["test"].get("calmar", 0) for f in folds], bins=28),
            "oos_sharpe": build_distribution([f["test"].get("sharpe", 0) for f in folds], bins=28),
            "oos_max_dd": build_distribution([f["test"].get("max_dd", 0) for f in folds], bins=28),
            "is_calmar": build_distribution([f["train"].get("calmar", 0) for f in folds], bins=28),
            "baseline_calmar": build_distribution([f["test_baseline"].get("calmar", 0) for f in folds], bins=28),
        },
        # Phân phối có điều kiện: chỉ tính các fold thực sự phát sinh lệnh, tránh
        # cột spike tại 0 gây ra bởi các fold không giao dịch.
        "distributions_traded": {
            k: build_distribution(
                [f["test"].get(v, 0) for f in traded_folds], bins=24
            )
            for k, v in (
                ("oos_total_return", "total_return"),
                ("oos_calmar", "calmar"),
                ("oos_sharpe", "sharpe"),
                ("oos_max_dd", "max_dd"),
            )
        },
    }


def build_portfolio_payload(portfolio: dict[str, Any], step: int = 5) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, payload in portfolio.items():
        dates, eq = downsample(payload["dates"], normalize(payload["equity"]), step)
        _, dd = downsample(payload["dates"], payload["drawdown"], step)
        _, exp = downsample(payload["dates"], payload["exposure"], step)
        monthly = monthly_returns_table(payload["equity"], pd.DatetimeIndex(payload["dates"]))
        trades = [
            {
                "symbol": t["symbol"],
                "entry_date": str(pd.Timestamp(t["entry_date"]).date()),
                "exit_date": str(pd.Timestamp(t["exit_date"]).date()),
                "entry_price": _r(t["entry_price"], 0),
                "exit_price": _r(t["exit_price"], 0),
                "shares": _r(t["shares"], 0),
                "units": int(t.get("units", 1)),
                "pnl": _r(t["pnl"], 0),
                "pnl_pct": _r(t["pnl_pct"]),
                "r_multiple": _r(t["r_multiple"], 2),
                "holding_days": _r(t["holding_days"], 0),
                "exit_reason": t["exit_reason"],
                "risk_vnd": _r(t.get("risk_vnd", 0), 0),
            }
            for t in payload["trades"]
        ]
        out[key] = {
            "dates": dates,
            "equity": eq,
            "drawdown": dd,
            "exposure": exp,
            "metrics": {k: _r(v) for k, v in payload["metrics"].items()},
            "trade_stats": {k: _r(v, 3) for k, v in payload["trade_stats"].items()},
            "trades": trades,
            "monthly": monthly,
            "params": {k: _r(v, 4) for k, v in payload["params"].items()},
        }
    return out


def build_ablation_payload(ablation: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not ablation:
        return []
    return [
        {
            "key": a["key"],
            "label": a["label"],
            "calmar_median": _r(a["calmar_median"]),
            "sharpe_median": _r(a["sharpe_median"]),
            "cagr_median": _r(a["cagr_median"]),
            "max_dd_median": _r(a["max_dd_median"]),
            "trades_per_year_median": _r(a["trades_per_year_median"], 2),
            "cagr_positive_share": _r(a["cagr_positive_share"]),
        }
        for a in ablation
    ]


def write_site_data(
    *,
    meta: dict[str, Any],
    symbol_rows: list[dict[str, Any]],
    curves: dict[str, Any],
    portfolio_payload: dict[str, Any],
    ga_payload: dict[str, Any],
    walkforward_payload: dict[str, Any],
    ablation_payload: list[dict[str, Any]],
    heatmap: list[dict[str, Any]] | None = None,
    liquidity: dict[str, Any] | None = None,
    out_dir: Path = SITE_DATA_DIR,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    def dump(name: str, payload: Any) -> None:
        p = out_dir / name
        write_json(payload, p)
        files[name] = p
        log.info("Ghi %s (%.0f KB)", name, p.stat().st_size / 1024)

    dump("meta.json", meta)
    dump("symbols.json", symbol_rows)
    dump("curves.json", curves)
    dump("portfolio.json", portfolio_payload)
    dump("ga.json", ga_payload)
    dump("walkforward.json", walkforward_payload)
    dump("ablation.json", ablation_payload)
    dump("heatmap.json", heatmap or [])
    dump("liquidity.json", liquidity or {"symbols": [], "coverage": {}})
    return files


def build_meta(
    *,
    bank_meta: dict[str, Any],
    cfg: BacktestConfig,
    ga_cfg: GAConfig,
    wf_cfg: WalkForwardConfig,
    portfolio_cfg: PortfolioConfig,
    space: ParamSpace,
    symbol_summary: dict[str, Any],
    ga_summary: dict[str, Any] | None,
    portfolio_payload: dict[str, Any],
    wf_payload: dict[str, Any],
    git_sha: str = "",
    repo_url: str = "",
    pages_url: str = "",
    data_source: str = "vnstock 3.x - nguồn VCI (Vietcap)",
    runtime_seconds: float = 0.0,
) -> dict[str, Any]:
    return {
        "generated_at": utc_now_iso(),
        "app": {
            "name": "DuDu-Trading",
            "version": "1.0.0",
            "tagline": "Donchian Breakout (Turtle System 2) + Genetic Algorithm cho thị trường Việt Nam",
            "repo_url": repo_url,
            "pages_url": pages_url,
            "git_sha": git_sha,
        },
        "data": {
            "source": data_source,
            "n_symbols": bank_meta["n_symbols"],
            "n_sessions": bank_meta["n_sessions"],
            "date_start": bank_meta["date_start"],
            "date_end": bank_meta["date_end"],
            "benchmark": bank_meta["benchmark"],
            "regime_share": _r(bank_meta["regime_share"]),
            "universe_group": "VN100 (HOSE)",
        },
        "config": {
            "market": asdict(cfg.market),
            "strategy": cfg.strategy.to_dict(),
            "ga": asdict(ga_cfg),
            "walkforward": asdict(wf_cfg),
            "portfolio": asdict(portfolio_cfg),
            "space": {k: list(v) for k, v in space.bounds().items()},
            "initial_capital": cfg.initial_capital,
        },
        "headline": {
            "default_calmar_median": _r(symbol_summary.get("calmar", {}).get("median", 0)),
            "default_sharpe_median": _r(symbol_summary.get("sharpe", {}).get("median", 0)),
            "default_cagr_median": _r(symbol_summary.get("cagr", {}).get("median", 0)),
            "default_max_dd_median": _r(symbol_summary.get("max_dd", {}).get("median", 0)),
            "default_trades_per_year_median": _r(symbol_summary.get("trades_per_year", {}).get("median", 0), 2),
            "default_cagr_positive_share": _r(symbol_summary.get("cagr", {}).get("positive_share", 0)),
            "ga_acceptance_rate": _r((ga_summary or {}).get("acceptance_rate", 0)),
            "ga_oos_calmar_median": _r((ga_summary or {}).get("oos_calmar_median", 0)),
            "ga_edge_oos_calmar": _r((ga_summary or {}).get("ga_edge_oos_calmar", 0)),
            "portfolio_cagr": _r(portfolio_payload.get("default", {}).get("metrics", {}).get("cagr", 0)),
            "portfolio_sharpe": _r(portfolio_payload.get("default", {}).get("metrics", {}).get("sharpe", 0)),
            "portfolio_calmar": _r(portfolio_payload.get("default", {}).get("metrics", {}).get("calmar", 0)),
            "portfolio_max_dd": _r(portfolio_payload.get("default", {}).get("metrics", {}).get("max_dd", 0)),
            "portfolio_trades_per_year": _r(
                portfolio_payload.get("default", {}).get("trade_stats", {}).get("trades_per_year", 0), 2
            ),
            "wf_acceptance_rate": _r(wf_payload.get("summary", {}).get("acceptance_rate", 0)),
            "wf_oos_calmar_gt_threshold": _r(wf_payload.get("summary", {}).get("oos_calmar_gt_threshold", 0)),
            "wf_ga_edge_vs_baseline": _r(wf_payload.get("summary", {}).get("ga_edge_vs_baseline", 0)),
        },
        "runtime_seconds": round(runtime_seconds, 1),
    }
