"""Kiểm thử thuật toán di truyền và quy trình walk-forward."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bubu.config import BacktestConfig, GAConfig, ParamSpace, WalkForwardConfig
from bubu.data import PricePanel
from bubu.ga import (
    GENES,
    Genome,
    _aggregate,
    blx_crossover,
    evaluate_genome,
    mutate,
    random_genome,
    run_ga,
)
from bubu.indicators import FeatureBank
from bubu.walkforward import aggregate_folds, make_folds

from .test_engine import make_bank, synthetic_symbol


@pytest.fixture(scope="module")
def bank() -> FeatureBank:
    frames = {f"S{i}": synthetic_symbol(n=900, seed=100 + i, drift=0.0008) for i in range(3)}
    return make_bank(frames)


# --------------------------------------------------------------------------
# Genome
# --------------------------------------------------------------------------
def test_genome_respects_bounds_and_integer_genes():
    space = ParamSpace()
    rng = np.random.default_rng(0)
    for _ in range(200):
        g = random_genome(rng, space)
        for name in GENES:
            lo, hi = space.bounds()[name]
            assert lo <= getattr(g, name) <= hi
        assert float(g.entry_window).is_integer()
        assert float(g.exit_window).is_integer()
        assert float(g.atr_period).is_integer()


def test_genome_from_list_clips_and_orders_windows():
    space = ParamSpace()
    g = Genome.from_list([1000, -5, 999, 5.0, 99.0], space)
    assert g.entry_window == 70
    assert g.exit_window == 15
    assert g.atr_period == 25
    assert 0.005 <= g.risk_per_unit <= 0.015
    assert 1.5 <= g.stop_atr <= 3.0
    # exit_window luôn nhỏ hơn entry_window
    assert g.exit_window < g.entry_window


def test_genome_hashable_and_roundtrip():
    g = Genome()
    assert g in {g}
    assert Genome.from_list(g.as_list(), ParamSpace()).to_dict() == g.to_dict()


def test_blx_crossover_stays_in_space():
    space = ParamSpace()
    rng = np.random.default_rng(1)
    a, b = random_genome(rng, space), random_genome(rng, space)
    for _ in range(100):
        c = blx_crossover(a, b, space, rng, 0.35)
        for name in GENES:
            lo, hi = space.bounds()[name]
            assert lo <= getattr(c, name) <= hi


def test_mutate_changes_some_genes_but_keeps_bounds():
    space = ParamSpace()
    rng = np.random.default_rng(2)
    g = Genome()
    changed = 0
    for _ in range(200):
        m = mutate(g, space, rng, 0.5, 0.2)
        changed += int(m != g)
        for name in GENES:
            lo, hi = space.bounds()[name]
            assert lo <= getattr(m, name) <= hi
    assert changed > 0


# --------------------------------------------------------------------------
# Hàm mục tiêu
# --------------------------------------------------------------------------
def test_aggregate_helpers():
    v = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert _aggregate(v, "median") == pytest.approx(0.0)
    assert _aggregate(v, "mean") > 0
    # Cắt đuôi 10% mỗi phía loại bỏ outlier 10.0
    assert _aggregate(v, "trimmed") == pytest.approx(0.0)
    assert _aggregate(np.array([]), "mean") == 0.0


def test_evaluate_genome_reports_penalty_for_low_frequency(bank: FeatureBank):
    cfg = BacktestConfig()
    ga_cfg = GAConfig(min_trades_per_year=50.0, penalty_weight=1.0)
    out = evaluate_genome(bank, bank.panel.symbols, Genome(), 0, 900, cfg, ga_cfg, "trimmed")
    assert out.penalty > 0
    assert out.fitness < ga_cfg.w_calmar * max(0.0, out.calmar)
    assert 0 <= out.traded_share <= 1


def test_evaluate_genome_no_symbols_returns_failure():
    frames = {"AAA": synthetic_symbol(n=300, seed=1)}
    b = make_bank(frames)
    out = evaluate_genome(b, ["KHONG_TON_TAI"], Genome(), 0, 300, BacktestConfig(), GAConfig())
    assert out.fitness < -100


# --------------------------------------------------------------------------
# Vòng lặp GA
# --------------------------------------------------------------------------
def test_run_ga_is_deterministic_with_seed(bank: FeatureBank):
    cfg = BacktestConfig()
    ga_cfg = GAConfig(population=12, generations=4, n_jobs=1)
    r1 = run_ga(bank, bank.panel.symbols, 0, 600, cfg, ParamSpace(), ga_cfg, seed=42)
    r2 = run_ga(bank, bank.panel.symbols, 0, 600, cfg, ParamSpace(), ga_cfg, seed=42)
    assert r1.best.to_dict() == r2.best.to_dict()
    assert r1.best_outcome.fitness == pytest.approx(r2.best_outcome.fitness)
    assert r1.history == r2.history


def test_run_ga_improves_or_matches_initial_best(bank: FeatureBank):
    cfg = BacktestConfig()
    ga_cfg = GAConfig(population=16, generations=6, n_jobs=1)
    res = run_ga(bank, bank.panel.symbols, 0, 600, cfg, ParamSpace(), ga_cfg, seed=7)
    # Neo quần thể tại Genome() mặc định, nên nghiệm cuối không được tệ hơn
    base = evaluate_genome(
        bank, bank.panel.symbols, Genome(), 0, 600, cfg, ga_cfg, "trimmed"
    )
    assert res.best_outcome.fitness >= base.fitness - 1e-9
    assert res.history[0]["best_fitness"] <= res.history[-1]["best_fitness"] + 1e-9
    assert len(res.history) == res.generations + 1


def test_run_ga_history_is_monotone_in_best(bank: FeatureBank):
    cfg = BacktestConfig()
    ga_cfg = GAConfig(population=14, generations=5, n_jobs=1)
    res = run_ga(bank, bank.panel.symbols, 0, 500, cfg, ParamSpace(), ga_cfg, seed=3)
    best = [h["best_fitness"] for h in res.history]
    assert all(best[i] <= best[i + 1] + 1e-9 for i in range(len(best) - 1))


def test_run_ga_refreshes_context_between_calls(bank: FeatureBank):
    """Hồi quy: ngữ cảnh đánh giá là biến toàn cục, phải được nạp lại mỗi lần gọi.

    Lỗi cũ: `_Pool` chỉ nạp ngữ cảnh khi biến toàn cục rỗng, nên từ lần gọi thứ
    hai trở đi GA vẫn đánh giá trên cửa sổ ngày và mã của lần gọi đầu tiên. Hậu
    quả là toàn bộ walk-forward (3.800 fold) trả về cùng một bộ tham số.
    """
    cfg = BacktestConfig()
    ga_cfg = GAConfig(population=10, generations=3, n_jobs=1)
    syms = bank.panel.symbols
    assert len(syms) >= 2

    first = run_ga(bank, [syms[0]], 0, 300, cfg, ParamSpace(), ga_cfg, seed=11)
    second = run_ga(bank, [syms[1]], 500, 800, cfg, ParamSpace(), ga_cfg, seed=11)

    # Điểm fitness của nghiệm thứ hai phải khớp khi đánh giá lại đúng cửa sổ đó.
    direct = evaluate_genome(bank, [syms[1]], second.best, 500, 800, cfg, ga_cfg, "trimmed")
    assert second.best_outcome.fitness == pytest.approx(direct.fitness)
    assert int(second.best_outcome.trades) == int(direct.trades)
    # Và không được trùng khít kết quả của lần gọi đầu (khác mã, khác cửa sổ).
    assert (first.best_outcome.fitness, first.best_outcome.calmar) != (
        second.best_outcome.fitness,
        second.best_outcome.calmar,
    )


# --------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------
def test_make_folds_step_and_bounds():
    cfg = WalkForwardConfig(train_sessions=252, test_sessions=63, step_sessions=63)
    folds = make_folds(1000, cfg)
    assert folds
    for f in folds:
        assert f.train_len == 252
        assert f.test_len == 63
        assert f.train_stop == f.test_start
        assert f.test_stop <= 1000
    assert folds[1].train_start - folds[0].train_start == 63
    # Cửa sổ cuối cùng phải nằm gọn trong dữ liệu
    assert folds[-1].test_stop <= 1000
    assert (folds[-1].test_stop + 63) > 1000


def test_make_folds_returns_empty_when_not_enough_data():
    cfg = WalkForwardConfig(train_sessions=252, test_sessions=63)
    assert make_folds(300, cfg) == []


def test_aggregate_folds_distribution():
    rows = [
        {
            "fold": i,
            "test": {"calmar": c, "sharpe": s, "max_dd": -0.2, "cagr": 0.1, "trades_per_year": 3,
                     "profit_factor": 1.5, "hit_rate": 0.4},
            "train": {"calmar": c + 0.5, "sharpe": s + 0.3},
            "test_baseline": {"calmar": c - 0.2},
            "accepted": c > 0.5,
        }
        for i, (c, s) in enumerate([(1.0, 1.2), (0.6, 0.9), (-0.3, -0.2), (0.2, 0.4)])
    ]
    out = aggregate_folds(rows, WalkForwardConfig())
    assert out["n_folds"] == 4
    assert out["accepted_folds"] == 2
    assert out["acceptance_rate"] == pytest.approx(0.5)
    assert out["oos_calmar_positive_share"] == pytest.approx(0.75)
    assert out["ga_edge_vs_baseline"] == pytest.approx(0.2)
    assert out["distribution"]["calmar"]["oos_max"] == pytest.approx(1.0)


def test_aggregate_folds_empty():
    assert aggregate_folds([], WalkForwardConfig()) == {"n_folds": 0}
