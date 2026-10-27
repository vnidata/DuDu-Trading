"""Nối chuỗi dữ liệu qua khoảng trống giao dịch: chuyển sàn vs đình chỉ vs hủy niêm yết.

Nguyên tắc:
1. Có bảng sự kiện point-in-time (events) thì dùng nó, không đoán.
2. Không có sự kiện thì phân loại bằng quy tắc dữ liệu, CHỈ dùng trong backtest (dùng thông tin sau
   khoảng trống). Chế độ live phải dựa vào thông báo của sàn.
3. Chuỗi kết thúc mà không có sự kiện -> UNRESOLVED_TERMINAL (cần xem xét), KHÔNG tự động haircut.
4. Vị thế bị KHÓA trong khoảng trống chuyển sàn: không khớp được, stop chỉ xét ở phiên đầu tiên sau chuyển.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

TRANSFER = "TRANSFER"
SUSPENSION = "SUSPENSION"
FORCED_DELIST = "FORCED_DELIST"
UNRESOLVED_TERMINAL = "UNRESOLVED_TERMINAL"
REVIEW = "REVIEW"


@dataclass
class GapConfig:
    min_gap_sessions: int = 3        # ngắn hơn: coi là dừng giao dịch bình thường, bỏ qua
    max_transfer_sessions: int = 20  # xuất hiện lại trong vòng N phiên thì mới là ứng viên chuyển sàn
    max_jump: float = 0.25           # |giá sau / giá trước - 1| tối đa để coi là liên tục
    min_resume_vol_ratio: float = 0.2  # khối lượng sau >= 20% trung vị 20 phiên trước
    terminal_lag_sessions: int = 5   # chuỗi kết thúc cách cuối lịch >= N phiên mới coi là kết thúc


def _session_pos(calendar: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(np.arange(len(calendar)), index=calendar)


def classify_gaps(
    bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    cfg: GapConfig = GapConfig(),
    events: Optional[pd.DataFrame] = None,
    ticker: Optional[str] = None,
) -> pd.DataFrame:
    """Trả về mỗi khoảng trống một dòng: kind, gap_sessions, last_date, first_date, jump, needs_review.

    bars: index DatetimeIndex, cột open/close/volume (đã sắp xếp).
    calendar: các phiên giao dịch của thị trường (ví dụ ngày của VN-Index).
    events: cột ticker, event_type, last_session, first_session (first_session có thể NaT).
    """
    pos = _session_pos(calendar)
    idx = bars.index
    rows = []

    def from_events(last_d):
        if events is None or ticker is None:
            return None
        m = events[(events.ticker == ticker) & (pd.to_datetime(events.last_session) == last_d)]
        return None if m.empty else m.iloc[0]

    # khoảng trống bên trong chuỗi
    for i in range(len(idx) - 1):
        a, b = idx[i], idx[i + 1]
        missing = int(pos[b] - pos[a] - 1)
        if missing < cfg.min_gap_sessions:
            continue
        jump = bars.close.iloc[i + 1] / bars.close.iloc[i] - 1.0
        pre_vol = bars.volume.iloc[max(0, i - 19): i + 1].median()
        post_vol = bars.volume.iloc[i + 1: i + 6].median()
        ev = from_events(a)
        if ev is not None:
            kind, review = ev.event_type, False
        elif (missing <= cfg.max_transfer_sessions and abs(jump) <= cfg.max_jump
              and post_vol >= cfg.min_resume_vol_ratio * pre_vol):
            kind, review = TRANSFER, False
        elif missing <= cfg.max_transfer_sessions:
            kind, review = REVIEW, True        # quay lại nhưng giá/khối lượng không liên tục
        else:
            kind, review = SUSPENSION, True    # đình chỉ dài: cần xem xét thủ công
        rows.append(dict(kind=kind, gap_sessions=missing, last_date=a, first_date=b,
                         jump=float(jump), needs_review=review))

    # chuỗi kết thúc sớm
    last = idx[-1]
    lag = int(len(calendar) - 1 - pos[last])
    if lag >= cfg.terminal_lag_sessions:
        ev = from_events(last)
        if ev is not None:
            rows.append(dict(kind=ev.event_type, gap_sessions=lag, last_date=last,
                             first_date=pd.NaT, jump=np.nan, needs_review=False))
        else:
            rows.append(dict(kind=UNRESOLVED_TERMINAL, gap_sessions=lag, last_date=last,
                             first_date=pd.NaT, jump=np.nan, needs_review=True))
    return pd.DataFrame(rows, columns=["kind", "gap_sessions", "last_date", "first_date",
                                       "jump", "needs_review"])


def resolve_position_over_gap(kind: str, last_close: float, first_open: float | None,
                              stop_level: float, haircut: float = 0.50) -> dict:
    """Quy tắc mô phỏng vị thế dài khi gặp khoảng trống.

    TRANSFER/SUSPENSION: vị thế khóa. Phiên đầu tiên sau đó: nếu mở cửa dưới stop thì thoát tại giá mở
    cửa (gap-through, không phải tại stop), ngược lại giữ tiếp.
    FORCED_DELIST: thanh lý tại last_close * (1 - haircut); haircut nên chạy theo kịch bản (0/30/50/70%).
    UNRESOLVED_TERMINAL/REVIEW: không tự quyết, dừng để người xem.
    """
    if kind in (TRANSFER, SUSPENSION):
        if first_open is None:
            raise ValueError("thiếu giá mở cửa phiên đầu sau khoảng trống")
        if first_open < stop_level:
            return dict(action="EXIT", price=first_open, locked=True)
        return dict(action="HOLD", price=None, locked=True)
    if kind == FORCED_DELIST:
        return dict(action="EXIT", price=last_close * (1.0 - haircut), locked=False)
    return dict(action="REVIEW", price=None, locked=False)


class GapStateMachine:
    """State Machine quản lý trạng thái vị thế khi gặp ô NaN hoặc khoảng trống giao dịch.

    Hỗ trợ 2 chế độ:
    - 'research': Không ném exception làm sập GA khi quét hàng nghìn lần đánh giá;
                  ghi nhận vào bảng sự kiện, đánh dấu STUCK và định giá theo kịch bản haircut.
    - 'production': Nghiêm ngặt (ném lỗi nếu khoảng trống vượt ngưỡng N phiên mà không có sự kiện xác nhận).
    """

    def __init__(self, mode: str = "research", max_missing_sessions: int = 20):
        self.mode = mode
        self.max_missing = max_missing_sessions
        # Trạng thái theo mã: {sym: {"missing_count": 0, "last_close": px, "locked": True}}
        self.tracking: dict[str, dict] = {}
        self.event_log: list[dict] = []

    def on_session_bar(
        self,
        symbol: str,
        t: int,
        date_str: str,
        open_px: float | None,
        close_px: float | None,
        stop_level: float,
        has_confirmed_delist: bool = False,
        haircut: float = 0.50,
    ) -> dict:
        """Đánh giá trạng thái tại mỗi phiên cho một vị thế đang nắm giữ."""
        is_missing = close_px is None or np.isnan(close_px) or close_px <= 0

        if is_missing:
            # 1. Gặp ô NaN: Khóa vị thế, tăng biến đếm số phiên khuyết
            rec = self.tracking.setdefault(
                symbol, {"missing_count": 0, "last_close": None, "locked": True, "start_date": date_str}
            )
            rec["missing_count"] += 1

            if rec["missing_count"] > self.max_missing:
                if has_confirmed_delist:
                    rec["locked"] = False
                    return dict(action="EXIT", price=rec["last_close"] * (1.0 - haircut), state="FORCED_DELIST")
                if self.mode == "production":
                    raise RuntimeError(
                        f"Mã {symbol} khuyết {rec['missing_count']} phiên không có thông báo xác nhận hủy niêm yết."
                    )
                # Chế độ research: đánh dấu STUCK, không sập tiến trình
                self.event_log.append(
                    {"symbol": symbol, "date": date_str, "state": "STUCK", "missing": rec["missing_count"]}
                )
                return dict(action="HOLD_STUCK", price=rec["last_close"], state="STUCK")

            return dict(action="HOLD_LOCKED", price=rec["last_close"], state="LOCKED")

        # 2. Phiên có nến trở lại (nếu trước đó bị locked)
        if symbol in self.tracking and self.tracking[symbol]["missing_count"] > 0:
            rec = self.tracking[symbol]
            missing = rec["missing_count"]
            self.tracking.pop(symbol, None)

            # Phiên đầu tiên xuất hiện lại: Gap-through stop evaluation
            actual_open = open_px if (open_px is not None and not np.isnan(open_px) and open_px > 0) else close_px
            if actual_open < stop_level:
                return dict(action="GAP_EXIT", price=actual_open, state="RESUMED_GAP_STOP", missing=missing)
            return dict(action="RESUME", price=close_px, state="ACTIVE", missing=missing)

        # 3. Phiên bình thường
        if symbol in self.tracking:
            self.tracking[symbol]["last_close"] = close_px
        else:
            self.tracking[symbol] = {"missing_count": 0, "last_close": close_px, "locked": False, "start_date": date_str}

        return dict(action="NORMAL", price=close_px, state="ACTIVE")
