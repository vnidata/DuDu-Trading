"""Client giao tiếp Model Context Protocol (MCP) JSON-RPC 2.0 cho chứng khoán Việt Nam.

Tương thích với các endpoint:
- SSI Securities: https://mcp.ssi.com.vn/mcp
- DNSE Entrade X: https://mcp.dnse.com.vn/mcp
- VCBS AI: https://ai.vcbs.com.vn/api/mcp
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Iterable, Sequence

import pandas as pd

from .mcp_auth import PROVIDER_METADATA, get_token
from .utils import inject_truststore

log = logging.getLogger(__name__)

OHLCV_COLUMNS = ["time", "open", "high", "low", "close", "volume"]


class MCPError(RuntimeError):
    """Lỗi phản hồi từ máy chủ MCP."""


class MCPAuthRequiredError(MCPError):
    """Máy chủ yêu cầu xác thực hoặc token hết hạn."""


class StockMCPClient:
    """Client giao tiếp với máy chủ MCP qua JSON-RPC 2.0 over HTTP."""

    def __init__(self, provider: str = "ssi", timeout: float = 30.0) -> None:
        provider = provider.lower()
        if provider not in PROVIDER_METADATA:
            raise ValueError(f"Không hỗ trợ provider '{provider}'. Chọn trong: {list(PROVIDER_METADATA.keys())}")
        self.provider = provider
        self.metadata = PROVIDER_METADATA[provider]
        self.url = self.metadata["mcp_url"]
        self.timeout = timeout
        self._id_counter = 0
        self._lock = threading.Lock()
        self._initialized = False

    def _next_id(self) -> int:
        with self._lock:
            self._id_counter += 1
            return self._id_counter

    def send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Gửi request JSON-RPC 2.0 tới MCP Server."""
        inject_truststore()
        token = get_token(self.provider)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream, */*",
            "User-Agent": "DuDu-Trading/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace")
                if not raw_body.strip():
                    return {}
                res = json.loads(raw_body)
                if "error" in res:
                    err = res["error"]
                    raise MCPError(f"[{self.provider}] Lỗi {err.get('code')}: {err.get('message')}")
                return res.get("result", {})
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise MCPAuthRequiredError(
                    f"[{self.provider}] Lỗi 401 Unauthorized: Cần đăng nhập để lấy token. "
                    f"Chạy: python scripts/mcp_market_data.py --auth {self.provider}"
                ) from exc
            try:
                err_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                err_text = str(exc)
            raise MCPError(f"[{self.provider}] HTTP {exc.code}: {err_text}") from exc
        except Exception as exc:
            raise MCPError(f"[{self.provider}] Kết nối thất bại: {exc}") from exc

    def initialize(self) -> dict[str, Any]:
        """Bắt tay khởi tạo phiên giao tiếp MCP."""
        res = self.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "DuDu-Trading", "version": "1.0.0"},
            },
        )
        self._initialized = True
        return res

    def list_tools(self) -> list[dict[str, Any]]:
        """Lấy danh sách các công cụ được máy chủ MCP cung cấp."""
        if not self._initialized:
            try:
                self.initialize()
            except Exception as e:
                log.debug("Initialize fallback: %s", e)
        res = self.send_request("tools/list", {})
        return res.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Thực thi một tool trên máy chủ MCP."""
        if not self._initialized:
            try:
                self.initialize()
            except Exception as e:
                log.debug("Initialize fallback: %s", e)

        res = self.send_request("tools/call", {"name": name, "arguments": arguments or {}})
        content = res.get("content", [])
        if not content:
            return res

        # MCP chuẩn trả về mảng các khối (thường là type="text")
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                texts.append(item["text"])
            elif isinstance(item, str):
                texts.append(item)

        combined = "\n".join(texts)
        try:
            return json.loads(combined)
        except Exception:
            return combined

    def fetch_stock_candles(
        self,
        symbol: str,
        start: str,
        end: str | None = None,
        resolution: str = "1D",
    ) -> pd.DataFrame:
        """Tải lịch sử nến giá OHLCV của cổ phiếu và chuẩn hoá về DataFrame chuẩn."""
        symbol = symbol.upper()
        tools = self.list_tools()
        tool_names = [t.get("name", "") for t in tools]

        # Tìm tool phù hợp theo provider
        raw_result = None

        if self.provider == "ssi":
            # SSI hỗ trợ các tool dạng marketdata_get_stock_history hoặc tương tự
            matched = [t for t in tool_names if "stock_history" in t or "history" in t or "price" in t]
            chosen_tool = matched[0] if matched else "marketdata_get_stock_history"
            args: dict[str, Any] = {"symbol": symbol, "from_date": start}
            if end:
                args["to_date"] = end
            if "resolution" in str(tools):
                args["resolution"] = resolution
            raw_result = self.call_tool(chosen_tool, args)

        elif self.provider == "dnse":
            matched = [t for t in tool_names if "history" in t or "ohlcv" in t or "candle" in t]
            chosen_tool = matched[0] if matched else "get_ohlcv"
            args = {"symbol": symbol, "start_date": start}
            if end:
                args["end_date"] = end
            raw_result = self.call_tool(chosen_tool, args)

        elif self.provider == "vcbs":
            matched = [t for t in tool_names if "history" in t or "price" in t or "quote" in t]
            chosen_tool = matched[0] if matched else "get_stock_price_history"
            args = {"symbol": symbol, "start_date": start}
            if end:
                args["end_date"] = end
            raw_result = self.call_tool(chosen_tool, args)

        return self._parse_to_ohlcv_dataframe(raw_result, symbol)

    def _parse_to_ohlcv_dataframe(self, raw_data: Any, symbol: str) -> pd.DataFrame:
        """Chuẩn hoá dữ liệu thô từ MCP thành DataFrame chuẩn của DuDu-Trading."""
        if raw_data is None:
            raise ValueError(f"Dữ liệu trả về rỗng cho {symbol}")

        # Trường hợp raw_data là dict chứa data/items/records
        records: list[dict[str, Any]] = []
        if isinstance(raw_data, list):
            records = raw_data
        elif isinstance(raw_data, dict):
            for key in ("data", "items", "records", "candles", "quotes", "history"):
                if key in raw_data and isinstance(raw_data[key], list):
                    records = raw_data[key]
                    break
            if not records and "time" in raw_data:
                # Định dạng nén dạng dict of lists: {"time": [...], "open": [...]}
                df = pd.DataFrame(raw_data)
                return self._normalize_columns(df, symbol)

        if not records:
            # Thử phân tích dạng text bảng nếu MCP trả về text
            if isinstance(raw_data, str):
                try:
                    loaded = json.loads(raw_data)
                    return self._parse_to_ohlcv_dataframe(loaded, symbol)
                except Exception:
                    pass
            raise ValueError(f"Không thể trích xuất danh sách nến giá từ kết quả MCP cho {symbol}: {type(raw_data)}")

        df = pd.DataFrame(records)
        return self._normalize_columns(df, symbol)

    def _normalize_columns(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Đổi tên cột và chuẩn hoá định dạng số."""
        out = df.copy()
        # Ánh xạ các biến thể tên cột về tên chuẩn
        col_map = {
            "date": "time",
            "tradingdate": "time",
            "datetime": "time",
            "t": "time",
            "o": "open",
            "openprice": "open",
            "h": "high",
            "highprice": "high",
            "l": "low",
            "lowprice": "low",
            "c": "close",
            "closeprice": "close",
            "v": "volume",
            "totalvolume": "volume",
            "vol": "volume",
        }
        # Đưa về chữ thường
        out = out.rename(columns={c: str(c).lower().strip() for c in out.columns})
        out = out.rename(columns=col_map)

        for col in OHLCV_COLUMNS:
            if col not in out.columns:
                raise ValueError(f"{symbol}: thiếu cột bắt buộc '{col}' (các cột hiện có: {list(out.columns)})")

        out = out[OHLCV_COLUMNS].copy()
        out["time"] = pd.to_datetime(out["time"]).dt.tz_localize(None).dt.normalize()
        for col in ("open", "high", "low", "close", "volume"):
            out[col] = pd.to_numeric(out[col], errors="coerce")

        out = (
            out.dropna(subset=["close"])
            .drop_duplicates(subset="time", keep="last")
            .sort_values("time")
            .reset_index(drop=True)
        )
        # Chuẩn hoá giá nếu giá theo đơn vị nghìn VND
        med = float(out["close"].median()) if len(out) > 0 else 0.0
        if 0 < med < 1000:
            for col in ("open", "high", "low", "close"):
                out[col] = out[col] * 1000.0

        out["volume"] = out["volume"].fillna(0.0)
        return out


class MultiProviderMCPClient:
    """Bộ điều phối MCP tự động thử và failover giữa các nhà cung cấp."""

    def __init__(self, providers: Sequence[str] = ("ssi", "dnse", "vcbs")) -> None:
        self.providers = list(providers)

    def fetch_stock_candles(
        self,
        symbol: str,
        start: str,
        end: str | None = None,
        preferred_provider: str | None = None,
    ) -> pd.DataFrame:
        """Thử tải nến giá lần lượt qua các provider sẵn sàng."""
        ordered = list(self.providers)
        if preferred_provider and preferred_provider in ordered:
            ordered.remove(preferred_provider)
            ordered.insert(0, preferred_provider)

        last_err: Exception | None = None
        for prov in ordered:
            tok = get_token(prov)
            if not tok:
                log.debug("Bỏ qua %s vì chưa có access token", prov)
                continue
            try:
                client = StockMCPClient(provider=prov)
                df = client.fetch_stock_candles(symbol, start, end)
                if len(df) > 0:
                    log.info("Tải thành công %s từ MCP [%s] (%d phiên)", symbol, prov.upper(), len(df))
                    return df
            except Exception as exc:
                log.warning("Thất bại khi lấy dữ liệu từ MCP [%s]: %s", prov, exc)
                last_err = exc

        raise RuntimeError(
            f"Không thể tải nến giá {symbol} qua các MCP server ({ordered}). "
            f"Lỗi cuối cùng: {last_err}. "
            "Hãy kiểm tra đăng nhập bằng: python scripts/mcp_market_data.py --auth"
        )
