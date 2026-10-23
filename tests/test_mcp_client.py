"""Kiểm thử đơn vị cho module MCP: xác thực PKCE, JSON-RPC client và chuẩn hoá nến giá."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from dudu.mcp_auth import (
    PROVIDER_METADATA,
    _generate_pkce_pair,
    get_token,
    load_all_tokens,
    save_tokens,
)
from dudu.mcp_client import (
    MCPAuthRequiredError,
    MCPError,
    MultiProviderMCPClient,
    StockMCPClient,
)


def test_pkce_generation():
    """Kiểm tra sinh mã PKCE verifier và challenge S256 chuẩn RFC 7636."""
    verifier, challenge = _generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) > 0
    assert "=" not in challenge  # Không có padding base64
    assert "+" not in challenge and "/" not in challenge  # URL-safe


def test_provider_metadata():
    """Kiểm tra danh mục cấu hình 3 nhà cung cấp MCP."""
    assert "ssi" in PROVIDER_METADATA
    assert "dnse" in PROVIDER_METADATA
    assert "vcbs" in PROVIDER_METADATA
    for prov, meta in PROVIDER_METADATA.items():
        assert meta["mcp_url"].startswith("https://")
        assert meta["auth_url"].startswith("https://")
        assert meta["token_url"].startswith("https://")


def test_mcp_client_unknown_provider():
    """Kiểm tra ném lỗi khi chỉ định provider không tồn tại."""
    with pytest.raises(ValueError, match="Không hỗ trợ provider"):
        StockMCPClient(provider="unknown_broker")


def test_parse_ohlcv_from_dict_wrapper():
    """Kiểm tra bóc tách nến giá khi MCP trả về định dạng {'data': [...]}."""
    client = StockMCPClient(provider="ssi")
    raw_payload = {
        "data": [
            {
                "time": "2024-01-02",
                "open": 50000.0,
                "high": 51500.0,
                "low": 49800.0,
                "close": 51000.0,
                "volume": 2500000.0,
            },
            {
                "time": "2024-01-03",
                "open": 51000.0,
                "high": 52000.0,
                "low": 50500.0,
                "close": 51800.0,
                "volume": 3100000.0,
            },
        ]
    }
    df = client._parse_to_ohlcv_dataframe(raw_payload, "FPT")
    assert len(df) == 2
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert df["close"].iloc[0] == 51000.0
    assert df["volume"].iloc[1] == 3100000.0


def test_parse_ohlcv_with_abbreviated_column_names():
    """Kiểm tra ánh xạ các tên cột viết tắt (t, o, h, l, c, v)."""
    client = StockMCPClient(provider="dnse")
    raw_list = [
        {"t": "2024-02-01", "o": 25.0, "h": 26.0, "l": 24.5, "c": 25.5, "v": 100000},
        {"t": "2024-02-02", "o": 25.5, "h": 26.5, "l": 25.2, "c": 26.0, "v": 150000},
    ]
    df = client._parse_to_ohlcv_dataframe(raw_list, "SSI")
    assert len(df) == 2
    # Giá < 1000 được tự động nhân 1000
    assert df["close"].iloc[0] == 25500.0
    assert df["open"].iloc[1] == 25500.0
    assert df["volume"].iloc[0] == 100000.0


def test_parse_ohlcv_from_json_string_content():
    """Kiểm tra parse khi MCP trả về JSON string dạng text block."""
    client = StockMCPClient(provider="vcbs")
    json_text = json.dumps([
        {"time": "2024-03-01", "open": 90000, "high": 92000, "low": 89000, "close": 91500, "volume": 500000}
    ])
    df = client._parse_to_ohlcv_dataframe(json_text, "VCB")
    assert len(df) == 1
    assert df["close"].iloc[0] == 91500.0


@patch("urllib.request.urlopen")
def test_jsonrpc_request_success(mock_urlopen):
    """Kiểm tra gửi và nhận phản hồi JSON-RPC 2.0 thành công."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = StockMCPClient(provider="ssi")
    res = client.initialize()
    assert res["protocolVersion"] == "2024-11-05"


@patch("urllib.request.urlopen")
def test_jsonrpc_request_server_error(mock_urlopen):
    """Kiểm tra xử lý lỗi khi JSON-RPC trả về trường error."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found"}
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = StockMCPClient(provider="ssi")
    with pytest.raises(MCPError, match="Method not found"):
        client.send_request("invalid_method")


@patch("dudu.mcp_client.StockMCPClient.fetch_stock_candles")
@patch("dudu.mcp_client.get_token")
def test_multiprovider_failover(mock_get_token, mock_fetch):
    """Kiểm tra cơ chế failover giữa các nhà cung cấp."""
    mock_get_token.side_effect = lambda prov: f"mock_token_{prov}"

    # Lần gọi đầu (SSI) ném exception, lần gọi sau (DNSE) thành công
    expected_df = pd.DataFrame({
        "time": [pd.Timestamp("2024-01-02")],
        "open": [10000.0],
        "high": [10500.0],
        "low": [9800.0],
        "close": [10200.0],
        "volume": [50000.0],
    })

    def side_effect_fetch(symbol, start, end):
        if mock_fetch.call_count == 1:
            raise RuntimeError("SSI server temporary error")
        return expected_df

    mock_fetch.side_effect = side_effect_fetch

    coordinator = MultiProviderMCPClient(providers=["ssi", "dnse", "vcbs"])
    df = coordinator.fetch_stock_candles("FPT", start="2024-01-01")

    assert len(df) == 1
    assert df["close"].iloc[0] == 10200.0
    assert mock_fetch.call_count == 2
