"""Tối ưu tham số bằng thuật toán di truyền (Genetic Algorithm).

Hàm mục tiêu kép theo đặc tả nghiên cứu:

    Fitness = w1 × Calmar − w2 × MaxDD

với w1 = 0.7, w2 = 0.3. Calmar = CAGR / |MaxDD| được cắt biên trong
`GAConfig.calmar_clip` để một fold may mắn không chi phối quần thể. Thêm hai
số hạng phạt: phạt khi quá ít lệnh (thiếu ý nghĩa thống kê) và phạt khi quá
nhiều lệnh (chi phí giao dịch ăn mòn lợi nhuận) - đúng yêu cầu "tần suất giao
dịch trung bình" của đặc tả.

Genome gồm 5 gen liên tục: entry_window, exit_window, atr_period,
risk_per_unit, stop_atr. Toán tử di truyền: chọn lọc tournament, lai ghép BLX-α,
đột biến Gaussian có thu hẹp dần theo thế hệ, giữ nguyên tinh hoa (elitism).
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from .backtest import run_symbol_window
from .config import BacktestConfig, GAConfig, ParamSpace, StrategyParams
from .indicators import FeatureBank
from .utils import safe_float

log = logging.getLogger(__name__)

GENES = ("entry_window", "exit_window", "atr_period", "risk_per_unit", "stop_atr")
INT_GENES = {"entry_window", "exit_window", "atr_period"}


# --------------------------------------------------------------------------
# Genome
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Genome:
    entry_window: int = 55
    exit_window: int = 20
    atr_period: int = 20
    risk_per_unit: float = 0.01
    stop_atr: float = 2.0

    def to_params(self, base: StrategyParams | None = None) -> StrategyParams:
        base = base or StrategyParams()
        return replace(
            base,
            entry_window=int(self.entry_window),
            exit_window=int(self.exit_window),
            atr_period=int(self.atr_period),
            risk_per_unit=float(self.risk_per_unit),
            stop_atr=float(self.stop_atr),
        )

    def as_list(self) -> list[float]:
        return [float(getattr(self, g)) for g in GENES]

    @staticmethod
    def from_list(values: Sequence[float], space: ParamSpace, base: StrategyParams | None = None) -> "Genome":
        d: dict[str, float] = {}
        for name, v in zip(GENES, values):
            lo, hi = space.bounds()[name]
            v = float(np.clip(v, lo, hi))
            if name in INT_GENES:
                v = int(round(v))
            d[name] = v
        g = Genome(**d)  # type: ignore[arg-type]
        # Ràng buộc logic: cửa sổ thoát phải ngắn hơn cửa sổ vào lệnh.
        if g.exit_window >= g.entry_window:
            d["exit_window"] = max(int(space.exit_window[0]), min(g.entry_window - 5, int(space.exit_window[1])))
            g = Genome(**d)  # type: ignore[arg-type]
        return g

    def to_dict(self) -> dict[str, float]:
        return {g: float(getattr(self, g)) for g in GENES}


# --------------------------------------------------------------------------
# Hàm mục tiêu
# --------------------------------------------------------------------------
@dataclass
class EvalOutcome:
    fitness: float
    calmar: float
    max_dd: float
    cagr: float
    sharpe: float
    trades: int
    trades_per_year: float
    profit_factor: float
    hit_rate: float
    penalty: float
    per_symbol: dict[str, dict[str, float]]
    traded_share: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fitness": self.fitness,
            "calmar": self.calmar,
            "max_dd": self.max_dd,
            "cagr": self.cagr,
            "sharpe": self.sharpe,
            "trades": self.trades,
            "trades_per_year": self.trades_per_year,
            "profit_factor": self.profit_factor,
            "hit_rate": self.hit_rate,
            "penalty": self.penalty,
            "traded_share": self.traded_share,
        }


def _aggregate(values: np.ndarray, how: str) -> float:
    """Gộp kết quả nhiều mã thành một điểm số.

    `mean` nhạy với outlier, `median` bền nhưng mất gradient khi hơn nửa rổ
    không phát sinh lệnh (trường hợp thường gặp khi bộ lọc ADV 30 tỷ chặn gần
    hết tín hiệu giai đoạn 2016-2020). `trimmed` cắt 10% đuôi mỗi phía, giữ
    được gradient mà vẫn kháng outlier.
    """
    if values.size == 0:
        return 0.0
    if how == "median":
        return float(np.median(values))
    if how == "trimmed":
        if values.size < 10:
            return float(np.mean(values))
        k = max(1, int(values.size * 0.1))
        s = np.sort(values)
        return float(np.mean(s[k:-k]))
    return float(np.mean(values))


def _penalty(trades_per_year: float, cfg: GAConfig) -> float:
    if trades_per_year < cfg.min_trades_per_year:
        return cfg.penalty_weight * (cfg.min_trades_per_year - trades_per_year) / cfg.min_trades_per_year
    if trades_per_year > cfg.max_trades_per_year:
        return cfg.penalty_weight * (trades_per_year - cfg.max_trades_per_year) / cfg.max_trades_per_year
    return 0.0


def evaluate_genome(
    bank: FeatureBank,
    symbols: Sequence[str],
    genome: Genome,
    t0: int,
    t1: int,
    cfg: BacktestConfig,
    ga_cfg: GAConfig,
    aggregate: str = "trimmed",
) -> EvalOutcome:
    """Đánh giá một genome trên một cửa sổ ngày và một tập mã.

    `aggregate`: "median" (mặc định, bền vững trước outlier) hoặc "mean".
    """
    params = genome.to_params(cfg.strategy)
    run_cfg = replace(cfg, strategy=params)
    calmars: list[float] = []
    dds: list[float] = []
    cagrs: list[float] = []
    sharpes: list[float] = []
    pfs: list[float] = []
    hits: list[float] = []
    total_trades = 0
    per_symbol: dict[str, dict[str, float]] = {}

    for sym in symbols:
        try:
            res = run_symbol_window(bank, sym, t0, t1, run_cfg, close_open_at_end=False)
        except Exception:  # pragma: no cover
            continue
        m = res.metrics
        ts = res.trade_stats
        calmars.append(safe_float(m.get("calmar")))
        dds.append(safe_float(m.get("max_dd")))
        cagrs.append(safe_float(m.get("cagr")))
        sharpes.append(safe_float(m.get("sharpe")))
        pfs.append(safe_float(ts.get("profit_factor")))
        hits.append(safe_float(ts.get("hit_rate")))
        total_trades += int(ts.get("trades", 0))
        per_symbol[sym] = {
            "calmar": calmars[-1],
            "max_dd": dds[-1],
            "cagr": cagrs[-1],
            "sharpe": sharpes[-1],
            "trades": safe_float(ts.get("trades", 0)),
        }

    if not calmars:
        return EvalOutcome(-999.0, 0, 0, 0, 0, 0, 0, 0, 0, 999.0, {})

    calmar = _aggregate(np.asarray(calmars, dtype=float), aggregate)
    max_dd = _aggregate(np.asarray(dds, dtype=float), aggregate)
    cagr = _aggregate(np.asarray(cagrs, dtype=float), aggregate)
    sharpe = _aggregate(np.asarray(sharpes, dtype=float), aggregate)
    sessions = max(1, t1 - t0)
    years = max(sessions / float(cfg.trading_days), 1e-9)
    trades_per_year = float(total_trades / len(calmars) / years)
    clipped = float(np.clip(calmar, *ga_cfg.calmar_clip))
    pen = _penalty(trades_per_year, ga_cfg)
    fitness = ga_cfg.w_calmar * clipped - ga_cfg.w_maxdd * abs(max_dd) - pen
    traded = sum(1 for v in per_symbol.values() if v["trades"] > 0)

    return EvalOutcome(
        fitness=safe_float(fitness),
        calmar=safe_float(calmar),
        max_dd=safe_float(max_dd),
        cagr=safe_float(cagr),
        sharpe=safe_float(sharpe),
        trades=total_trades,
        trades_per_year=safe_float(trades_per_year),
        profit_factor=safe_float(float(np.median(pfs))) if pfs else 0.0,
        hit_rate=safe_float(float(np.median(hits))) if hits else 0.0,
        penalty=safe_float(pen),
        per_symbol=per_symbol,
        traded_share=safe_float(traded / len(calmars)),
    )


# --------------------------------------------------------------------------
# Toán tử di truyền
# --------------------------------------------------------------------------
def random_genome(rng: np.random.Generator, space: ParamSpace) -> Genome:
    vals = []
    for name in GENES:
        lo, hi = space.bounds()[name]
        vals.append(rng.uniform(lo, hi))
    return Genome.from_list(vals, space)


def tournament(pop: list[Genome], fits: np.ndarray, rng: np.random.Generator, k: int) -> Genome:
    idx = rng.integers(0, len(pop), size=k)
    best = idx[int(np.argmax(fits[idx]))]
    return pop[int(best)]


def blx_crossover(a: Genome, b: Genome, space: ParamSpace, rng: np.random.Generator, alpha: float) -> Genome:
    xa, xb = np.array(a.as_list()), np.array(b.as_list())
    lo = np.minimum(xa, xb)
    hi = np.maximum(xa, xb)
    span = hi - lo
    lower = lo - alpha * span
    upper = hi + alpha * span
    child = rng.uniform(lower, upper)
    return Genome.from_list(child, space)


def mutate(g: Genome, space: ParamSpace, rng: np.random.Generator, rate: float, scale: float) -> Genome:
    vals = np.array(g.as_list(), dtype=float)
    for i, name in enumerate(GENES):
        if rng.random() >= rate:
            continue
        lo, hi = space.bounds()[name]
        sigma = scale * (hi - lo)
        vals[i] = vals[i] + rng.normal(0.0, sigma)
        if rng.random() < 0.08:  # đột biến hoàn toàn, chống hội tụ sớm
            vals[i] = rng.uniform(lo, hi)
    return Genome.from_list(vals, space)


# --------------------------------------------------------------------------
# Vòng lặp GA
# --------------------------------------------------------------------------
@dataclass
class GAResult:
    best: Genome
    best_outcome: EvalOutcome
    history: list[dict[str, float]]
    population: list[dict[str, Any]]
    generations: int
    evaluations: int
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "best": self.best.to_dict(),
            "best_outcome": self.best_outcome.to_dict(),
            "history": self.history,
            "generations": self.generations,
            "evaluations": self.evaluations,
            "seed": self.seed,
            "population": self.population,
        }


_WORKER_CTX: dict[str, Any] = {}


def _init_worker(
    bank: FeatureBank,
    symbols: Sequence[str],
    t0: int,
    t1: int,
    cfg: BacktestConfig,
    ga_cfg: GAConfig,
    aggregate: str,
) -> None:
    """Nạp ngữ cảnh đánh giá vào tiến trình con.

    `FeatureBank` nặng hàng chục MB; nếu truyền kèm mỗi genome thì chi phí
    pickle sẽ lấn át chi phí tính toán. Do đó ngữ cảnh được gửi một lần qua
    `initializer` và tác vụ chỉ còn truyền genome.

    CẢNH BÁO: `_WORKER_CTX` là biến toàn cục của tiến trình. Mỗi lần gọi
    `run_ga` với cửa sổ ngày hoặc mã khác đều PHẢI nạp lại ngữ cảnh, nếu không
    các fold sau sẽ tiếp tục tối ưu trên cửa sổ của fold đầu tiên. Đây từng là
    lỗi khiến toàn bộ walk-forward trả về cùng một bộ tham số.
    """
    _WORKER_CTX.clear()
    _WORKER_CTX.update(
        bank=bank, symbols=list(symbols), t0=t0, t1=t1, cfg=cfg, ga_cfg=ga_cfg, aggregate=aggregate
    )


def _eval_task(genome: Genome) -> tuple[Genome, EvalOutcome]:
    c = _WORKER_CTX
    return genome, evaluate_genome(
        c["bank"], c["symbols"], genome, c["t0"], c["t1"], c["cfg"], c["ga_cfg"], c["aggregate"]
    )


class _Pool:
    """Bọc ProcessPoolExecutor, tái sử dụng giữa các thế hệ của cùng một GA."""

    def __init__(self, n_jobs: int, context: tuple | None = None) -> None:
        self.n_jobs = max(1, n_jobs)
        self.context = context
        self._exec: ProcessPoolExecutor | None = None

    def map(self, genomes: list[Genome]) -> list[tuple[Genome, EvalOutcome]]:
        if self.context is None:
            raise RuntimeError("_Pool cần context để đánh giá")
        if self.n_jobs == 1 or len(genomes) <= 1:
            # Chế độ tuần tự: LUÔN nạp lại ngữ cảnh. Ngữ cảnh là biến toàn cục
            # của tiến trình và có thể đã bị thay bởi lần gọi run_ga trước đó
            # với cửa sổ ngày hoặc mã khác.
            _init_worker(*self.context)
            return [_eval_task(g) for g in genomes]
        if self._exec is None:
            bank, symbols, t0, t1, cfg, ga_cfg, aggregate = self.context
            self._exec = ProcessPoolExecutor(
                max_workers=self.n_jobs,
                initializer=_init_worker,
                initargs=(bank, symbols, t0, t1, cfg, ga_cfg, aggregate),
            )
        chunk = max(1, len(genomes) // (self.n_jobs * 4))
        return list(self._exec.map(_eval_task, genomes, chunksize=chunk))

    def close(self) -> None:
        if self._exec is not None:
            self._exec.shutdown(wait=True, cancel_futures=True)
            self._exec = None


def run_ga(
    bank: FeatureBank,
    symbols: Sequence[str],
    t0: int,
    t1: int,
    cfg: BacktestConfig,
    space: ParamSpace | None = None,
    ga_cfg: GAConfig | None = None,
    seed: int | None = None,
    aggregate: str = "trimmed",
    pool: _Pool | None = None,
    init: Sequence[Genome] | None = None,
) -> GAResult:
    """Chạy GA tối ưu tham số trên cửa sổ [t0, t1)."""
    space = space or ParamSpace()
    ga_cfg = ga_cfg or GAConfig()
    seed = ga_cfg.seed if seed is None else seed
    rng = np.random.default_rng(seed)
    symbols = list(symbols)
    evaluations = 0

    pop: list[Genome] = list(init or [])
    while len(pop) < ga_cfg.population:
        pop.append(random_genome(rng, space))
    pop = pop[: ga_cfg.population]
    # Neo quần thể tại cấu hình Donchian-55 mặc định để không thoái hoá.
    if init is None:
        pop[0] = Genome()

    own_pool = pool is None
    context = (bank, symbols, t0, t1, cfg, ga_cfg, aggregate)
    pool = pool or _Pool(ga_cfg.n_jobs if len(symbols) > 1 else 1, context)
    try:
        history: list[dict[str, float]] = []
        cache: dict[Genome, EvalOutcome] = {}

        def evaluate_many(genomes: list[Genome]) -> list[EvalOutcome]:
            nonlocal evaluations
            todo = [g for g in dict.fromkeys(genomes) if g not in cache]
            if todo:
                for g, out in pool.map(todo):
                    cache[g] = out
                    evaluations += 1
            return [cache[g] for g in genomes]

        fits = np.array([o.fitness for o in evaluate_many(pop)], dtype=float)
        best_idx = int(np.argmax(fits))
        best_genome, best_outcome = pop[best_idx], cache[pop[best_idx]]
        history.append(
            {
                "generation": 0,
                "best_fitness": safe_float(fits.max()),
                "mean_fitness": safe_float(fits.mean()),
                "std_fitness": safe_float(fits.std()),
                "best_calmar": best_outcome.calmar,
                "best_max_dd": best_outcome.max_dd,
                "best_trades_per_year": best_outcome.trades_per_year,
            }
        )

        stagnant = 0
        for gen in range(1, ga_cfg.generations + 1):
            order = np.argsort(-fits)
            new_pop: list[Genome] = [pop[int(i)] for i in order[: ga_cfg.elite]]
            # Đột biến thu hẹp dần theo thế hệ
            scale = ga_cfg.mutation_scale * (1.0 - 0.8 * gen / max(1, ga_cfg.generations))
            while len(new_pop) < ga_cfg.population:
                parent_a = tournament(pop, fits, rng, ga_cfg.tournament_size)
                child = parent_a
                if rng.random() < ga_cfg.crossover_rate:
                    parent_b = tournament(pop, fits, rng, ga_cfg.tournament_size)
                    child = blx_crossover(parent_a, parent_b, space, rng, ga_cfg.blx_alpha)
                child = mutate(child, space, rng, ga_cfg.mutation_rate, scale)
                new_pop.append(child)
            pop = new_pop
            fits = np.array([o.fitness for o in evaluate_many(pop)], dtype=float)
            idx = int(np.argmax(fits))
            if fits[idx] > best_outcome.fitness + 1e-9:
                best_outcome = cache[pop[idx]]
                best_genome = pop[idx]
                stagnant = 0
            else:
                stagnant += 1
            history.append(
                {
                    "generation": gen,
                    "best_fitness": safe_float(fits.max()),
                    "mean_fitness": safe_float(fits.mean()),
                    "std_fitness": safe_float(fits.std()),
                    "best_calmar": best_outcome.calmar,
                    "best_max_dd": best_outcome.max_dd,
                    "best_trades_per_year": best_outcome.trades_per_year,
                }
            )
            if stagnant >= max(8, ga_cfg.generations // 3):
                log.debug("GA hội tụ sớm tại thế hệ %d", gen)
                break

        # Danh sách quần thể cuối cùng để vẽ bản đồ tham số trên website
        final = sorted(
            (
                {"genome": g.to_dict(), **cache[g].to_dict()}
                for g in set(pop)
                if g in cache
            ),
            key=lambda r: -r["fitness"],
        )[:40]
    finally:
        if own_pool:
            pool.close()

    return GAResult(
        best=best_genome,
        best_outcome=best_outcome,
        history=history,
        population=final,
        generations=len(history) - 1,
        evaluations=evaluations,
        seed=seed,
    )


# --------------------------------------------------------------------------
# Quét lưới tham số (kiểm chứng GA)
# --------------------------------------------------------------------------
def parameter_sweep(
    bank: FeatureBank,
    symbols: Sequence[str],
    entry_windows: Iterable[int],
    exit_window: int,
    atr_period: int,
    t0: int,
    t1: int,
    cfg: BacktestConfig,
    ga_cfg: GAConfig | None = None,
) -> list[dict[str, Any]]:
    """Quét entry_window để dựng bản đồ nhiệt Sharpe/Calmar, đối chiếu với GA."""
    ga_cfg = ga_cfg or GAConfig()
    rows: list[dict[str, Any]] = []
    for w in entry_windows:
        g = Genome(entry_window=int(w), exit_window=exit_window, atr_period=atr_period)
        out = evaluate_genome(bank, symbols, g, t0, t1, cfg, ga_cfg)
        rows.append({"entry_window": int(w), **out.to_dict()})
    return rows
