#!/usr/bin/env python3
"""Công cụ dòng lệnh chẩn đoán, xác thực và lấy dữ liệu chứng khoán qua MCP (SSI, DNSE, VCBS).

Cách dùng:
    # 1. Kiểm tra kết nối tới cả 3 server:
    python scripts/mcp_market_data.py --ping

    # 2. Đăng nhập mở trình duyệt cấp quyền (OAuth 2.1 PKCE):
    python scripts/mcp_market_data.py --auth ssi
    python scripts/mcp_market_data.py --auth dnse
    python scripts/mcp_market_data.py --auth vcbs

    # 3. Xem tình trạng token đã lưu:
    python scripts/mcp_market_data.py --status

    # 4. Lưu token thủ công (nếu đã có token/bearer):
    python scripts/mcp_market_data.py --set-token ssi <TOKEN_VALUE>

    # 5. Liệt kê danh sách công cụ của từng server:
    python scripts/mcp_market_data.py --list-tools ssi

    # 6. Tải nến giá một mã cổ phiếu:
    python scripts/mcp_market_data.py --fetch FPT --from 2024-01-01 --provider ssi
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

# Đảm bảo in UTF-8 không lỗi trên Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dudu.mcp_auth import (
    PROVIDER_METADATA,
    get_token,
    interactive_login,
    load_all_tokens,
    set_token,
)
from dudu.mcp_client import MultiProviderMCPClient, StockMCPClient
from dudu.utils import inject_truststore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mcp_cli")


def cmd_ping() -> None:
    """Kiểm tra phản hồi mạng tới 3 máy chủ MCP."""
    inject_truststore()
    print("=" * 60, flush=True)
    print("KIỂM TRA KẾT NỐI TỚI CÁC MÁY CHỦ MCP CHỨNG KHOÁN VIỆT NAM", flush=True)
    print("=" * 60, flush=True)

    for provider, meta in PROVIDER_METADATA.items():
        url = meta["mcp_url"]
        print(f"\n[{provider.upper()}] {meta['name']} -> {url}", flush=True)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "DuDu-Trading/1.0", "Accept": "application/json, text/event-stream"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"  ✓ Phản hồi HTTP {resp.status}", flush=True)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                print(f"  ✓ Máy chủ trực tuyến (HTTP 401 Unauthorized - Đúng chuẩn MCP bảo mật OAuth)", flush=True)
            else:
                print(f"  ! Máy chủ phản hồi mã HTTP {exc.code}", flush=True)
        except Exception as exc:
            print(f"  ✗ Kết nối thất bại: {exc}", flush=True)


def cmd_status() -> None:
    """In trạng thái token xác thực hiện tại."""
    print("=" * 60, flush=True)
    print("TRẠNG THÁI TOKEN XÁC THỰC MCP", flush=True)
    print("=" * 60, flush=True)
    tokens = load_all_tokens()
    now = time.time()

    for provider, meta in PROVIDER_METADATA.items():
        entry = tokens.get(provider)
        token = get_token(provider)
        print(f"\n[{provider.upper()}] - {meta['name']}:", flush=True)
        if not entry and not token:
            print("  Trạng thái : Chưa có token.", flush=True)
            print(f"  Hướng dẫn  : Chạy 'python scripts/mcp_market_data.py --auth {provider}'", flush=True)
            continue

        if entry:
            expires_at = entry.get("expires_at", 0)
            diff = expires_at - now
            if diff > 0:
                hours = int(diff // 3600)
                mins = int((diff % 3600) // 60)
                print(f"  Trạng thái : ✓ Còn hiệu lực (còn {hours} giờ {mins} phút)", flush=True)
            else:
                print("  Trạng thái : ! Đã hết hạn (sẽ tự động refresh khi gọi)", flush=True)
            print(f"  Client ID  : {entry.get('client_id')}", flush=True)
            print(f"  Cập nhật lúc: {entry.get('updated_at', 'N/A')}", flush=True)
        elif token:
            print("  Trạng thái : ✓ Đọc từ biến môi trường hoặc cache mcp-remote", flush=True)


def cmd_auth(provider_arg: str, port: int) -> None:
    """Chạy quy trình xác thực OAuth PKCE."""
    targets = list(PROVIDER_METADATA.keys()) if provider_arg == "all" else [provider_arg.lower()]

    for prov in targets:
        if prov not in PROVIDER_METADATA:
            print(f"Lỗi: Không hỗ trợ provider '{prov}'. Hãy chọn một trong {list(PROVIDER_METADATA.keys())}", flush=True)
            continue

        print(f"\n>>> Bắt đầu xác thực cho {PROVIDER_METADATA[prov]['name']}...", flush=True)
        try:
            interactive_login(provider=prov, port=port)
            print(f"✓ Đã lưu token thành công cho {prov.upper()}!", flush=True)
        except Exception as exc:
            print(f"✗ Xác thực thất bại cho {prov.upper()}: {exc}", flush=True)


def cmd_set_token(provider: str, token_str: str) -> None:
    """Lưu token thủ công."""
    provider = provider.lower()
    if provider not in PROVIDER_METADATA:
        print(f"Lỗi: Chọn provider trong {list(PROVIDER_METADATA.keys())}", flush=True)
        return
    set_token(provider, token_str)
    print(f"✓ Đã lưu token thành công cho [{provider.upper()}].", flush=True)


def cmd_list_tools(provider: str) -> None:
    """Liệt kê công cụ của một máy chủ MCP."""
    provider = provider.lower()
    if provider not in PROVIDER_METADATA:
        print(f"Lỗi: Chọn provider trong {list(PROVIDER_METADATA.keys())}", flush=True)
        return

    print(f"\nĐang tải danh sách công cụ từ {PROVIDER_METADATA[provider]['name']} ({provider.upper()})...", flush=True)
    client = StockMCPClient(provider=provider)
    try:
        tools = client.list_tools()
        print(f"✓ Tìm thấy {len(tools)} công cụ hỗ trợ:\n", flush=True)
        for i, t in enumerate(tools, 1):
            name = t.get("name", "N/A")
            desc = t.get("description", "Không có mô tả")
            print(f"{i:2d}. {name}", flush=True)
            print(f"    Mô tả: {desc.strip()[:100]}...", flush=True)
    except Exception as exc:
        print(f"✗ Không thể lấy danh sách tool: {exc}", flush=True)


def cmd_fetch(symbol: str, start: str, end: str | None, provider: str, save: bool) -> None:
    """Tải và hiển thị nến giá."""
    symbol = symbol.upper()
    print(f"\nĐang tải nến giá cho {symbol} từ {start} đến {end or 'hiện tại'}...", flush=True)

    try:
        if provider == "auto":
            coordinator = MultiProviderMCPClient()
            df = coordinator.fetch_stock_candles(symbol, start=start, end=end)
        else:
            client = StockMCPClient(provider=provider)
            df = client.fetch_stock_candles(symbol, start=start, end=end)

        print(f"\n✓ Tải thành công {len(df)} phiên giao dịch:", flush=True)
        print(df.tail(10).to_string(index=False), flush=True)

        if save:
            from dudu.config import RAW_DIR
            from dudu.utils import write_gzip_csv

            cache_path = RAW_DIR / f"{symbol}_{start[:4]}.csv.gz"
            write_gzip_csv(df, cache_path)
            print(f"✓ Đã lưu cache vào {cache_path}", flush=True)

    except Exception as exc:
        print(f"✗ Tải nến giá thất bại: {exc}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="DuDu-Trading Vietnam Stock MCP CLI")
    parser.add_argument("--ping", action="store_true", help="Kiểm tra kết nối tới 3 server MCP")
    parser.add_argument("--status", action="store_true", help="Xem trạng thái token hiện tại")
    parser.add_argument("--auth", metavar="PROVIDER", help="Đăng nhập OAuth (ssi, dnse, vcbs, hoặc all)")
    parser.add_argument("--port", type=int, default=8080, help="Cổng callback OAuth (mặc định 8080)")
    parser.add_argument("--set-token", nargs=2, metavar=("PROVIDER", "TOKEN"), help="Lưu token thủ công")
    parser.add_argument("--list-tools", metavar="PROVIDER", help="Liệt kê công cụ của provider")
    parser.add_argument("--fetch", metavar="SYMBOL", help="Tải nến giá cổ phiếu (ví dụ: SSI, VCB, FPT)")
    parser.add_argument("--from", dest="start_date", default="2024-01-01", help="Ngày bắt đầu YYYY-MM-DD")
    parser.add_argument("--to", dest="end_date", default=None, help="Ngày kết thúc YYYY-MM-DD")
    parser.add_argument(
        "--provider",
        choices=["ssi", "dnse", "vcbs", "auto"],
        default="auto",
        help="Nguồn dữ liệu ưu tiên (mặc định auto)",
    )
    parser.add_argument("--save", action="store_true", help="Lưu dữ liệu tải về vào thư mục cache data/raw/")

    args = parser.parse_args()

    if args.ping:
        cmd_ping()
    elif args.status:
        cmd_status()
    elif args.auth:
        cmd_auth(args.auth, args.port)
    elif args.set_token:
        cmd_set_token(args.set_token[0], args.set_token[1])
    elif args.list_tools:
        cmd_list_tools(args.list_tools)
    elif args.fetch:
        cmd_fetch(args.fetch, args.start_date, args.end_date, args.provider, args.save)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
