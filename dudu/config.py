"""Cấu hình lõi cho DuDu-Trading.

Toàn bộ tham số đặc thù thị trường Việt Nam được tập trung tại đây để mọi
thành phần (data, backtest, GA, walk-forward, report) dùng chung một nguồn
sự thật duy nhất.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Đường dẫn
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
RESULTS_DIR = ROOT / "results"
SITE_DATA_DIR = ROOT / "site" / "data"

for _d in (DATA_DIR, RAW_DIR, CACHE_DIR, RESULTS_DIR, SITE_DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Vi mô cấu trúc thị trường HOSE
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class MarketConfig:
    """Đặc thù vi cấu trúc thị trường cơ sở HOSE.

    price_limit      : biên độ dao động giá HOSE ±7% so với giá tham chiếu.
    commission       : phí môi giới mỗi chiều (0.15% - mức phổ biến của CTCK).
    sell_tax         : thuế TNCN khi bán 0.1% giá trị bán.
    slippage         : trượt giá giả định mỗi chiều (0.10%).
    lot_size         : lô chẵn tối thiểu trên HOSE là 100 cổ phiếu.
    settlement_lag   : số phiên tối thiểu trước khi cổ phiếu mua về được bán.
                       Chu kỳ T+2.5 nghĩa là cổ phiếu mua tại phiên t có thể
                       bán từ phiên t+2 (khớp lệnh phiên chiều). Vì backtest
                       chỉ khớp theo giá đóng cửa, dùng lag = 2 phiên.
    """

    price_limit: float = 0.07
    commission: float = 0.0015
    sell_tax: float = 0.001
    slippage: float = 0.001
    lot_size: int = 100
    settlement_lag: int = 2

    def tick_size(self, price: float) -> float:
        """Bước giá HOSE theo khung giá (VND)."""
        if price < 10_000:
            return 10.0
        if price < 50_000:
            return 50.0
        return 100.0

    def ceiling_price(self, prev_close: float) -> float:
        """Giá trần = giá tham chiếu × 1.07, làm tròn xuống theo bước giá."""
        raw = prev_close * (1.0 + self.price_limit)
        tick = self.tick_size(raw)
        return float(int(raw / tick) * tick)

    def floor_price(self, prev_close: float) -> float:
        """Giá sàn = giá tham chiếu × 0.93, làm tròn lên theo bước giá."""
        raw = prev_close * (1.0 - self.price_limit)
        tick = self.tick_size(raw)
        return float(-(-raw // tick) * tick)


# --------------------------------------------------------------------------
# Tham số chiến lược Donchian Breakout (Turtle System 2)
# --------------------------------------------------------------------------
@dataclass
class StrategyParams:
    """Tham số chiến lược. Giá trị mặc định = Donchian-55 (Turtle S2)."""

    entry_window: int = 55          # phá đỉnh 55 phiên -> mua
    exit_window: int = 20           # phá đáy 20 phiên -> thoát
    atr_period: int = 20            # N = ATR(20)
    risk_per_unit: float = 0.01     # rủi ro mục tiêu mỗi Unit (% equity)
    stop_atr: float = 2.0           # stop loss = 2N từ giá vào
    pyramid_atr: float = 0.5        # gia tăng 1 Unit mỗi 0.5N thuận lợi
    max_units: int = 4              # trần số Unit trên một mã
    sizing_mode: str = "risk"       # "risk": rủi ro đúng risk_per_unit tại stop
                                    # "volatility": công thức Turtle gốc (1%/N)
    max_unit_nav: float = 0.20      # trần tỷ trọng NAV cho 1 Unit
    max_symbol_nav: float = 0.60    # trần tổng tỷ trọng NAV cho 1 mã

    # Bộ lọc đặc thù Việt Nam
    avoid_ceiling_entry: bool = True   # không mua khi đóng cửa tại giá trần
    block_floor_exit: bool = True      # không bán được khi đóng cửa tại giá sàn
    use_market_filter: bool = True     # chỉ giao dịch khi VN-Index > SMA200
    market_sma: int = 200
    trade_long_only: bool = True       # cấm bán khống cổ phiếu cơ sở

    # Thanh khoản
    adv_min: float = 30e9              # ADV tối thiểu 30 tỷ VND/phiên
    adv_window: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "StrategyParams":
        valid = {f for f in StrategyParams().__dataclass_fields__}
        return StrategyParams(**{k: v for k, v in d.items() if k in valid})


# --------------------------------------------------------------------------
# Không gian tìm kiếm của Genetic Algorithm
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ParamSpace:
    """Không gian tham số GA (theo khuyến nghị quy trình Việt Nam)."""

    entry_window: tuple[int, int] = (40, 70)
    exit_window: tuple[int, int] = (15, 25)
    atr_period: tuple[int, int] = (14, 25)
    risk_per_unit: tuple[float, float] = (0.005, 0.015)
    stop_atr: tuple[float, float] = (1.5, 3.0)

    def bounds(self) -> dict[str, tuple[float, float]]:
        return {
            "entry_window": self.entry_window,
            "exit_window": self.exit_window,
            "atr_period": self.atr_period,
            "risk_per_unit": self.risk_per_unit,
            "stop_atr": self.stop_atr,
        }


@dataclass(frozen=True)
class GAConfig:
    """Cấu hình thuật toán di truyền."""

    population: int = 60
    generations: int = 40
    elite: int = 4
    tournament_size: int = 3
    crossover_rate: float = 0.85
    mutation_rate: float = 0.18
    mutation_scale: float = 0.15     # BLX-alpha / gaussian sigma theo biên độ
    blx_alpha: float = 0.35
    w_calmar: float = 0.7            # w1 trong Fitness = w1*Calmar - w2*MaxDD
    w_maxdd: float = 0.3             # w2
    calmar_clip: tuple[float, float] = (-3.0, 8.0)
    min_trades_per_year: float = 2.0   # phạt nếu quá ít lệnh (thiếu ý nghĩa thống kê)
    max_trades_per_year: float = 20.0  # phạt nếu quá nhiều lệnh (chi phí ăn mòn)
    penalty_weight: float = 0.5
    seed: int = 20240101
    n_jobs: int = 10


@dataclass(frozen=True)
class WalkForwardConfig:
    """Cấu hình walk-forward: fit 252 phiên -> test 63 phiên -> dịch cửa sổ."""

    train_sessions: int = 252
    test_sessions: int = 63
    step_sessions: int = 63
    min_train_sessions: int = 200
    oos_calmar_min: float = 0.5
    oos_max_trades_per_year: float = 20.0


@dataclass(frozen=True)
class PortfolioConfig:
    """Cấu hình mô phỏng danh mục chia sẻ vốn."""

    initial_capital: float = 1_000_000_000.0   # 1 tỷ VND
    max_positions: int = 5
    max_gross_exposure: float = 0.60           # tổng exposure ≤ 60% NAV
    max_new_positions_per_day: int = 2
    cash_buffer: float = 0.05                  # dự phòng 5% NAV tiền mặt


@dataclass(frozen=True)
class BacktestConfig:
    market: MarketConfig = field(default_factory=MarketConfig)
    strategy: StrategyParams = field(default_factory=StrategyParams)
    initial_capital: float = 1_000_000_000.0
    rf_annual: float = 0.0                     # lãi suất phi rủi ro dùng cho Sharpe
    trading_days: int = 252

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": asdict(self.market),
            "strategy": self.strategy.to_dict(),
            "initial_capital": self.initial_capital,
            "rf_annual": self.rf_annual,
            "trading_days": self.trading_days,
        }


# --------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------
DEFAULT_UNIVERSE_GROUP = "VN100"
BENCHMARK_SYMBOL = "VNINDEX"
DATA_START = "2016-01-01"
