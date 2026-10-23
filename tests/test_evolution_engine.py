"""Kiểm thử Hệ Thống Tự Tiến Hóa, Khám Nghiệm Tử Thi & Lai Ghép Di Truyền.

Kế thừa từ vn-stock-ai-advisors:
- Khám nghiệm tử thi lệnh lỗ (Weakness Autopsy)
- Bóc tách nhân tố sinh lời Alpha (Strength Extraction)
- Lai ghép di truyền (Genetic Crossover & Inoculation)
"""

from __future__ import annotations

import pytest

from dudu.advisors import ActiveAdvisor, PersistentAdvisor
from dudu.evolution import (
    WeaknessAnalyzer,
    StrengthExtractor,
    AdvisorSynthesizer,
)


def test_weakness_analyzer_drawdown_autopsy():
    """Khám nghiệm sụt giảm sâu (> -22%) phải kích hoạt tăng tỷ trọng Low Volatility."""
    analyzer = WeaknessAnalyzer()
    bad_metrics = {
        "max_drawdown_pct": -32.5,
        "cagr_pct": 5.0,
        "alpha_annual_pct": -3.0,
        "win_rate_pct": 38.0,
        "profit_factor": 0.95,
        "turnover_per_year": 30.0,
    }
    report = analyzer.analyze(bad_metrics, advisor_name="Failed_Trader")

    assert len(report.primary_flaws) >= 3
    assert "w_mean_reversion" in report.penalize_factors
    assert "w_low_volatility" in report.boost_factors
    assert "Failed_Trader" in report.root_cause_diagnosis


def test_strength_extractor_alpha():
    """Bóc tách nhân tố của chuyên gia thành công (Alpha > 15%, Sharpe > 1.0)."""
    extractor = StrengthExtractor()
    top_adv = ActiveAdvisor()
    good_metrics = {
        "alpha_annual_pct": 22.5,
        "sharpe_ratio": 1.45,
        "max_drawdown_pct": -15.0,
        "win_rate_pct": 58.0,
        "profit_factor": 1.85,
        "cagr_pct": 28.0,
    }
    profile = extractor.extract(top_adv, good_metrics)

    assert len(profile.dominant_strengths) >= 4
    assert len(profile.winning_genome_factors) == 4
    assert profile.sharpe_ratio == 1.45


def test_advisor_synthesizer_genetic_crossover():
    """Bộ máy lai ghép sinh ra Chuyên gia F1 kế thừa gen ưu tú và kháng thể miễn dịch."""
    synth = AdvisorSynthesizer(mutation_rate=0.0)
    p_a = ActiveAdvisor()
    p_b = PersistentAdvisor()

    child = synth.synthesize(
        parent_a=p_a,
        parent_b=p_b,
        penalize_factors=["w_mean_reversion"],
        boost_factors=["w_trend_alignment"],
        generation_idx=1,
    )

    assert child.generation == 1
    assert "Gen1" in child.name
    # Tổng gene phải luôn chuẩn hóa
    assert abs(sum(child.genome.values()) - 1.0) < 1e-4
    # Nhân tố boost phải được tăng cường
    assert child.genome["w_trend_alignment"] > 0.05
