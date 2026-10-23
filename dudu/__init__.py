"""DuDu-Trading - Donchian Breakout (Turtle System 2) + Genetic Algorithm.

Bộ công cụ nghiên cứu định lượng cho thị trường chứng khoán Việt Nam, hỗ trợ
dữ liệu Vnstock (VCI) và các máy chủ MCP (SSI, DNSE, VCBS).
"""

from __future__ import annotations

__version__ = "1.1.0"
__all__ = [
    "config",
    "data",
    "indicators",
    "backtest",
    "metrics",
    "mcp_auth",
    "mcp_client",
]

from . import backtest, config, data, indicators, metrics, mcp_auth, mcp_client  # noqa: E402,F401
