"""Hệ thống Tự Tiến Hóa & Tối Ưu Hóa Sinh Học (Continuous Evolutionary Engine).

Bao gồm:
- WeaknessAnalyzer & WeaknessReport: Khám nghiệm tử thi lệnh lỗ và chẩn đoán điểm yếu
- StrengthExtractor & StrengthProfile: Bóc tách nhân tố sinh lời vượt trội
- AdvisorSynthesizer & DynamicSynthesizedAdvisor: Lai ghép di truyền F1, F2
"""

from .weakness import WeaknessAnalyzer, WeaknessReport
from .strength import StrengthExtractor, StrengthProfile
from .synthesizer import AdvisorSynthesizer, DynamicSynthesizedAdvisor

__all__ = [
    "WeaknessAnalyzer",
    "WeaknessReport",
    "StrengthExtractor",
    "StrengthProfile",
    "AdvisorSynthesizer",
    "DynamicSynthesizedAdvisor",
]
