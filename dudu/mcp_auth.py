"""Quản lý xác thực OAuth 2.1 (PKCE & RFC 7591) cho các máy chủ MCP chứng khoán Việt Nam.

Hỗ trợ SSI, DNSE và VCBS:
- Dynamic Client Registration (RFC 7591)
- PKCE Authorization Code Flow (RFC 7636)
- Tự động làm mới access token qua refresh_token
- Lưu trữ an toàn trong `data/mcp_tokens.json` hoặc đọc từ biến môi trường / .env.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .utils import inject_truststore

log = logging.getLogger(__name__)

TOKEN_FILE = DATA_DIR / "mcp_tokens.json"

PROVIDER_METADATA: dict[str, dict[str, str]] = {
    "ssi": {
        "name": "SSI Securities",
        "mcp_url": "https://mcp.ssi.com.vn/mcp",
        "auth_url": "https://mcp.ssi.com.vn/oauth/authorize",
        "token_url": "https://mcp.ssi.com.vn/oauth/token",
        "register_url": "https://mcp.ssi.com.vn/oauth/register",
        "scope": "market-data:read",
    },
    "dnse": {
        "name": "DNSE Entrade X",
        "mcp_url": "https://mcp.dnse.com.vn/mcp",
        "auth_url": "https://mcp.dnse.com.vn/oauth2/authorize",
        "token_url": "https://mcp.dnse.com.vn/oauth2/token",
        "register_url": "https://mcp.dnse.com.vn/oauth2/register",
        "scope": "openid",
    },
    "vcbs": {
        "name": "VCBS AI",
        "mcp_url": "https://ai.vcbs.com.vn/api/mcp",
        "auth_url": "https://ai.vcbs.com.vn/api/oauth/authorize",
        "token_url": "https://ai.vcbs.com.vn/api/oauth/token",
        "register_url": "https://ai.vcbs.com.vn/api/oauth/register",
        "scope": "mcp",
    },
}


def _generate_pkce_pair() -> tuple[str, str]:
    """Sinh cặp mã verifier và challenge S256 chuẩn RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def load_all_tokens() -> dict[str, Any]:
    """Đọc toàn bộ token đã lưu từ tệp JSON."""
    if not TOKEN_FILE.exists():
        return {}
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Không thể đọc tệp token %s: %s", TOKEN_FILE, exc)
        return {}


def save_tokens(data: dict[str, Any]) -> None:
    """Ghi đè token vào tệp JSON."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def register_client(provider: str, redirect_uri: str) -> str:
    """Đăng ký Dynamic Client Registration (RFC 7591) và trả về client_id."""
    inject_truststore()
    meta = PROVIDER_METADATA.get(provider)
    if not meta:
        raise ValueError(f"Không hỗ trợ nhà cung cấp {provider}")

    reg_url = meta["register_url"]
    body = {
        "client_name": "DuDu-Trading MCP Client",
        "redirect_uris": [redirect_uri],
        "response_types": ["code"],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
    }
    req = urllib.request.Request(
        reg_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "DuDu-Trading/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        client_id = res.get("client_id")
        if not client_id:
            raise RuntimeError(f"Đăng ký client {provider} thất bại: {res}")
        return str(client_id)


def exchange_code_for_token(
    provider: str,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Đổi authorization_code lấy access_token bằng PKCE verifier."""
    inject_truststore()
    meta = PROVIDER_METADATA[provider]
    token_url = meta["token_url"]

    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        token_url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "DuDu-Trading/1.0",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res


def refresh_access_token(provider: str, refresh_token: str, client_id: str) -> dict[str, Any]:
    """Làm mới access_token bằng refresh_token."""
    inject_truststore()
    meta = PROVIDER_METADATA[provider]
    token_url = meta["token_url"]

    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        token_url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "DuDu-Trading/1.0",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_token(provider: str) -> str | None:
    """Lấy access_token hợp lệ cho một provider.

    Kiểm tra theo thứ tự:
    1. Biến môi trường: `SSI_MCP_TOKEN`, `DNSE_MCP_TOKEN`, `VCBS_MCP_TOKEN`
    2. Tệp `data/mcp_tokens.json` (tự động làm mới nếu hết hạn và có refresh_token)
    3. Thư mục cache `mcp-remote`
    """
    env_var = f"{provider.upper()}_MCP_TOKEN"
    if os.getenv(env_var):
        return os.getenv(env_var)

    all_tokens = load_all_tokens()
    entry = all_tokens.get(provider)
    if not entry:
        # Thử tìm trong thư mục mcp-remote
        remote_tok = _find_mcp_remote_token(provider)
        if remote_tok:
            return remote_tok
        return None

    access_token = entry.get("access_token")
    expires_at = entry.get("expires_at", 0)
    refresh_tok = entry.get("refresh_token")
    client_id = entry.get("client_id")

    # Kiểm tra xem token còn hạn không (trừ hao 60s)
    now = time.time()
    if access_token and (expires_at == 0 or expires_at - now > 60):
        return access_token

    # Thử refresh nếu có
    if refresh_tok and client_id:
        try:
            log.info("Làm mới access token cho %s...", provider)
            new_data = refresh_access_token(provider, refresh_tok, client_id)
            new_access = new_data.get("access_token")
            if new_access:
                expires_in = new_data.get("expires_in", 3600)
                entry["access_token"] = new_access
                entry["expires_at"] = now + expires_in
                if "refresh_token" in new_data:
                    entry["refresh_token"] = new_data["refresh_token"]
                all_tokens[provider] = entry
                save_tokens(all_tokens)
                return new_access
        except Exception as exc:
            log.warning("Không thể làm mới token cho %s: %s", provider, exc)

    return access_token


