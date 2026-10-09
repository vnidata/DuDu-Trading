"""Tiện ích dùng chung: SSL, logging, IO, mã hoá kết quả."""

from __future__ import annotations

import gzip
import json
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Cấu hình logging một lần cho toàn bộ tiến trình."""
    if logging.getLogger().handlers:
        logging.getLogger().setLevel(level)
        return
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stdout)


def inject_truststore() -> bool:
    """Dùng kho chứng thư của Windows cho TLS.

    Mạng nội bộ BSC chèn chứng thư gốc của Kaspersky Endpoint Security vào
    chuỗi TLS. Bundle `certifi` mặc định của Python không chứa chứng thư này
    nên mọi request HTTPS tới API dữ liệu đều báo CERTIFICATE_VERIFY_FAILED.
    `truststore` đọc trực tiếp Windows Root store, nhờ đó không cần tắt xác
    thực chứng thư.
    """
    if os.environ.get("DUDU_DISABLE_TRUSTSTORE") == "1":
        return False
    try:
        import truststore

        truststore.inject_into_ssl()
        return True
    except Exception:  # pragma: no cover - phụ thuộc môi trường
        return False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_gzip_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, compression="gzip")


def write_gzip_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, compression="gzip")


class _NumpyEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:  # noqa: D102
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            v = float(o)
            return None if (np.isnan(v) or np.isinf(v)) else v
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (pd.Timestamp, datetime, date)):
            return o.isoformat()
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        if isinstance(o, set):
            return sorted(o)
        return super().default(o)


def json_dumps(obj: Any, indent: int | None = None) -> str:
    return json.dumps(obj, cls=_NumpyEncoder, ensure_ascii=False, indent=indent)


def write_json(obj: Any, path: Path, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json_dumps(obj, indent=indent), encoding="utf-8")
    tmp.replace(path)


def write_json_gz(obj: Any, path: Path) -> None:
    """Ghi JSON nén gzip để giữ repo Git nhẹ."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json_dumps(obj).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=9) as fh:
        fh.write(raw)
    tmp.replace(path)


def read_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
        return json.load(fh)


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if np.isnan(v) or np.isinf(v):
        return default
    return v


def human_vnd(x: float) -> str:
    """Định dạng số tiền VND theo tỷ / triệu."""
    ax = abs(x)
    if ax >= 1e12:
        return f"{x / 1e12:,.2f} nghìn tỷ"
    if ax >= 1e9:
        return f"{x / 1e9:,.2f} tỷ"
    if ax >= 1e6:
        return f"{x / 1e6:,.1f} triệu"
    return f"{x:,.0f}"
