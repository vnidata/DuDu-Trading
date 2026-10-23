"""Script kiểm thử toàn diện QA & Data Sync cho DuDu-Trading.

Chạy:
    python scripts/run_qa_and_sync.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent


def run_step(name: str, cmd: list[str]) -> tuple[bool, str]:
    t0 = time.time()
    try:
        res = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        elapsed = time.time() - t0
        ok = (res.returncode == 0)
        out = (res.stdout + "\n" + res.stderr).strip()
        status = "PASSED" if ok else "FAILED"
        print(f"[{status}] {name} ({elapsed:.1f}s)")
        if not ok:
            print(f"      Chi tiết lỗi: {out[:400]}")
        return ok, out
    except Exception as exc:
        print(f"[FAILED] {name}: {exc}")
        return False, str(exc)


def main() -> int:
    print("=" * 60)
    print("DUDU-TRADING: KIỂM ĐỊNH TOÀN DIỆN QA & ĐỒNG BỘ DỮ LIỆU")
    print("=" * 60)

    steps = [
        ("1. Pytest Test Suite (126 unit tests: Engine, Advisors, Evolution, Execution, Diagnosis, Pullback, Chandelier, Allocator)", [sys.executable, "-m", "pytest", "tests/", "-q"]),
        ("2. Kiểm tra tính toàn vẹn DOM (Smoke DOM JS)", ["node", "scripts/smoke_dom.js"]),
        ("3. Kiểm tra tệp Website & Cấu trúc Site (Check Site JS)", ["node", "scripts/check_site.js"]),
        ("4. Tạo Ảnh chụp Thị trường Live (Snapshot)", [sys.executable, "scripts/snapshot.py", "--offline", "--quiet"]),
    ]

    all_ok = True
    for name, cmd in steps:
        ok, _ = run_step(name, cmd)
        if not ok:
            all_ok = False

    print("-" * 60)
    if all_ok:
        print("TẤT CẢ CÁC BƯỚC KIỂM THỬ ĐẠT CHUẨN (100% GREEN)")
        print("Hệ thống sẵn sàng commit và triển khai lên GitHub Pages.")
        return 0
    else:
        print("CÓ BƯỚC KIỂM THỬ THẤT BẠI. Vui lòng kiểm tra lại log.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
