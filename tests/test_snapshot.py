"""Kiểm thử ảnh chụp thị trường trong phiên và nhịp làm mới dữ liệu."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dudu.data import CachePolicy
from dudu.snapshot import (
    SESSION_LABELS,
    SnapshotContext,
    VN_TZ,
    _unit_shares,
    append_history,
    build_snapshot,
    history_entry,
    session_of,
)

from .test_engine import make_bank, synthetic_symbol


def vn(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=VN_TZ)


# --------------------------------------------------------------------------
# Nhãn phiên
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "dt,expected",
    [
        (vn(2026, 10, 12, 8, 59), "pre_open"),
        (vn(2026, 10, 12, 9, 0), "pre_open"),      # ATO bắt đầu, chưa khớp liên tục
        (vn(2026, 10, 12, 9, 14), "pre_open"),
        (vn(2026, 10, 12, 9, 15), "morning"),
        (vn(2026, 10, 12, 9, 45), "morning"),      # mốc 1
        (vn(2026, 10, 12, 10, 0), "morning"),      # mốc 2
        (vn(2026, 10, 12, 11, 29), "morning"),
        (vn(2026, 10, 12, 11, 30), "lunch"),       # mốc 3 - hết phiên sáng
        (vn(2026, 10, 12, 12, 59), "lunch"),
        (vn(2026, 10, 12, 13, 0), "afternoon"),
        (vn(2026, 10, 12, 13, 30), "afternoon"),   # mốc 4
        (vn(2026, 10, 12, 14, 0), "afternoon"),    # mốc 5
        (vn(2026, 10, 12, 14, 30), "atc"),
        (vn(2026, 10, 12, 14, 59), "atc"),
        (vn(2026, 10, 12, 15, 0), "closed"),       # mốc 6
        (vn(2026, 10, 12, 22, 0), "closed"),
    ],
)
def test_session_of_boundaries(dt, expected):
    assert session_of(dt) == expected


def test_session_of_weekend_is_holiday():
    assert session_of(vn(2026, 10, 10, 10, 0)) == "holiday"   # thứ Bảy
    assert session_of(vn(2026, 10, 11, 10, 0)) == "holiday"   # Chủ nhật
    assert set(SESSION_LABELS) >= {"pre_open", "morning", "lunch", "afternoon", "atc", "closed", "holiday"}


# --------------------------------------------------------------------------
# Lịch sử ảnh chụp
# --------------------------------------------------------------------------
def test_history_entry_extracts_compact_row():
    snap = {
        "as_of": "2026-10-12T10:00:00+07:00",
        "session": "morning",
        "session_label": "Phiên sáng",
        "bar_date": "2026-10-12",
        "is_final": False,
        "benchmark": {"close": 1750.5, "change_pct": 0.004, "above_sma200": True},
        "breadth": {"up_share": 0.6, "median_change_pct": 0.002},
        "liquidity": {"turnover_total_bn": 5000.0, "adv_pass_share": 0.5},
        "signals": {"n_entry": 3, "n_exit": 1, "n_at_ceiling": 2, "n_at_floor": 0},
    }
    row = history_entry(snap)
    assert row["vnindex"] == 1750.5
    assert row["up_share"] == 0.6
    assert row["n_entry"] == 3
    assert row["above_sma200"] is True


def test_append_history_dedupes_and_caps():
    hist: list[dict] = []
    for i in range(5):
        hist = append_history(hist, {"as_of": f"2026-10-12T10:0{i}:00+07:00", "n": i}, cap=10)
    assert len(hist) == 5
    # Ghi lại cùng mốc thời gian phải thay thế, không nhân đôi
    hist = append_history(hist, {"as_of": "2026-10-12T10:02:00+07:00", "n": 99}, cap=10)
    assert len(hist) == 5
    assert hist[-1]["n"] == 99
    # Vượt trần thì cắt từ đầu
    for i in range(20):
        hist = append_history(hist, {"as_of": f"2026-10-13T09:{i:02d}:00+07:00"}, cap=10)
    assert len(hist) == 10


# --------------------------------------------------------------------------
# Ảnh chụp
# --------------------------------------------------------------------------
def test_build_snapshot_shape():
    frames = {f"S{i}": synthetic_symbol(n=400, seed=200 + i) for i in range(3)}
    b = make_bank(frames)
    snap = build_snapshot(b, SnapshotContext(), now=vn(2026, 10, 12, 10, 0))
    assert snap["n_symbols"] == 3
    assert snap["session"] == "morning"
    assert snap["session_label"] == "Phiên sáng"
    # Dữ liệu tổng hợp kết thúc năm 2019 nên bar đã chốt và không có phiên mới
    assert snap["is_final"] is True
    assert snap["has_new_session"] is False
    assert set(snap["signals"]) >= {"n_entry", "n_exit", "entry_symbols", "exit_symbols"}
    assert len(snap["symbols"]) == 3
    for key in ("symbol", "close", "change_pct", "turnover_bn", "adv20_bn", "passes_adv", "signal_entry", "signal_exit"):
        assert key in snap["symbols"][0]
    assert snap["breadth"]["up"] + snap["breadth"]["down"] + snap["breadth"]["flat"] == 3
    assert 0.0 <= snap["liquidity"]["adv_pass_share"] <= 1.0


def test_build_snapshot_final_only_after_close():
    frames = {"S0": synthetic_symbol(n=400, seed=7)}
    b = make_bank(frames)
    bar_date = pd.Timestamp(b.panel.dates[-1]).date()
    during = build_snapshot(b, SnapshotContext(), now=datetime(bar_date.year, bar_date.month, bar_date.day, 10, 0, tzinfo=VN_TZ))
    after = build_snapshot(b, SnapshotContext(), now=datetime(bar_date.year, bar_date.month, bar_date.day, 15, 30, tzinfo=VN_TZ))
    assert during["is_final"] is False
    assert after["is_final"] is True
    assert during["bar_date"] == after["bar_date"]


def test_market_regime_gate_blocks_every_entry():
    """Khi chỉ số chung dưới SMA200, không mã nào được phát tín hiệu vào lệnh."""
    frames = {f"S{i}": synthetic_symbol(n=500, seed=300 + i, drift=0.004) for i in range(3)}
    panel_bank = make_bank(frames)
    # Bật lại regime = False cho toàn bộ
    panel_bank.regime[:] = False
    snap = build_snapshot(panel_bank, SnapshotContext(), now=vn(2026, 10, 12, 10, 0))
    assert snap["signals"]["n_entry"] == 0
    assert all(r["signal_entry"] is False for r in snap["symbols"])
    assert snap["signals"]["n_regime_bull"] == 0


def test_snapshot_detects_ceiling_and_floor():
    n = 300
    prev = 20_000.0
    ceiling = 21_400.0    # 20.000 × 1,07 làm tròn xuống bước giá 50
    floor = 18_600.0      # 20.000 × 0,93 làm tròn lên bước giá 50

    def frame(last_close: float, seed: int) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        close = np.full(n, prev)
        close[-1] = last_close
        high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
        low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
        high[-1] = max(high[-1], last_close)
        low[-1] = min(low[-1], last_close)
        return pd.DataFrame({
            "time": pd.bdate_range("2018-01-02", periods=n),
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": high, "low": low, "close": close,
            "volume": np.full(n, 5e6),
        })

    b = make_bank({"TRAN": frame(ceiling, 1), "SAN": frame(floor, 2)})
    snap = build_snapshot(b, SnapshotContext(), now=vn(2026, 10, 12, 10, 0))
    by = {r["symbol"]: r for r in snap["symbols"]}
    assert by["TRAN"]["at_ceiling"] is True
    assert by["TRAN"]["at_floor"] is False
    assert by["SAN"]["at_floor"] is True
    assert by["SAN"]["at_ceiling"] is False
    # Mã đóng cửa tại giá trần không được phát tín hiệu vào lệnh
    assert by["TRAN"]["signal_entry"] is False
    assert snap["signals"]["n_at_ceiling"] == 1
    assert snap["signals"]["n_at_floor"] == 1


def test_unit_shares_formula_and_cap():
    ctx = SnapshotContext(capital=1_000_000_000.0, risk_per_unit=0.01, stop_atr=2.0)
    # N = 600 VND, giá 20.000 -> 1e7 / 1.200 = 8.333 -> làm tròn lô 100
    assert _unit_shares(20_000.0, 600.0, ctx) == 8_300
    # N rất nhỏ -> chạm trần 20% NAV/Unit = 1e9*0,2/20.000 = 10.000 cổ phiếu
    assert _unit_shares(20_000.0, 1.0, ctx) == 10_000
    assert _unit_shares(20_000.0, 0.0, ctx) == 0
    assert _unit_shares(0.0, 600.0, ctx) == 0


def test_snapshot_leaders_are_sorted():
    frames = {"UP": synthetic_symbol(n=400, seed=11), "DOWN": synthetic_symbol(n=400, seed=12)}
    b = make_bank(frames)
    snap = build_snapshot(b, SnapshotContext(), now=vn(2026, 10, 12, 14, 0))
    gainers = [r["change_pct"] for r in snap["leaders"]["gainers"]]
    losers = [r["change_pct"] for r in snap["leaders"]["losers"]]
    turnover = [r["turnover_bn"] for r in snap["leaders"]["turnover"]]
    assert gainers == sorted(gainers, reverse=True)
    assert losers == sorted(losers)
    assert turnover == sorted(turnover, reverse=True)


# --------------------------------------------------------------------------
# Ngưỡng cache theo phút
# --------------------------------------------------------------------------
def test_cache_policy_max_age_minutes(tmp_path: Path):
    import os

    p = tmp_path / "X_2016.csv.gz"
    p.write_bytes(b"x")
    policy = CachePolicy(max_age_minutes=5)
    assert policy.is_fresh(p) is True
    # Giả lập tệp cũ 10 phút -> quá ngưỡng 5 phút
    old = time.time() - 600
    os.utime(p, (old, old))
    assert policy.is_fresh(p) is False
    # Không đặt max_age_minutes thì quay về ngưỡng ngày (3 ngày = 259.200 giây)
    assert CachePolicy(max_age_days=3).is_fresh(p) is True
    assert CachePolicy(max_age_days=0).is_fresh(p) is False
    # Tệp không tồn tại luôn là không tươi
    assert CachePolicy().is_fresh(tmp_path / "missing.csv.gz") is False


def test_vn_tz_offset_is_seven_hours():
    assert VN_TZ.utcoffset(None) == timedelta(hours=7)