def _find_mcp_remote_token(provider: str) -> str | None:
    """Tìm token do mcp-remote lưu trong máy."""
    meta = PROVIDER_METADATA.get(provider)
    if not meta:
        return None
    url = meta["mcp_url"]
    home = Path.home()
    possible_dirs = [
        home / ".mcp-remote",
        home / "AppData" / "Roaming" / "mcp-remote",
        home / "AppData" / "Local" / "mcp-remote",
    ]
    for pdir in possible_dirs:
        if pdir.exists():
            for f in pdir.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                        if url in str(data):
                            if "access_token" in data:
                                return data["access_token"]
                            if "token" in data:
                                return data["token"]
                except Exception:
                    pass
    return None


def interactive_login(provider: str, port: int = 8080) -> dict[str, Any]:
    """Khởi động quy trình đăng nhập OAuth qua trình duyệt cục bộ."""
    inject_truststore()
    provider = provider.lower()
    if provider not in PROVIDER_METADATA:
        raise ValueError(f"Provider {provider} không hợp lệ. Chọn: {list(PROVIDER_METADATA.keys())}")

    meta = PROVIDER_METADATA[provider]
    redirect_uri = f"http://localhost:{port}/callback"

    # Bước 1: Đăng ký client dynamically
    log.info("Đang đăng ký Client với %s...", meta["name"])
    client_id = register_client(provider, redirect_uri)
    log.info("Đã đăng ký Client ID: %s", client_id)

    # Bước 2: Tạo PKCE
    code_verifier, code_challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": meta["scope"],
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{meta['auth_url']}?{urllib.parse.urlencode(auth_params)}"

    # Bước 3: Khởi tạo HTTP server đón callback
    received_code: list[str] = []
    received_error: list[str] = []

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)

            if "code" in query:
                received_code.append(query["code"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = (
                    "<html><body style='font-family: sans-serif; text-align: center; padding: 50px;'>"
                    "<h2 style='color: #10b981;'>✓ Đăng nhập thành công!</h2>"
                    "<p>Bạn có thể đóng cửa sổ trình duyệt này và quay lại màn hình làm việc.</p>"
                    "</body></html>"
                )
                self.wfile.write(html.encode("utf-8"))
            elif "error" in query:
                err = query.get("error_description", query["error"])[0]
                received_error.append(err)
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = f"<html><body><h2 style='color: red;'>Lỗi xác thực: {err}</h2></body></html>"
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return  # Tắt log HTTP server console

    server = HTTPServer(("localhost", port), CallbackHandler)
    server.timeout = 180.0  # Chờ người dùng đăng nhập tối đa 3 phút

    print(f"\n========================================================")
    print(f"XÁC THỰC MCP CHO {meta['name'].upper()}")
    print(f"Trình duyệt sẽ tự động mở liên kết đăng nhập:")
    print(f"{auth_url}")
    print(f"========================================================\n")

    webbrowser.open(auth_url)

    # Đón request callback
    while not received_code and not received_error:
        server.handle_request()

    server.server_close()

    if received_error:
        raise RuntimeError(f"Xác thực thất bại: {received_error[0]}")
    if not received_code:
        raise TimeoutError("Quá thời gian chờ đăng nhập (3 phút).")

    auth_code = received_code[0]
    log.info("Nhận được mã authorization_code, đang đổi access_token...")

    token_res = exchange_code_for_token(
        provider=provider,
        client_id=client_id,
        code=auth_code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )

    now = time.time()
    expires_in = token_res.get("expires_in", 86400)
    token_entry = {
        "provider": provider,
        "client_id": client_id,
        "access_token": token_res.get("access_token"),
        "refresh_token": token_res.get("refresh_token"),
        "token_type": token_res.get("token_type", "Bearer"),
        "scope": token_res.get("scope", meta["scope"]),
        "expires_in": expires_in,
        "expires_at": now + expires_in,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    all_tokens = load_all_tokens()
    all_tokens[provider] = token_entry
    save_tokens(all_tokens)

    log.info("Đã lưu token thành công vào %s", TOKEN_FILE)
    return token_entry
