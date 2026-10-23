"""Kiểm thử cơ chế khóa an toàn phân vùng dữ liệu Holdout (Holdout Safety Lock).

Kế thừa từ VN-SWING:
Bảo đảm không có mã lệnh nào được phép truy cập dữ liệu từ 2025-01-01 trở đi
nếu không có sự cho phép rõ ràng (--unlock-holdout), ngăn chặn triệt để
hiện tượng nhìn trước tương lai và p-hacking.
"""

from __future__ import annotations

import pytest
import pandas as pd

from dudu.execution.holdout import HoldoutLock, check_holdout_boundary


def test_holdout_violation_raises_error():
    """Truy cập ngày nằm trong vùng Holdout (>= 2025-01-01) mà không mở khóa phải ném PermissionError."""
    lock = HoldoutLock(holdout_start="2025-01-01", is_unlocked=False)

    # Ngày trong vùng In-Sample -> Hợp lệ
    assert lock.verify_date("2024-12-31") is True

    # Ngày vi phạm vùng Holdout -> Bị chặn
    with pytest.raises(PermissionError) as exc_info:
        lock.verify_date("2025-01-02")
    assert "[HOLDOUT VIOLATION]" in str(exc_info.value)

    # Khi mở khóa tường minh -> Cho phép
    unlocked_lock = HoldoutLock(holdout_start="2025-01-01", is_unlocked=True)
    assert unlocked_lock.verify_date("2025-01-02") is True


def test_filter_safe_dates():
    """Bộ lọc chỉ giữ lại các ngày trước mốc Holdout."""
    lock = HoldoutLock(holdout_start="2025-01-01")
    dates = ["2024-11-01", "2024-12-31", "2025-01-02", "2025-06-15"]

    safe = lock.filter_safe_dates(dates)
    assert len(safe) == 2
    assert all(d < pd.Timestamp("2025-01-01") for d in safe)
