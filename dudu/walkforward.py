"""Walk-forward optimization: fit 252 phiên -> test 63 phiên -> dịch cửa sổ.

Quy trình này là hàng rào chống overfitting quan trọng nhất với dữ liệu
VN-Index vốn có tính phi dừng cao. Kết quả báo cáo dưới dạng PHÂN PHỐI trên
toàn bộ fold (Sharpe, MaxDD, Calmar), không phải một con số tổng hợp duy nhất.

Cổng kiểm định out-of-sample theo đặc tả: chỉ chấp nhận cấu hình nếu
Calmar(OOS) > 0.5 và số lệnh < 20/năm.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from .backtest import run_symbol_window
from .config import BacktestConfig, GAConfig, ParamSpace, WalkForwardConfig
from .ga import Genome, GAResult, run_ga
from .indicators import FeatureBank
from .utils import safe_float

log = logging.getLogger(__name__)


@dataclass
class Fold:
    index: int
    train_start: int
    train_stop: int
    test_start: int
    test_stop: int

    @property
    def train_len(self) -> int:
        return self.train_stop - self.train_start

    @property
    def test_len(self) -> int:
        return self.test_stop - self.test_start


def make_folds(n_sessions: int, cfg: WalkForwardConfig) -> list[Fold]:
    """Sinh danh sách fold theo bước dịch `step_sessions`."""
    folds: list[Fold] = []
    start = 0
    idx = 0
    while True:
        train_stop = start + cfg.train_sessions
        test_stop = train_stop + cfg.test_sessions
        if test_stop > n_sessions:
            break
        if train_stop - start < cfg.min_train_sessions:
            start += cfg.step_sessions
            continue
        folds.append(Fold(idx, start, train_stop, train_stop, test_stop))
        idx += 1
        start += cfg.step_sessions
    return folds


def _metrics_of(res) -> dict[str, float]:
    out = dict(res.metrics)
    out.update(res.trade_stats)
    return out


def run_walkforward_symbol(
    bank: FeatureBank,
    symbol: str,
    cfg: BacktestConfig,
    wf_cfg: WalkForwardConfig,
    space: ParamSpace | None = None,
    ga_cfg: GAConfig | None = None,
    seed: int | None = None,
    baseline_genome: Genome | None = None,
) -> dict[str, Any]:
    """Walk-forward cho một mã: mỗi fold tối ưu trên train rồi đo trên test."""
    space = space or ParamSpace()
    ga_cfg = ga_cfg or GAConfig()
    baseline = baseline_genome or Genome()
    n = bank.n_dates()
    folds = make_folds(n, wf_cfg)
    rows: list[dict[str, Any]] = []

    for fold in folds:
        ga_res: GAResult = run_ga(
            bank,
            [symbol],
            fold.train_start,
            fold.train_stop,
            cfg,
            space=space,
            ga_cfg=ga_cfg,
            seed=(seed or ga_cfg.seed) + fold.index,
            aggregate="median",
        )
        from dataclasses import replace as _replace

        test_cfg = _replace(cfg, strategy=ga_res.best.to_params(cfg.strategy))
        train_res = run_symbol_window(bank, symbol, fold.train_start, fold.train_stop, test_cfg, True)
        test_res = run_symbol_window(bank, symbol, fold.test_start, fold.test_stop, test_cfg, True)
        base_cfg = _replace(cfg, strategy=baseline.to_params(cfg.strategy))
        base_test = run_symbol_window(bank, symbol, fold.test_start, fold.test_stop, base_cfg, True)

        test_m = _metrics_of(test_res)
        accepted = (
            safe_float(test_m.get("calmar")) > wf_cfg.oos_calmar_min
            and safe_float(test_m.get("trades_per_year")) < wf_cfg.oos_max_trades_per_year
            and safe_float(test_m.get("trades")) > 0
        )
        rows.append(
            {
                "fold": fold.index,
                "symbol": symbol,
                "train_start": str(bank.panel.dates[fold.train_start].date()),
                "train_end": str(bank.panel.dates[fold.train_stop - 1].date()),
                "test_start": str(bank.panel.dates[fold.test_start].date()),
                "test_end": str(bank.panel.dates[fold.test_stop - 1].date()),
                "params": ga_res.best.to_dict(),
                "train": {**_metrics_of(train_res), "fitness": ga_res.best_outcome.fitness},
                "test": test_m,
                "test_baseline": _metrics_of(base_test),
                "accepted": bool(accepted),
            }
        )

    return {"symbol": symbol, "folds": rows, **aggregate_folds(rows, wf_cfg)}


def aggregate_folds(rows: list[dict[str, Any]], wf_cfg: WalkForwardConfig) -> dict[str, Any]:
    """Thống kê phân phối trên toàn bộ fold."""
    if not rows:
        return {"n_folds": 0}
    keys = ["sharpe", "calmar", "max_dd", "cagr", "trades_per_year", "profit_factor", "hit_rate"]
    dist: dict[str, Any] = {}
    for k in keys:
        oos = np.array([safe_float(r["test"].get(k)) for r in rows], dtype=float)
        ins = np.array([safe_float(r["train"].get(k)) for r in rows], dtype=float)
        dist[k] = {
            "oos_mean": safe_float(oos.mean()),
            "oos_median": safe_float(np.median(oos)),
            "oos_p25": safe_float(np.percentile(oos, 25)),
            "oos_p75": safe_float(np.percentile(oos, 75)),
            "oos_min": safe_float(oos.min()),
            "oos_max": safe_float(oos.max()),
            "is_mean": safe_float(ins.mean()),
            "is_median": safe_float(np.median(ins)),
            "positive_share": safe_float((oos > 0).mean()),
        }
    base = np.array([safe_float(r["test_baseline"].get("calmar")) for r in rows], dtype=float)
    oos_calmar = np.array([safe_float(r["test"].get("calmar")) for r in rows], dtype=float)

    # Rất nhiều fold không phát sinh lệnh nào (bộ lọc ADV 30 tỷ chặn hết tín
    # hiệu trong 2016-2020), khiến Calmar và Sharpe bằng đúng 0 và làm phân
    # phối bị chi phối bởi một cột spike tại 0. Vì vậy báo cáo thêm phân phối
    # có điều kiện: chỉ tính các fold thực sự có giao dịch.
    traded = [r for r in rows if safe_float(r["test"].get("trades")) > 0]
    dist_traded: dict[str, Any] = {}
    for k in keys:
        v = np.array([safe_float(r["test"].get(k)) for r in traded], dtype=float)
        if v.size == 0:
            dist_traded[k] = {}
            continue
        dist_traded[k] = {
            "oos_mean": safe_float(v.mean()),
            "oos_median": safe_float(np.median(v)),
            "oos_p25": safe_float(np.percentile(v, 25)),
            "oos_p75": safe_float(np.percentile(v, 75)),
            "oos_min": safe_float(v.min()),
            "oos_max": safe_float(v.max()),
            "positive_share": safe_float((v > 0).mean()),
            "gt_threshold_share": safe_float((v > wf_cfg.oos_calmar_min).mean()) if k == "calmar" else 0.0,
            "n": int(v.size),
        }
    traded_calmar = np.array([safe_float(r["test"].get("calmar")) for r in traded], dtype=float)
    traded_base = np.array([safe_float(r["test_baseline"].get("calmar")) for r in traded], dtype=float)

    return {
        "n_folds": len(rows),
        "n_traded_folds": len(traded),
        "traded_share": safe_float(len(traded) / len(rows)) if rows else 0.0,
        "accepted_folds": int(sum(1 for r in rows if r["accepted"])),
        "acceptance_rate": safe_float(np.mean([1.0 if r["accepted"] else 0.0 for r in rows])),
        "acceptance_rate_traded": safe_float(
            np.mean([1.0 if r["accepted"] else 0.0 for r in traded])
        ) if traded else 0.0,
        "oos_calmar_positive_share": safe_float((oos_calmar > 0).mean()),
        "oos_calmar_positive_share_traded": safe_float((traded_calmar > 0).mean())
        if traded_calmar.size
        else 0.0,
        "oos_calmar_gt_threshold": safe_float((oos_calmar > wf_cfg.oos_calmar_min).mean()),
        "oos_calmar_gt_threshold_traded": safe_float(
            (traded_calmar > wf_cfg.oos_calmar_min).mean()
        )
        if traded_calmar.size
        else 0.0,
        "baseline_calmar_mean": safe_float(base.mean()) if base.size else 0.0,
        "ga_edge_vs_baseline": safe_float(oos_calmar.mean() - base.mean()) if base.size else 0.0,
        "ga_edge_vs_baseline_traded": safe_float(traded_calmar.mean() - traded_base.mean())
        if traded_calmar.size
        else 0.0,
        "distribution": dist,
        "distribution_traded": dist_traded,
        "config": {
            "train_sessions": wf_cfg.train_sessions,
            "test_sessions": wf_cfg.test_sessions,
            "step_sessions": wf_cfg.step_sessions,
            "oos_calmar_min": wf_cfg.oos_calmar_min,
            "oos_max_trades_per_year": wf_cfg.oos_max_trades_per_year,
        },
    }


_WF_CTX: dict[str, Any] = {}


def _wf_init(bank: FeatureBank, cfg: BacktestConfig, wf_cfg: WalkForwardConfig, space: ParamSpace, ga_cfg: GAConfig, seed: int) -> None:
    _WF_CTX.clear()
    _WF_CTX.update(bank=bank, cfg=cfg, wf_cfg=wf_cfg, space=space, ga_cfg=ga_cfg, seed=seed)


def _wf_task(symbol: str) -> dict[str, Any]:
    c = _WF_CTX
    try:
        return run_walkforward_symbol(
            c["bank"], symbol, c["cfg"], c["wf_cfg"], c["space"], c["ga_cfg"], c["seed"]
        )
    except Exception as exc:  # pragma: no cover
        return {"symbol": symbol, "folds": [], "error": str(exc), "n_folds": 0}


def run_walkforward_panel(
    bank: FeatureBank,
    symbols: Sequence[str],
    cfg: BacktestConfig,
    wf_cfg: WalkForwardConfig,
    space: ParamSpace | None = None,
    ga_cfg: GAConfig | None = None,
    n_jobs: int = 8,
) -> dict[str, Any]:
    """Walk-forward song song theo mã (mỗi tiến trình xử lý trọn một mã).

    `FeatureBank` được nạp một lần cho mỗi tiến trình con qua `initializer`;
    nếu truyền kèm từng tác vụ thì chi phí pickle (hơn 100 MB mỗi lần) sẽ
    lấn át toàn bộ thời gian tính toán.
    """
    from concurrent.futures import ProcessPoolExecutor

    symbols = list(symbols)
    ga_cfg = ga_cfg or GAConfig()
    space = space or ParamSpace()
    seed = ga_cfg.seed

    if n_jobs <= 1 or len(symbols) == 1:
        _wf_init(bank, cfg, wf_cfg, space, ga_cfg, seed)
        results = [_wf_task(s) for s in symbols]
    else:
        with ProcessPoolExecutor(
            max_workers=n_jobs,
            initializer=_wf_init,
            initargs=(bank, cfg, wf_cfg, space, ga_cfg, seed),
        ) as ex:
            results = list(ex.map(_wf_task, symbols, chunksize=1))

    ok = [r for r in results if r.get("folds")]
    if not ok:
        first = next((r.get("error") for r in results if r.get("error")), "không rõ nguyên nhân")
        raise RuntimeError(
            f"Walk-forward thất bại trên toàn bộ {len(symbols)} mã. Lỗi đầu tiên: {first}"
        )
    all_rows = [row for r in ok for row in r["folds"]]
    summary = aggregate_folds(all_rows, wf_cfg)
    per_symbol = {
        r["symbol"]: {
            "n_folds": r.get("n_folds", 0),
            "n_traded_folds": r.get("n_traded_folds", 0),
            "traded_share": r.get("traded_share", 0.0),
            "acceptance_rate": r.get("acceptance_rate", 0.0),
            "acceptance_rate_traded": r.get("acceptance_rate_traded", 0.0),
            "oos_calmar_gt_threshold": r.get("oos_calmar_gt_threshold", 0.0),
            "ga_edge_vs_baseline": r.get("ga_edge_vs_baseline", 0.0),
            "ga_edge_vs_baseline_traded": r.get("ga_edge_vs_baseline_traded", 0.0),
            "oos_calmar_median": safe_float(
                np.median([safe_float(x["test"].get("calmar")) for x in r["folds"]])
            ),
            "oos_calmar_median_traded": safe_float(
                np.median([safe_float(x["test"].get("calmar")) for x in r["folds"] if safe_float(x["test"].get("trades")) > 0])
            ) if any(safe_float(x["test"].get("trades")) > 0 for x in r["folds"]) else 0.0,
            "oos_sharpe_median": safe_float(
                np.median([safe_float(x["test"].get("sharpe")) for x in r["folds"]])
            ),
            "oos_max_dd_median": safe_float(
                np.median([safe_float(x["test"].get("max_dd")) for x in r["folds"]])
            ),
        }
        for r in ok
    }
    return {
        "summary": summary,
        "per_symbol": per_symbol,
        "folds": all_rows,
        "symbols_run": [r["symbol"] for r in ok],
        "symbols_failed": [r["symbol"] for r in results if not r.get("folds")],
    }
