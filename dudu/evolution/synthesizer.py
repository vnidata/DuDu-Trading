"""Bộ Máy Lai Ghép Di Truyền & Sinh Chuyên Gia Thế Hệ Mới (Advisor Synthesizer).

Kế thừa từ vn-stock-ai-advisors:
1. Lai ghép di truyền (Genetic Crossover) giữa các chuyên gia AI có thành tích dẫn đầu.
2. Tiêm kháng thể (Inoculation) chống lại các sai lầm khám nghiệm tử thi.
3. Đột biến ngẫu nhiên (Mutation) để duy trì tính đa dạng giải pháp.
4. Sinh ra Chuyên gia Tiến Hóa Thế Hệ F1, F2...
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional
from dudu.advisors.base import BaseAdvisor, AllocationMethod


class DynamicSynthesizedAdvisor(BaseAdvisor):
    """Chuyên gia AI thế hệ mới được sinh ra từ quá trình tiến hóa di truyền."""

    def __init__(
        self,
        name: str,
        description: str,
        rebalance_days: int = 21,
        portfolio_size: int = 5,
        allocation_method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT,
        genome: Optional[Dict[str, float]] = None,
        generation: int = 1,
    ):
        super().__init__(
            name=name,
            description=description,
            rebalance_days=rebalance_days,
            portfolio_size=portfolio_size,
            allocation_method=allocation_method,
            genome=genome,
        )
        self.generation = generation


class AdvisorSynthesizer:
    """Bộ máy lai ghép và miễn dịch di truyền cho các AI Advisor."""

    def __init__(self, mutation_rate: float = 0.15):
        self.mutation_rate = mutation_rate

    def synthesize(
        self,
        parent_a: BaseAdvisor,
        parent_b: Optional[BaseAdvisor] = None,
        penalize_factors: Optional[List[str]] = None,
        boost_factors: Optional[List[str]] = None,
        generation_idx: int = 1,
    ) -> DynamicSynthesizedAdvisor:
        """Lai ghép hai chuyên gia cha mẹ và triệt tiêu các nhân tố gây lỗ."""
        p2 = parent_b or parent_a
        child_genome: Dict[str, float] = {}

        # 1. Lai ghép chéo (Crossover)
        all_keys = set(parent_a.genome.keys()).union(set(p2.genome.keys()))
        for k in all_keys:
            v_a = parent_a.genome.get(k, 0.1)
            v_b = p2.genome.get(k, 0.1)
            blend = random.uniform(0.35, 0.65)
            child_genome[k] = v_a * blend + v_b * (1.0 - blend)

        # 2. Tiêm kháng thể (Inoculation against weaknesses)
        if penalize_factors:
            for pf in penalize_factors:
                if pf in child_genome:
                    child_genome[pf] = max(0.02, child_genome[pf] * 0.55)

        if boost_factors:
            for bf in boost_factors:
                if bf in child_genome:
                    child_genome[bf] = child_genome[bf] * 1.30

        # 3. Đột biến có kiểm soát (Controlled Mutation)
        for k in child_genome.keys():
            if random.random() < self.mutation_rate:
                noise = (random.random() - 0.5) * 0.08
                child_genome[k] = max(0.01, child_genome[k] + noise)

        name = f"AI_Advisor_Evolved_Gen{generation_idx}"
        desc = (
            f"Chuyên gia Thế Hệ F{generation_idx} (Lai ghép từ {parent_a.name} & {p2.name}, "
            f"kháng thể miễn dịch sụt giảm)"
        )

        return DynamicSynthesizedAdvisor(
            name=name,
            description=desc,
            rebalance_days=parent_a.rebalance_days,
            portfolio_size=parent_a.portfolio_size,
            allocation_method=parent_a.allocation_method,
            genome=child_genome,
            generation=generation_idx,
        )
