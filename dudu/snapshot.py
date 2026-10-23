"""Ảnh chụp trạng thái thị trường trong phiên.

Phục vụ 6 mốc làm mới mỗi ngày theo nhịp phiên HOSE (09:45, 10:00, 11:30,
13:30, 14:00, 15:00 giờ Việt Nam). Khác với pipeline nghiên cứu - vốn chỉ có ý
nghĩa khi bar ngày đã chốt - module này đọc bar đang hình thành và trả lời ba
câu hỏi vận hành:

1. Chỉ số tham chiếu và độ rộng thị trường đang thế nào?
2. Mã nào đang phát tín hiệu vào/ra lệnh theo đúng luật của chiến lược?
3. Dữ liệu đã chốt chưa, hay còn là bar dở dang của phiên đang chạy?

Cảnh báo quan trọng: trong phiên, VCI trả về bar NGÀY CHƯA HOÀN TẤT. Giá đóng
cửa của bar đó chỉ là giá khớp gần nhất, nên mọi tín hiệu đọc từ nó đều có thể
đảo chiều trước khi phiên kết thúc. Trường `is_final` đánh dấu rõ điều này và
website hiển thị cảnh báo tương ứng.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .config import BENCHMARK_SYMBOL, DEFAULT_UNIVERSE_GROUP
from .indicators import FeatureBank
from .utils import safe_float, utc_now_iso

VN_TZ = timezone(timedelta(hours=7))

# Khung giờ phiên HOSE (áp dụng từ sau chuyển đổi hệ thống KRX):
#   09:00-09:15  phiên mở cửa (ATO)
#   09:15-11:30  khớp lệnh liên tục buổi sáng
#   11:30-13:00  nghỉ trưa
#   13:00-14:30  khớp lệnh liên tục buổi chiều
#   14:30-14:45  phiên đóng cửa (ATC)
#   14:45-15:00  giao dịch thoả thuận
OPEN_ATO = time(9, 0)
OPEN_CONTINUOUS = time(9, 15)
LUNCH_START = time(11, 30)
AFTERNOON_START = time(13, 0)
ATC_START = time(14, 30)
CLOSE = time(15, 0)

SESSION_LABELS = {
    "pre_open": "Chưa mở cửa",
    "morning": "Phiên sáng",
    "lunch": "Nghỉ trưa",
    "afternoon": "Phiên chiều",
    "atc": "Phiên đóng cửa (ATC)",
    "closed": "Đã đóng cửa",
    "holiday": "Cuối tuần / ngày nghỉ",
}


def vn_now() -> datetime:
    return datetime.now(tz=VN_TZ)


def session_of(dt: datetime) -> str:
    """Nhãn phiên theo giờ Việt Nam. Trả 'holiday' cho thứ Bảy và Chủ nhật."""
    if dt.weekday() >= 5:
        return "holiday"
    t = dt.time()
    if t < OPEN_ATO:
        return "pre_open"
    if t < OPEN_CONTINUOUS:
        return "pre_open"
    if t < LUNCH_START:
        return "morning"
    if t < AFTERNOON_START:
        return "lunch"
    if t < ATC_START:
        return "afternoon"
    if t < CLOSE:
        return "atc"
    return "closed"


@dataclass
class SnapshotContext:
    universe_group: str = DEFAULT_UNIVERSE_GROUP
    benchmark: str = BENCHMARK_SYMBOL
    adv_min: float = 30e9
    entry_window: int = 55
    exit_window: int = 20
    atr_period: int = 20
    risk_per_unit: float = 0.01
    stop_atr: float = 2.0
    capital: float = 1_000_000_000.0


def _finite(x: Any) -> float | None:
    v = safe_float(x, default=float("nan"))
    return None if (v is None or not np.isfinite(v)) else float(v)


def build_snapshot(
    bank: FeatureBank,
    ctx: SnapshotContext | None = None,
    now: datetime | None = None,
    bench_close: np.ndarray | None = None,
    dataset_generated_at: str | None = None,
) -> dict[str, Any]:
    """Dựng ảnh chụp thị trường từ FeatureBank tại phiên cuối cùng của dữ liệu."""
    ctx = ctx or SnapshotContext()
    now = now or vn_now()
    panel = bank.panel
    n, m = panel.close.shape
    t = n - 1

    upper = bank.upper_ref(ctx.entry_window)[t]
    lower = bank.lower_ref(ctx.exit_window)[t]
    atr = bank.atr_ref(ctx.atr_period)[t]
    adv = bank.adv[t]
    ceiling = bank.ceiling[t]
    floor = bank.floor[t]
    regime = bank.regime[t]
    close = panel.close[t]
    prev_close = panel.close[t - 1] if n >= 2 else np.full(m, np.nan)
    high = panel.high[t]
    low = panel.low[t]
    volume = panel.volume[t]

    bar_date = pd.Timestamp(panel.dates[t])
    today = pd.Timestamp(now.date())
    is_final = bool(bar_date < today) or session_of(now) == "closed"
    has_new_session = bool(bar_date >= today)

    rows: list[dict[str, Any]] = []
    for j, sym in enumerate(panel.symbols):
        c = _finite(close[j])
        pc = _finite(prev_close[j])
        if c is None or c <= 0:
            continue
        chg = (c / pc - 1.0) if (pc and pc > 0) else 0.0
        u = _finite(upper[j])
        lo = _finite(lower[j])
        a = _finite(atr[j])
        a20 = _finite(adv[j])
        ce = _finite(ceiling[j])
        fl = _finite(floor[j])
        turnover = c * safe_float(volume[j])
        at_ceiling = bool(ce and c >= ce - 1e-9)
        at_floor = bool(fl and c <= fl + 1e-9)
        breakout = bool(u and c > u)
        rows.append(
            {
                "symbol": sym,
                "close": round(c, 1),
                "prev_close": round(pc, 1) if pc else None,
                "change_pct": round(chg, 5),
                "high": round(_finite(high[j]) or c, 1),
                "low": round(_finite(low[j]) or c, 1),
                "volume": int(safe_float(volume[j])),
                "turnover_bn": round(turnover / 1e9, 3),
                "adv20_bn": round((a20 or 0.0) / 1e9, 3),
                "passes_adv": bool(a20 is not None and a20 >= ctx.adv_min),
                "donchian_upper": round(u, 1) if u else None,
                "donchian_lower": round(lo, 1) if lo else None,
                "dist_to_upper_pct": round(c / u - 1.0, 5) if u else None,
                "atr": round(a, 1) if a else None,
                "atr_pct": round(a / c, 5) if a else None,
                "at_ceiling": at_ceiling,
                "at_floor": at_floor,
                "signal_entry": bool(breakout and not at_ceiling and (a20 is not None and a20 >= ctx.adv_min) and bool(regime[j])),
                "signal_exit": bool(lo and c < lo),
                "above_upper": breakout,
                "market_regime_bull": bool(regime[j]),
                # Định cỡ Unit theo đúng công thức engine dùng
                "unit_shares": int(_unit_shares(c, a, ctx) or 0),
            }
        )

    changes = np.array([r["change_pct"] for r in rows], dtype=float)
    turnover_total = float(sum(r["turnover_bn"] for r in rows))
    n_adv = int(sum(1 for r in rows if r["passes_adv"]))
    entries = [r for r in rows if r["signal_entry"]]
    exits = [r for r in rows if r["signal_exit"]]
    ceilings = [r for r in rows if r["at_ceiling"]]
    floors = [r for r in rows if r["at_floor"]]

    bench_info: dict[str, Any] = {"symbol": ctx.benchmark}
    if bench_close is not None and len(bench_close) >= 2:
        b = np.asarray(bench_close, dtype=float)
        b = b[np.isfinite(b)]
        if b.size >= 2:
            bench_info.update(
                close=round(float(b[-1]), 2),
                change_pct=round(float(b[-1] / b[-2] - 1.0), 5),
            )
        if b.size >= 200:
            sma200 = float(np.mean(b[-200:]))
            bench_info.update(sma200=round(sma200, 2), above_sma200=bool(b[-1] > sma200))

    # Tích hợp đánh giá từ Hội Đồng Đa Chuyên Gia AI (Multi-Advisor AI Council)
    advisors_eval: dict[str, Any] = {}
    trade_kpis: dict[str, Any] = {}
    try:
        from .advisors import AdvisorCouncil
        from .execution import LedgerManager
        from pathlib import Path

        # 1. Đánh giá vũ trụ cổ phiếu qua Hội Đồng AI
        council = AdvisorCouncil()
        symbol_dfs: dict[str, pd.DataFrame] = {}
        # Lấy tối đa 120 phiên gần nhất cho mỗi mã
        n_bars = min(120, n)
        recent_dates = panel.dates[-n_bars:]
        for j, sym in enumerate(panel.symbols):
            c_s = panel.close[-n_bars:, j]
            if np.all(np.isnan(c_s)):
                continue
            symbol_dfs[sym] = pd.DataFrame(
                {
                    "time": recent_dates,
                    "open": panel.open[-n_bars:, j],
                    "high": panel.high[-n_bars:, j],
                    "low": panel.low[-n_bars:, j],
                    "close": c_s,
                    "volume": panel.volume[-n_bars:, j],
                }
            )

        bench_df = None
        if bench_close is not None and len(bench_close) >= n_bars:
            bench_df = pd.DataFrame({
                "time": recent_dates,
                "close": bench_close[-n_bars:],
            })

        advisors_eval = council.evaluate_universe(symbol_dfs, benchmark_df=bench_df)

        # 2. Thống kê KPI Sổ lệnh thực chiến từ ledger
        hist_p = Path(__file__).resolve().parent.parent / "site" / "data" / "trade_history.json"
        if not hist_p.exists():
            hist_p = Path(__file__).resolve().parent.parent / "data" / "trade_history_2025_2026.json"
        if hist_p.exists():
            ledger = LedgerManager.from_json(hist_p)
            trade_kpis = ledger.summary_kpis()
    except Exception as exc:
        pass

    return {
        "as_of": now.isoformat(timespec="seconds"),
        "as_of_utc": utc_now_iso(),
        "session": session_of(now),
        "session_label": SESSION_LABELS[session_of(now)],
        "is_trading_day": now.weekday() < 5,
        "bar_date": str(bar_date.date()),
        "has_new_session": has_new_session,
        "is_final": is_final,
        "dataset_generated_at": dataset_generated_at,
        "universe_group": ctx.universe_group,
        "n_symbols": len(rows),
        "benchmark": bench_info,
        "breadth": {
            "up": int((changes > 0).sum()),
            "down": int((changes < 0).sum()),
            "flat": int((changes == 0).sum()),
            "up_share": round(float((changes > 0).mean()), 4) if changes.size else 0.0,
            "median_change_pct": round(float(np.median(changes)), 5) if changes.size else 0.0,
        },
        "liquidity": {
            "turnover_total_bn": round(turnover_total, 1),
            "n_passes_adv": n_adv,
            "adv_pass_share": round(n_adv / len(rows), 4) if rows else 0.0,
            "adv_min_bn": round(ctx.adv_min / 1e9, 1),
        },
        "signals": {
            "n_entry": len(entries),
            "n_exit": len(exits),
            "n_above_upper": int(sum(1 for r in rows if r["above_upper"])),
            "n_at_ceiling": len(ceilings),
            "n_at_floor": len(floors),
            "n_regime_bull": int(sum(1 for r in rows if r["market_regime_bull"])),
            "entry_symbols": [
                {"symbol": r["symbol"], "close": r["close"], "change_pct": r["change_pct"],
                 "turnover_bn": r["turnover_bn"], "units": r["unit_shares"],
                 "dist_to_upper_pct": r["dist_to_upper_pct"]}
                for r in sorted(entries, key=lambda x: -x["turnover_bn"])[:30]
            ],
            "exit_symbols": [
                {"symbol": r["symbol"], "close": r["close"], "change_pct": r["change_pct"]}
                for r in sorted(exits, key=lambda x: x["change_pct"])[:20]
            ],
        },
        "leaders": {
            "gainers": sorted(rows, key=lambda r: -r["change_pct"])[:8],
            "losers": sorted(rows, key=lambda r: r["change_pct"])[:8],
            "turnover": sorted(rows, key=lambda r: -r["turnover_bn"])[:8],
        },
        "advisors_evaluation": advisors_eval,
        "trade_kpis": trade_kpis,
        "symbols": rows,
        "disclaimer": (
            "Trong phiên, giá đóng cửa là giá khớp gần nhất của bar ngày chưa hoàn tất; "
            "tín hiệu có thể đảo chiều trước khi phiên kết thúc."
        ),
    }


def _unit_shares(price: float, n_value: float | None, ctx: SnapshotContext) -> int:
    """Khối lượng một Unit theo công thức engine (chế độ risk), đã áp trần 20% NAV."""
    if not n_value or n_value <= 0 or price <= 0:
        return 0
    raw = (ctx.risk_per_unit * ctx.capital) / (ctx.stop_atr * n_value)
    raw = min(raw, 0.20 * ctx.capital / price)
    return int(raw // 100 * 100)


def history_entry(snap: dict[str, Any]) -> dict[str, Any]:
    """Rút gọn snapshot thành một dòng lịch sử để vẽ diễn biến trong ngày."""
    b = snap.get("benchmark", {})
    return {
        "as_of": snap["as_of"],
        "session": snap["session"],
        "session_label": snap["session_label"],
        "bar_date": snap["bar_date"],
        "is_final": snap["is_final"],
        "vnindex": b.get("close"),
        "vnindex_change_pct": b.get("change_pct"),
        "above_sma200": b.get("above_sma200"),
        "up_share": snap["breadth"]["up_share"],
        "median_change_pct": snap["breadth"]["median_change_pct"],
        "turnover_bn": snap["liquidity"]["turnover_total_bn"],
        "adv_pass_share": snap["liquidity"]["adv_pass_share"],
        "n_entry": snap["signals"]["n_entry"],
        "n_exit": snap["signals"]["n_exit"],
        "n_at_ceiling": snap["signals"]["n_at_ceiling"],
        "n_at_floor": snap["signals"]["n_at_floor"],
    }


def append_history(history: list[dict[str, Any]], entry: dict[str, Any], cap: int = 600) -> list[dict[str, Any]]:
    """Thêm dòng mới, bỏ dòng trùng thời điểm, giữ tối đa `cap` dòng gần nhất."""
    out = [h for h in history if h.get("as_of") != entry.get("as_of")]
    out.append(entry)
    return out[-cap:]
