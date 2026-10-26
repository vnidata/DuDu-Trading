"""Bộ điều phối tự động cập nhật dữ liệu định kỳ (Local / Server Daemon).

Hỗ trợ duy trì dữ liệu liên tục và toàn diện cả trên máy cá nhân hoặc máy chủ riêng:
- Trong phiên giao dịch HOSE (09:00 - 15:00 T2-T6): Tự động nạp dữ liệu nến mới mỗi 5 phút (hoặc tùy chỉnh).
- Cuối phiên (sau 15:00): Chốt ảnh chụp phiên cuối ngày (`is_final = True`) và làm mới meta.
- Tự động đẩy (git push) lên GitHub Pages nếu bật cờ `--push`.
- Tự phục hồi sau sự cố mạng hoặc lỗi kết nối.

Cách dùng:
    python scripts/auto_updater.py                  # Chạy định kỳ 5 phút
    python scripts/auto_updater.py --interval 180   # Chạy định kỳ 3 phút
    python scripts/auto_updater.py --push           # Tự động commit & push lên GitHub
    python scripts/auto_updater.py --once           # Chạy thử 1 lần rồi thoát
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

# Đảm bảo UTF-8 trên Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dudu.snapshot import session_of, vn_now, SESSION_LABELS
from dudu.utils import setup_logging

log = logging.getLogger("auto_updater")


def run_snapshot(refresh: bool = False) -> bool:
    """Gọi lệnh snapshot.py cập nhật thị trường."""
    cmd = [sys.executable, str(ROOT_DIR / "scripts" / "snapshot.py"), "--max-age-minutes", "4.0"]
    if refresh:
        cmd.append("--refresh")
    try:
        res = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True, encoding="utf-8", check=True)
        log.info("Snapshot thành công.")
        for line in res.stdout.strip().splitlines()[-3:]:
            log.info("  | %s", line)
        return True
    except subprocess.CalledProcessError as exc:
        log.error("Snapshot thất bại (mã %d): %s", exc.returncode, exc.stderr)
        return False


def run_push(commit_msg: str | None = None) -> bool:
    """Tự động commit và push dữ liệu mới lên remote GitHub."""
    now_str = vn_now().strftime("%Y-%m-%d %H:%M")
    msg = commit_msg or f"chore(data): auto-update snapshot {now_str}"
    try:
        # Kiểm tra có thay đổi dữ liệu không
        subprocess.run(["git", "add", "site/data", "data/manifest.json"], cwd=ROOT_DIR, check=True)
        diff_res = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT_DIR)
        if diff_res.returncode == 0:
            log.info("Không có dữ liệu mới để commit.")
            return True

        subprocess.run(["git", "commit", "-m", msg], cwd=ROOT_DIR, check=True)
        # Sử dụng biến môi trường tránh prompt GUI
        import os
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=ROOT_DIR, env=env, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=ROOT_DIR, env=env, check=True)
        log.info("Đã đẩy dữ liệu mới lên GitHub thành công.")
        return True
    except Exception as exc:
        log.warning("Không thể tự động git push: %s", exc)
        return False


def is_active_trading_window(now: datetime) -> bool:
    """Kiểm tra có đang trong ngày và khung giờ cần cập nhật không."""
    # Thứ Hai = 0, Thứ Sáu = 4, Thứ Bảy = 5, Chủ Nhật = 6
    if now.weekday() >= 5:
        return False
    t = now.time()
    # Theo dõi từ 08:55 sáng đến 15:15 chiều
    return dtime(8, 55) <= t <= dtime(15, 15)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bộ cập nhật dữ liệu tự động DuDu-Trading")
    parser.add_argument("--interval", type=int, default=300, help="Chu kỳ cập nhật tính bằng giây (mặc định 300s = 5 phút)")
    parser.add_argument("--push", action="store_true", help="Tự động commit & git push lên GitHub sau mỗi lần cập nhật")
    parser.add_argument("--force", action="store_true", help="Cập nhật bất kể có trong phiên giao dịch hay không")
    parser.add_argument("--refresh", action="store_true", help="Buộc tải lại toàn bộ nến")
    parser.add_argument("--once", action="store_true", help="Chạy một chu kỳ duy nhất rồi dừng")
    args = parser.parse_args()

    setup_logging()
    log.info("Khởi động Bộ cập nhật tự động DuDu-Trading (chu kỳ %d giây, push=%s)", args.interval, args.push)

    iteration = 0
    try:
        while True:
            iteration += 1
            now = vn_now()
            sess = session_of(now)
            sess_label = SESSION_LABELS.get(sess, sess)

            log.info("--- Chu kỳ #%d | %s | %s ---", iteration, now.strftime("%H:%M:%S %d/%m/%Y"), sess_label)

            should_update = args.force or is_active_trading_window(now)

            if should_update:
                success = run_snapshot(refresh=args.refresh)
                if success and args.push:
                    run_push()
            else:
                log.info("Thị trường hiện đang ngoài phiên (%s). Tạm nghỉ đến phiên kế tiếp.", sess_label)

            if args.once:
                log.info("Đã chạy xong chế độ --once. Kết thúc.")
                break

            # Tính thời gian ngủ thích hợp
            sleep_sec = args.interval
            if not should_update and not args.force:
                # Ngoài phiên giao dịch: ngủ dài hơn (15 phút) để tiết kiệm tài nguyên
                sleep_sec = 900

            log.info("Chờ %d giây cho chu kỳ tiếp theo...", sleep_sec)
            time.sleep(sleep_sec)

    except KeyboardInterrupt:
        log.info("Người dùng dừng tiến trình (Ctrl+C). Tạm biệt!")
        return 0
    except Exception as exc:
        log.exception("Lỗi không mong muốn trong vòng lặp cập nhật: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
