"""Chỉ số đo lường hiệu quả và rủi ro.

Mọi chỉ số dùng chuẩn thực hành ngành: CAGR theo năm lịch, Sharpe với lãi suất
phi rủi ro cấu hình được, MaxDD theo đỉnh-tới-đáy trên đường vốn, Calmar =
CAGR / |MaxDD|.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from .utils import safe_float


def max_drawdown(equity: np.ndarray) -> tuple[float, int, int]:
    """Trả về (max_drawdown âm, chỉ số đỉnh, chỉ số đáy)."""
    if equity.size == 0:
        return 0.0, 0, 0
    peak = np.maximum.accumulate(equity)
    dd = np.where(peak > 0, equity / peak - 1.0, 0.0)
    idx = int(np.argmin(dd))
    if dd[idx] >= 0:
        return 0.0, 0, 0
    peak_idx = int(np.argmax(equity[: idx + 1]))
    return float(dd[idx]), peak_idx, idx


def max_drawdown_duration(equity: np.ndarray) -> int:
    """Số phiên dài nhất dưới đỉnh cũ (drawdown duration)."""
    if equity.size == 0:
        return 0
    peak = np.maximum.accumulate(equity)
    under = equity < peak - 1e-12
    longest = cur = 0
    for flag in under:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    return int(longest)


def _returns(equity: np.ndarray) -> np.ndarray:
    if equity.size < 2:
        return np.array([])
    return np.diff(equity) / np.where(equity[:-1] == 0, np.nan, equity[:-1])


def equity_metrics(
    equity: np.ndarray,
    trading_days: int = 252,
    rf_annual: float = 0.0,
) -> dict[str, float]:
    """Chỉ số trên đường vốn (đã bao gồm chi phí giao dịch)."""
    equity = np.asarray(equity, dtype=float)
    equity = equity[np.isfinite(equity)]
    n = equity.size
    out: dict[str, float] = {
        "sessions": float(n),
        "final_equity": safe_float(equity[-1]) if n else 0.0,
        "total_return": 0.0,
        "cagr": 0.0,
        "vol_annual": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "max_dd": 0.0,
        "max_dd_duration": 0.0,
        "calmar": 0.0,
        "exposure": 0.0,
    }
    if n < 2 or equity[0] <= 0:
        return out

    years = max(n / float(trading_days), 1e-9)
    total_return = equity[-1] / equity[0] - 1.0
    cagr = (equity[-1] / equity[0]) ** (1.0 / years) - 1.0 if equity[-1] > 0 else -1.0
    rets = _returns(equity)
    rets = rets[np.isfinite(rets)]
    vol = float(np.std(rets, ddof=1) * np.sqrt(trading_days)) if rets.size > 1 else 0.0
    rf_daily = rf_annual / trading_days
    excess = rets - rf_daily
    sharpe = (
        float(np.mean(excess) / np.std(rets, ddof=1) * np.sqrt(trading_days))
        if rets.size > 1 and np.std(rets, ddof=1) > 0
        else 0.0
    )
    downside = rets[rets < 0]
    sortino = (
        float(np.mean(excess) / np.std(downside, ddof=1) * np.sqrt(trading_days))
        if downside.size > 1 and np.std(downside, ddof=1) > 0
        else 0.0
    )
    dd, _, _ = max_drawdown(equity)
    calmar = float(cagr / abs(dd)) if dd < -1e-9 else 0.0

    out.update(
        total_return=safe_float(total_return),
        cagr=safe_float(cagr),
        vol_annual=safe_float(vol),
        sharpe=safe_float(sharpe),
        sortino=safe_float(sortino),
        max_dd=safe_float(dd),
        max_dd_duration=float(max_drawdown_duration(equity)),
        calmar=safe_float(calmar),
    )
    return out


def trade_metrics(trades: Sequence[dict[str, Any]], sessions: int, trading_days: int = 252) -> dict[str, float]:
    """Chỉ số trên tập lệnh đã khớp."""
    years = max(sessions / float(trading_days), 1e-9)
    n = len(trades)
    base = {
        "trades": float(n),
        "trades_per_year": safe_float(n / years),
        "hit_rate": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "payoff_ratio": 0.0,
        "profit_factor": 0.0,
        "expectancy_r": 0.0,
        "avg_r": 0.0,
        "avg_holding_days": 0.0,
        "best_r": 0.0,
        "worst_r": 0.0,
        "max_consecutive_losses": 0.0,
        "total_fees": 0.0,
    }
    if n == 0:
        return base

    pnl = np.array([safe_float(t.get("pnl")) for t in trades], dtype=float)
    r = np.array([safe_float(t.get("r_multiple")) for t in trades], dtype=float)
    hold = np.array([safe_float(t.get("holding_days")) for t in trades], dtype=float)
    fees = np.array([safe_float(t.get("fees")) for t in trades], dtype=float)

    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = float(losses.mean()) if losses.size else 0.0

    # Chuỗi thua dài nhất
    longest = cur = 0
    for v in pnl:
        cur = cur + 1 if v < 0 else 0
        longest = max(longest, cur)

    base.update(
        hit_rate=safe_float(wins.size / n),
        avg_win=safe_float(avg_win),
        avg_loss=safe_float(avg_loss),
        payoff_ratio=safe_float(abs(avg_win / avg_loss)) if avg_loss else 0.0,
        profit_factor=safe_float(gross_win / gross_loss) if gross_loss > 0 else 0.0,
        expectancy_r=safe_float(float(r.mean()) if r.size else 0.0),
        avg_r=safe_float(float(r.mean()) if r.size else 0.0),
        avg_holding_days=safe_float(float(hold.mean()) if hold.size else 0.0),
        best_r=safe_float(float(r.max()) if r.size else 0.0),
        worst_r=safe_float(float(r.min()) if r.size else 0.0),
        max_consecutive_losses=float(longest),
        total_fees=safe_float(float(fees.sum())),
    )
    return base


def monthly_returns_table(equity: np.ndarray, dates: pd.DatetimeIndex) -> list[dict[str, Any]]:
    """Bảng lợi nhuận theo tháng để hiển thị heatmap trên website."""
    if equity.size < 2 or len(dates) != equity.size:
        return []
    s = pd.Series(equity, index=pd.DatetimeIndex(dates))
    monthly = s.resample("ME").last().dropna()
    ret = monthly.pct_change().dropna()
    rows = []
    for ts, v in ret.items():
        rows.append({"year": int(ts.year), "month": int(ts.month), "return": safe_float(v)})
    return rows


def drawdown_series(equity: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(equity)
    return np.where(peak > 0, equity / peak - 1.0, 0.0)


def summarize(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Tổng hợp nhiều mã thành thống kê phân phối."""
    if not results:
        return {}
    keys = ["cagr", "sharpe", "calmar", "max_dd", "profit_factor", "hit_rate", "trades_per_year"]
    out: dict[str, Any] = {"n_symbols": len(results)}
    for k in keys:
        vals = np.array([safe_float(r.get(k)) for r in results.values()], dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        out[k] = {
            "mean": safe_float(vals.mean()),
            "median": safe_float(np.median(vals)),
            "p25": safe_float(np.percentile(vals, 25)),
            "p75": safe_float(np.percentile(vals, 75)),
            "min": safe_float(vals.min()),
            "max": safe_float(vals.max()),
            "positive_share": safe_float((vals > 0).mean()),
        }
    return out
