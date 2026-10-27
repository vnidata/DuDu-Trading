import numpy as np
import pandas as pd
import pytest

from dudu.execution.venue_chain import (
    TRANSFER,
    FORCED_DELIST,
    UNRESOLVED_TERMINAL,
    REVIEW,
    GapConfig,
    classify_gaps,
    resolve_position_over_gap,
)

CAL = pd.bdate_range("2025-11-03", "2026-08-31")  # lịch phiên đơn giản (bỏ qua ngày lễ)


def make_bars(dates, price_before, price_after=None, split=None, vol=1e6):
    n = len(dates)
    px = np.full(n, float(price_before))
    if split is not None:
        px[split:] = price_after
    return pd.DataFrame({"open": px, "close": px, "volume": np.full(n, vol)}, index=dates)


def test_mch_like_transfer_is_not_delisting():
    # phiên cuối UPCoM 17/12/2025 (170.390), chào sàn HOSE 25/12/2025 (mở 176.400)
    before = CAL[(CAL >= "2025-11-05") & (CAL <= "2025-12-17")]
    after = CAL[(CAL >= "2025-12-25") & (CAL <= "2026-01-20")]
    dates = before.append(after)
    bars = make_bars(dates, 170390, 176400, split=len(before))
    gaps = classify_gaps(bars, CAL[CAL <= dates[-1]])
    assert len(gaps) == 1 and gaps.kind[0] == TRANSFER
    assert gaps.gap_sessions[0] == 5 and not gaps.needs_review[0]


def test_bvb_like_transfer():
    before = CAL[(CAL >= "2026-06-23") & (CAL <= "2026-07-08")]
    after = CAL[(CAL >= "2026-07-21") & (CAL <= "2026-08-10")]
    bars = make_bars(before.append(after), 12953, 13050, split=len(before))
    gaps = classify_gaps(bars, CAL[CAL <= after[-1]])
    assert gaps.kind[0] == TRANSFER and gaps.gap_sessions[0] == 8


def test_position_locked_over_transfer_not_haircut():
    r = resolve_position_over_gap(TRANSFER, last_close=170390, first_open=176400, stop_level=150000)
    assert r["action"] == "HOLD" and r["locked"]


def test_gap_through_stop_exits_at_open_not_stop():
    r = resolve_position_over_gap(TRANSFER, last_close=100, first_open=88, stop_level=92)
    assert r["action"] == "EXIT" and r["price"] == 88


def test_terminal_without_event_is_unresolved_not_haircut():
    dates = CAL[(CAL >= "2026-01-05") & (CAL <= "2026-03-31")]
    gaps = classify_gaps(make_bars(dates, 10), CAL)
    assert gaps.kind.iloc[-1] == UNRESOLVED_TERMINAL and gaps.needs_review.iloc[-1]
    assert resolve_position_over_gap(UNRESOLVED_TERMINAL, 10, None, 9)["action"] == "REVIEW"


def test_event_table_overrides_and_applies_haircut_scenarios():
    dates = CAL[(CAL >= "2026-01-05") & (CAL <= "2026-03-31")]
    ev = pd.DataFrame([dict(ticker="XYZ", event_type=FORCED_DELIST,
                            last_session="2026-03-31", first_session=pd.NaT)])
    gaps = classify_gaps(make_bars(dates, 10), CAL, events=ev, ticker="XYZ")
    assert gaps.kind.iloc[-1] == FORCED_DELIST and not gaps.needs_review.iloc[-1]
    for h in (0.0, 0.3, 0.5, 0.7):
        assert resolve_position_over_gap(FORCED_DELIST, 10, None, 9, haircut=h)["price"] == pytest.approx(10 * (1 - h))


def test_discontinuous_return_is_flagged_for_review():
    before = CAL[(CAL >= "2026-01-05") & (CAL <= "2026-02-10")]
    after = CAL[(CAL >= "2026-02-20") & (CAL <= "2026-03-31")]
    bars = make_bars(before.append(after), 10, 16, split=len(before))  # nhảy +60%
    gaps = classify_gaps(bars, CAL[CAL <= after[-1]])
    assert gaps.kind[0] == REVIEW and gaps.needs_review[0]


def test_short_halts_ignored():
    d = CAL[(CAL >= "2026-01-05") & (CAL <= "2026-01-20")]
    d = d.delete(5)  # thiếu 1 phiên
    assert classify_gaps(make_bars(d, 10), CAL, cfg=GapConfig(terminal_lag_sessions=10**6)).empty


def test_state_machine_locked_and_gap_through():
    from dudu.execution.venue_chain import GapStateMachine

    sm = GapStateMachine(mode="production", max_missing_sessions=5)
    # Phiên 1: bình thường
    r1 = sm.on_session_bar("XYZ", 0, "2026-01-02", 100.0, 102.0, stop_level=95.0)
    assert r1["state"] == "ACTIVE"

    # Phiên 2: thiếu nến (NaN)
    r2 = sm.on_session_bar("XYZ", 1, "2026-01-05", None, None, stop_level=95.0)
    assert r2["state"] == "LOCKED" and r2["action"] == "HOLD_LOCKED"

    # Phiên 3: trở lại nhưng gap-down xuyên qua stop (open 90 < stop 95)
    r3 = sm.on_session_bar("XYZ", 2, "2026-01-06", open_px=90.0, close_px=92.0, stop_level=95.0)
    assert r3["state"] == "RESUMED_GAP_STOP" and r3["action"] == "GAP_EXIT" and r3["price"] == 90.0


def test_state_machine_modes_research_vs_production():
    from dudu.execution.venue_chain import GapStateMachine

    # Production mode: ném exception khi khuyết quá ngưỡng
    sm_prod = GapStateMachine(mode="production", max_missing_sessions=2)
    sm_prod.on_session_bar("ABC", 0, "2026-01-02", 50.0, 50.0, stop_level=45.0)
    sm_prod.on_session_bar("ABC", 1, "2026-01-05", None, None, stop_level=45.0)
    sm_prod.on_session_bar("ABC", 2, "2026-01-06", None, None, stop_level=45.0)
    with pytest.raises(RuntimeError, match="khuyết"):
        sm_prod.on_session_bar("ABC", 3, "2026-01-07", None, None, stop_level=45.0)

    # Research mode: không sập tiến trình, chuyển sang STUCK
    sm_res = GapStateMachine(mode="research", max_missing_sessions=2)
    sm_res.on_session_bar("ABC", 0, "2026-01-02", 50.0, 50.0, stop_level=45.0)
    sm_res.on_session_bar("ABC", 1, "2026-01-05", None, None, stop_level=45.0)
    sm_res.on_session_bar("ABC", 2, "2026-01-06", None, None, stop_level=45.0)
    r = sm_res.on_session_bar("ABC", 3, "2026-01-07", None, None, stop_level=45.0)
    assert r["state"] == "STUCK" and r["action"] == "HOLD_STUCK"

