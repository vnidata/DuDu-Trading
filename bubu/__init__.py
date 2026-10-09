"""BuBu-Trading - Donchian Breakout (Turtle System 2) + Genetic Algorithm.

Bộ công cụ nghiên cứu định lượng cho thị trường chứng khoán Việt Nam, dùng dữ
liệu Vnstock (nhà cung cấp VCI).
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = [
    "config",
    "data",
    "indicators",
    "backtest",
    "metrics",
]

from . import backtest, config, data, indicators, metrics  # noqa: E402,F401
