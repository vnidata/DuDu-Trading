"""Kiểm tra tính toàn vẹn của website và chạy xem thử cục bộ.

Website GitHub Pages được triển khai thẳng từ thư mục `site/` qua GitHub
Actions, nên script này không sao chép gì mặc định. Hai chế độ hữu ích:

    python scripts/build_site.py --check          # kiểm tra dữ liệu + tài nguyên
    python scripts/build_site.py --serve          # mở server xem thử ở cổng 8787
    python scripts/build_site.py --out docs       # sao chép sang docs/ để publish kiểu cũ
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dudu.config import ROOT
from dudu.utils import setup_logging

SITE = ROOT / "site"
REQUIRED_DATA = [
    "meta.json",
    "symbols.json",
    "curves.json",
    "portfolio.json",
    "ga.json",
    "walkforward.json",
    "ablation.json",
    "heatmap.json",
    "liquidity.json",
]
REQUIRED_ASSETS = ["index.html", "assets/app.js", "assets/styles.css"]


def check() -> int:
    ok = True
    for rel in REQUIRED_ASSETS:
        p = SITE / rel
        status = "OK " if p.exists() else "THIẾU"
        if not p.exists():
            ok = False
        print(f"  [{status}] {rel}")
    total = 0
    for name in REQUIRED_DATA:
        p = SITE / "data" / name
        if not p.exists():
            print(f"  [THIẾU] data/{name}")
            ok = False
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  [LỖI ] data/{name}: {exc}")
            ok = False
            continue
        size = p.stat().st_size
        total += size
        kind = type(payload).__name__
        n = len(payload) if hasattr(payload, "__len__") else 0
        print(f"  [OK  ] data/{name:22s} {size/1024:7.1f} KB  {kind}({n})")
    print(f"  Tổng dữ liệu: {total/1024:.0f} KB")
    meta_path = SITE / "data" / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print(f"  Sinh lúc: {meta.get('generated_at')} · {meta['data']['n_symbols']} mã · "
              f"{meta['data']['date_start']} → {meta['data']['date_end']}")
    if total > 25 * 1024 * 1024:
        print("  [CẢNH BÁO] Dữ liệu vượt 25 MB, nên làm mảnh thêm trước khi publish.")
    return 0 if ok else 1


def serve(port: int) -> int:
    handler = lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(SITE), **k)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Xem thử tại http://127.0.0.1:{port}/  (Ctrl+C để dừng)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    return 0


def copy_to(out: Path) -> int:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE, out)
    print(f"Đã sao chép site/ -> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Kiểm tra và xem thử website DuDu-Trading")
    ap.add_argument("--check", action="store_true", help="Kiểm tra dữ liệu và tài nguyên")
    ap.add_argument("--serve", action="store_true", help="Chạy server xem thử")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--out", default=None, help="Sao chép site sang thư mục này")
    args = ap.parse_args()
    setup_logging()

    if args.out:
        copy_to(Path(args.out).resolve())
    if args.serve:
        return serve(args.port)
    return check() if (args.check or not args.out) else 0


if __name__ == "__main__":
    raise SystemExit(main())
