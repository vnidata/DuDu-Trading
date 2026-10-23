"""Cơ chế khóa an toàn phân vùng Holdout (Holdout Safety Lock).

Kế thừa từ VN-SWING:
Bảo vệ vùng dữ liệu thực chiến ngoài mẫu (từ 2025-01-01 trở đi).
Chặn đứng việc look-ahead và p-hacking trên tập holdout trong quá trình
huấn luyện và tối ưu hóa tham số.
"""

from __future__ import annotations

from typing import Iterable, Sequence
import pandas as pd


DEFAULT_HOLDOUT_START = "2025-01-01"


class HoldoutLock:
    """Khóa an toàn dữ liệu vùng Holdout chống rò rỉ dữ liệu và tối ưu hóa quá mức."""

    def __init__(self, holdout_start: str = DEFAULT_HOLDOUT_START, is_unlocked: bool = False):
        self.holdout_start = pd.Timestamp(holdout_start)
        self.is_unlocked = is_unlocked

    def verify_date(self, target_date: str | pd.Timestamp) -> bool:
        """Kiểm tra ngày. Ném lỗi PermissionError nếu vi phạm vùng Holdout."""
        t = pd.Timestamp(target_date)
        if not self.is_unlocked and t >= self.holdout_start:
            raise PermissionError(
                f"[HOLDOUT VIOLATION] Cố tình truy cập dữ liệu vùng Holdout "
                f"({t.strftime('%Y-%m-%d')} >= {self.holdout_start.strftime('%Y-%m-%d')}) "
                f"mà không có quyền mở khóa (--unlock-holdout). "
                f"Khóa an toàn chống p-hacking cấp mã nguồn đang được kích hoạt."
            )
        return True

    def filter_safe_dates(self, dates: Sequence[str | pd.Timestamp]) -> list[pd.Timestamp]:
        """Lọc danh sách ngày an toàn trong vùng In-Sample."""
        if self.is_unlocked:
            return [pd.Timestamp(d) for d in dates]
        return [pd.Timestamp(d) for d in dates if pd.Timestamp(d) < self.holdout_start]


def check_holdout_boundary(
    end_date: str | pd.Timestamp,
    holdout_start: str = DEFAULT_HOLDOUT_START,
    unlock: bool = False,
) -> bool:
    """Hàm tiện ích kiểm tra nhanh biên giới vùng holdout."""
    lock = HoldoutLock(holdout_start=holdout_start, is_unlocked=unlock)
    return lock.verify_date(end_date)
