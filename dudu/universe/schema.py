"""Schema các bảng sự kiện niêm yết và Point-in-Time Universe."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import pandas as pd


class Exchange(str, Enum):
    HOSE = "HOSE"
    HNX = "HNX"
    UPCOM = "UPCOM"
    OTC = "OTC"
    DELISTED = "DELISTED"


class EndReason(str, Enum):
    ACTIVE = "ACTIVE"                      # Đang niêm yết
    TRANSFER = "TRANSFER"                  # Chuyển sàn (UPCoM -> HOSE, HNX -> HOSE...)
    MANDATORY_DELIST = "MANDATORY_DELIST"  # Hủy niêm yết bắt buộc (thua lỗ, vi phạm CBTT)
    VOLUNTARY_DELIST = "VOLUNTARY_DELIST"  # Hủy niêm yết tự nguyện
    MERGER = "MERGER"                      # Sáp nhập / hoán đổi cổ phiếu
    OTHER = "OTHER"


class StatusEventType(str, Enum):
    SUSPENSION = "SUSPENSION"              # Tạm ngừng / đình chỉ giao dịch
    WARNING = "WARNING"                    # Cảnh báo
    CONTROL = "CONTROL"                    # Kiểm soát
    RESTRICTION = "RESTRICTION"            # Hạn chế giao dịch (chỉ GD phiên chiều)


class DataQualityType(str, Enum):
    FLAT_DUMMY_BAR = "FLAT_DUMMY_BAR"      # Nến phẳng nhân tạo vendor tạo khi chuyển sàn (VTP 12/03/2024)
    PRICE_LIMIT_BREACH = "LIMIT_BREACH"    # Nến vượt trần/sàn biên độ
    JUMP_CANDLE = "JUMP_CANDLE"            # Nhảy giá bất thường
    NAN_INTERPOLATED = "NAN_INTERPOLATED"  # Giá NaN được nội suy


@dataclass
class Security:
    """Đại diện thực thể công ty/chứng khoán ổn định xuyên suốt thời gian."""
    security_id: str
    current_ticker: str
    ticker_history: list[tuple[str, pd.Timestamp]] = field(default_factory=list)
    name: str = ""
    isin: str = ""


@dataclass
class ListingEpisode:
    """Một giai đoạn niêm yết liên tục của chứng khoán trên một sàn cụ thể."""
    security_id: str
    ticker: str
    exchange: Exchange
    first_trade_date: pd.Timestamp
    last_trade_date: pd.Timestamp | None = None  # None nếu đang niêm yết
    end_reason: EndReason = EndReason.ACTIVE
    source_url: str = ""
    verified: bool = False


@dataclass
class StatusEvent:
    """Sự kiện trạng thái giao dịch (đình chỉ, kiểm soát, cảnh báo...)."""
    security_id: str
    ticker: str
    event_type: StatusEventType
    effective_date: pd.Timestamp
    end_date: pd.Timestamp | None = None
    notes: str = ""


@dataclass
class CorporateAction:
    """Hệ số điều chỉnh kỹ thuật và sự kiện cổ tức tách gộp."""
    security_id: str
    ticker: str
    event_date: pd.Timestamp
    factor_raw_to_adj: float = 1.0
    cash_dividend: float = 0.0
    stock_dividend_ratio: float = 0.0
    rights_ratio: float = 0.0


@dataclass
class DataQualityEvent:
    """Ghi nhận dị thường dữ liệu để kiểm toán và xử lý."""
    security_id: str
    ticker: str
    date: pd.Timestamp
    event_type: DataQualityType
    details: str = ""
    action_taken: str = ""
