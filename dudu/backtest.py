"""Bộ máy backtest Donchian Breakout (Turtle System 2) cho thị trường Việt Nam.

Các ràng buộc vi cấu trúc được mô hình hoá tường minh:

1. **Biên độ ±7% và giá trần**: không mở vị thế khi giá đóng cửa đã ở giá trần
   (lệnh mua tại giá trần khó khớp và dễ bị đảo chiều cuối phiên).
2. **Giá sàn**: không thể khớp lệnh bán khi cổ phiếu đóng cửa tại giá sàn; tín
   hiệu thoát được đẩy sang phiên kế tiếp và khớp tại giá mở cửa.
3. **Chu kỳ T+2.5**: cổ phiếu mua tại phiên t chỉ được bán từ phiên t+2. Mỗi
   Unit mới vào bị "khoá" đúng `settlement_lag` phiên; lệnh thoát chỉ bán được
   phần cổ phiếu đã về tài khoản, phần còn lại treo sang phiên sau.
4. **Cấm bán khống cổ phiếu cơ sở**: toàn bộ engine là long-only.
5. **Thanh khoản phân tán**: bộ lọc ADV tối thiểu và trần tỷ trọng NAV.

Nguyên tắc tránh look-ahead: chỉ báo Donchian tính trên các phiên TRƯỚC ngày
tín hiệu; ADV dịch 1 phiên. Giá khớp là giá đóng cửa cộng trượt giá - một giả
định lạc quan nhẹ đã được bù bằng `MarketConfig.slippage` và nêu rõ trong
`METHODOLOGY.md`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .config import BacktestConfig, PortfolioConfig, StrategyParams
from .indicators import FeatureBank
from .metrics import drawdown_series, equity_metrics, trade_metrics
from .utils import safe_float


# --------------------------------------------------------------------------
# Cấu trúc kết quả
# --------------------------------------------------------------------------
@dataclass
class BacktestResult:
    symbol: str
    start: int = 0
    stop: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    dates: pd.DatetimeIndex | None = None
    equity: np.ndarray = field(default_factory=lambda: np.array([]))
    exposure: np.ndarray = field(default_factory=lambda: np.array([]))
    trades: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    trade_stats: dict[str, float] = field(default_factory=dict)
    open_position: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        s: dict[str, Any] = {"symbol": self.symbol}
        s.update(self.metrics)
        s.update(self.trade_stats)
        return s


@dataclass
class _Unit:
    shares: float
    entry_price: float      # giá khớp đã gồm trượt giá
    entry_t: int
    n_at_entry: float
    cost: float             # tiền mặt đã bỏ ra gồm phí mua
    fees: float


# --------------------------------------------------------------------------
# Tiện ích
# --------------------------------------------------------------------------
def _floor_lot(shares: float, lot: int) -> float:
    if shares <= 0 or lot <= 0:
        return 0.0
    return float(math.floor(shares / lot) * lot)


def _unit_shares(units: Sequence[_Unit]) -> float:
    return float(sum(u.shares for u in units))


def _unit_cost(units: Sequence[_Unit]) -> float:
    return float(sum(u.cost for u in units))


def _unit_fees(units: Sequence[_Unit]) -> float:
    return float(sum(u.fees for u in units))


def _unit_risk(units: Sequence[_Unit], stop_atr: float) -> float:
    return float(sum(stop_atr * u.n_at_entry * u.shares for u in units))


def _size_shares(
    price: float,
    n_value: float,
    equity_ref: float,
    cash: float,
    p: StrategyParams,
    cfg: BacktestConfig,
    room_value: float,
    budget: float | None = None,
) -> float:
    """Số cổ phiếu cho một Unit theo công thức Turtle, đã áp mọi trần rủi ro."""
    if not math.isfinite(n_value) or n_value <= 0 or price <= 0 or equity_ref <= 0:
        return 0.0
    risk_capital = p.risk_per_unit * equity_ref
    if p.sizing_mode == "volatility":
        raw = risk_capital / n_value
    else:
        raw = risk_capital / (p.stop_atr * n_value)
    raw = min(raw, p.max_unit_nav * equity_ref / price)
    if room_value > 0:
        raw = min(raw, room_value / price)
    avail = cash if budget is None else min(cash, budget)
    if avail <= 0:
        return 0.0
    raw = min(raw, avail / (price * (1.0 + cfg.market.commission)))
    return _floor_lot(raw, cfg.market.lot_size)


# --------------------------------------------------------------------------
# Bộ máy một mã
# --------------------------------------------------------------------------
def simulate_symbol(
    symbol: str,
    arrays: dict[str, np.ndarray],
    dates: pd.DatetimeIndex,
    cfg: BacktestConfig,
    close_open_at_end: bool = False,
    tradable: Sequence[bool] | np.ndarray | None = None,
) -> BacktestResult:
    """Mô phỏng một mã trên cửa sổ ngày đã cắt sẵn.

    `arrays` gồm các khoá: open, high, low, close, upper, lower, atr, ceiling,
    floor, adv, regime, age - mảng 1-D cùng độ dài.
    `tradable`: mảng bool cho biết phiên t có được phép giao dịch hay không.
    """
    p = cfg.strategy
    mkt = cfg.market
    # Chuyển sang list Python: vòng lặp trong GA chạy hàng trăm nghìn lần, số
    # học trên np.float64 chậm hơn float gốc khoảng một bậc độ lớn.
    op = arrays["open"].tolist()
    hi = arrays["high"].tolist()
    lo = arrays["low"].tolist()
    cl = arrays["close"].tolist()
    upper = arrays["upper"].tolist()
    lower = arrays["lower"].tolist()
    atr = arrays["atr"].tolist()
    ceiling = arrays["ceiling"].tolist()
    floor = arrays["floor"].tolist()
    adv = arrays["adv"].tolist()
    regime = arrays["regime"].tolist()
    age = arrays["age"].tolist()
    n = len(cl)
    fin = math.isfinite

    is_tradable = tradable if tradable is not None else arrays.get("tradable", None)

    cash = float(cfg.initial_capital)
    units: list[_Unit] = []
    trades: list[dict[str, Any]] = []
    equity_list = [0.0] * n
    exposure_list = [0.0] * n
    force_exit = False
    eq_at_first_entry = cfg.initial_capital

    def close_units(t: int, price: float, reason: str, ignore_settlement: bool = False) -> None:
        """Bán phần cổ phiếu đã về tài khoản; phần còn lại treo sang phiên sau."""
        nonlocal cash, units, force_exit
        sellable = (
            list(units)
            if ignore_settlement
            else [u for u in units if u.entry_t + mkt.settlement_lag <= t]
        )
        if not sellable or price <= 0:
            return
        shares = _unit_shares(sellable)
        gross = shares * price
        fee = gross * (mkt.commission + mkt.sell_tax)
        cash += gross - fee
        cost = _unit_cost(sellable)
        risk = _unit_risk(sellable, p.stop_atr)
        pnl = (gross - fee) - cost
        first_t = min(u.entry_t for u in sellable)
        trades.append(
            {
                "symbol": symbol,
                "entry_date": dates[first_t],
                "exit_date": dates[t],
                "entry_price": cost / shares if shares else 0.0,
                "exit_price": price,
                "shares": shares,
                "units": len(sellable),
                "pnl": pnl,
                "pnl_pct": pnl / cost if cost > 0 else 0.0,
                "r_multiple": pnl / risk if risk > 0 else 0.0,
                "fees": _unit_fees(sellable) + fee,
                "holding_days": float(t - first_t),
                "exit_reason": reason,
                "notional_at_entry": (cost / shares) * shares if shares else 0.0,
                "risk_vnd": risk,
                "equity_at_entry": eq_at_first_entry,
                "partial": bool(len(sellable) < len(units)),
            }
        )
        sold = set(id(u) for u in sellable)
        units = [u for u in units if id(u) not in sold]
        if units:
            force_exit = True

    def open_unit(t: int, price: float, equity_ref: float, n_value: float, budget: float | None = None) -> None:
        nonlocal cash, eq_at_first_entry
        if not units:
            eq_at_first_entry = equity_ref
        held_value = _unit_shares(units) * price
        room = p.max_symbol_nav * equity_ref - held_value
        shares = _size_shares(price, n_value, equity_ref, cash, p, cfg, room, budget)
        if shares <= 0:
            return
        fill = price * (1.0 + mkt.slippage)
        gross = shares * fill
        fee = gross * mkt.commission
        if gross + fee > cash:
            shares = _floor_lot((cash / (1.0 + mkt.commission)) / fill, mkt.lot_size)
            if shares <= 0:
                return
            gross = shares * fill
            fee = gross * mkt.commission
        cash -= gross + fee
        units.append(
            _Unit(shares=shares, entry_price=fill, entry_t=t, n_at_entry=float(n_value), cost=gross + fee, fees=fee)
        )

    for t in range(n):
        price = cl[t]
        can_trade = bool(is_tradable[t]) if is_tradable is not None else True

        # ---- A. Lệnh thoát treo từ phiên trước (kẹt sàn hoặc T+2.5) ----
        if can_trade and force_exit and units and op[t] > floor[t] and op[t] > 0:
            close_units(t, op[t] * (1.0 - mkt.slippage), "exit_deferred")
            if not units:
                force_exit = False

        # ---- B. Stop loss 2N (chỉ áp dụng cho Unit đã về tài khoản) ----
        if can_trade and units and not force_exit:
            sellable = [u for u in units if u.entry_t + mkt.settlement_lag <= t]
            if sellable:
                ref = sellable[-1]
                stop_price = ref.entry_price - p.stop_atr * ref.n_at_entry
                if fin(lo[t]) and lo[t] <= stop_price:
                    if op[t] <= floor[t]:
                        force_exit = True
                    else:
                        fill = max(min(op[t], stop_price), floor[t])
                        close_units(t, fill * (1.0 - mkt.slippage), "stop_loss")

        # ---- C. Tín hiệu thoát: đóng cửa dưới đáy Donchian ----
        if can_trade and units and not force_exit and fin(lower[t]) and price < lower[t]:
            if p.block_floor_exit and price <= floor[t]:
                force_exit = True
            else:
                close_units(t, price * (1.0 - mkt.slippage), "breakout_low")

        equity_ref = cash + _unit_shares(units) * price

        # ---- D. Kim tự tháp: gia tăng Unit mỗi 0.5N thuận lợi ----
        if can_trade and units and not force_exit and len(units) < p.max_units:
            last = units[-1]
            mature = last.entry_t + mkt.settlement_lag <= t
            add_level = last.entry_price + p.pyramid_atr * last.n_at_entry
            ceiling_ok = (not p.avoid_ceiling_entry) or price < ceiling[t]
            if mature and price >= add_level and ceiling_ok and price > 0:
                open_unit(t, price, equity_ref, atr[t])

        # ---- E. Vào lệnh mới khi phá đỉnh Donchian ----
        if can_trade and not units and not force_exit:
            u = upper[t]
            n_value = atr[t]
            liquid = fin(adv[t]) and adv[t] >= p.adv_min
            trend = (not p.use_market_filter) or bool(regime[t])
            fresh = age[t] >= (p.entry_window + 1)
            ceiling_ok = (not p.avoid_ceiling_entry) or (price < ceiling[t])
            if (
                fin(u)
                and fin(n_value)
                and n_value > 0
                and price > u
                and liquid
                and trend
                and fresh
                and ceiling_ok
            ):
                open_unit(t, price, equity_ref, n_value)

        # ---- F. Đánh giá vốn cuối phiên ----
        eq = cash + _unit_shares(units) * price
        equity_list[t] = eq
        exposure_list[t] = ((eq - cash) / eq) if eq > 0 else 0.0

    equity = np.array(equity_list, dtype=float)
    exposure = np.array(exposure_list, dtype=float)

    open_position = None
    if units:
        mv = _unit_shares(units) * cl[-1]
        cost = _unit_cost(units)
        open_position = {
            "shares": _unit_shares(units),
            "avg_entry": cost / _unit_shares(units) if _unit_shares(units) else 0.0,
            "units": len(units),
            "unrealized": mv - cost,
            "entry_date": dates[min(u.entry_t for u in units)],
        }
        if close_open_at_end:
            # Đóng toàn bộ ở giá thị trường cuối kỳ để số liệu lệnh đầy đủ,
            # bỏ qua ràng buộc T+2.5 vì đây là bút toán đánh giá, không phải
            # lệnh bán thực tế trên thị trường.
            close_units(n - 1, cl[-1] * (1.0 - mkt.slippage), "mark_to_market", ignore_settlement=True)
            equity[-1] = cash
            exposure[-1] = 0.0

    result = BacktestResult(
        symbol=symbol,
        start=0,
        stop=n,
        params=p.to_dict(),
        dates=dates,
        equity=equity,
        exposure=exposure,
        trades=trades,
        open_position=open_position,
    )
    result.metrics = equity_metrics(equity, cfg.trading_days, cfg.rf_annual)
    result.metrics["avg_exposure"] = safe_float(float(np.mean(exposure)) if n else 0.0)
    result.metrics["max_exposure"] = safe_float(float(np.max(exposure)) if n else 0.0)
    result.trade_stats = trade_metrics(trades, n, cfg.trading_days)
    return result


# --------------------------------------------------------------------------
# Cắt cửa sổ từ FeatureBank
# --------------------------------------------------------------------------
def window_arrays(
    bank: FeatureBank,
    j: int,
    t0: int,
    t1: int,
    params: StrategyParams,
) -> tuple[dict[str, np.ndarray], pd.DatetimeIndex]:
    """Cắt mảng 1-D cho một mã trong khoảng [t0, t1)."""
    panel = bank.panel
    sl = slice(t0, t1)
    arrays = {
        "open": panel.open[sl, j],
        "high": panel.high[sl, j],
        "low": panel.low[sl, j],
        "close": panel.close[sl, j],
        "upper": bank.upper_ref(params.entry_window)[sl, j],
        "lower": bank.lower_ref(params.exit_window)[sl, j],
        "atr": bank.atr_ref(params.atr_period)[sl, j],
        "ceiling": bank.ceiling[sl, j],
        "floor": bank.floor[sl, j],
        "adv": bank.adv[sl, j],
        "regime": bank.regime[sl, j],
        "age": bank.age[sl, j],
    }
    return arrays, panel.dates[t0:t1]


def run_symbol_window(
    bank: FeatureBank,
    symbol: str,
    t0: int,
    t1: int,
    cfg: BacktestConfig,
    close_open_at_end: bool = True,
    tradable: Sequence[bool] | np.ndarray | None = None,
) -> BacktestResult:
    j = bank.panel.symbol_index[symbol]
    arrays, dates = window_arrays(bank, j, t0, t1, cfg.strategy)
    if tradable is not None:
        arrays["tradable"] = np.asarray(tradable)
    res = simulate_symbol(symbol, arrays, dates, cfg, close_open_at_end=close_open_at_end, tradable=tradable)
    res.start, res.stop = t0, t1
    return res


def run_panel(
    bank: FeatureBank,
    cfg: BacktestConfig,
    t0: int = 0,
    t1: int | None = None,
    symbols: Sequence[str] | None = None,
    close_open_at_end: bool = True,
    tradable: np.ndarray | None = None,
) -> dict[str, BacktestResult]:
    t1 = bank.n_dates() if t1 is None else t1
    names = list(symbols) if symbols else list(bank.panel.symbols)
    panel = bank.panel
    out: dict[str, BacktestResult] = {}
    for s_idx, sym in enumerate(names):
        try:
            sym_tradable = None
            if tradable is not None:
                j = panel.symbol_index[sym]
                c = j if tradable.shape[1] == panel.shape[1] else s_idx
                if tradable.shape[0] == bank.n_dates():
                    sym_tradable = tradable[t0:t1, c]
                else:
                    sym_tradable = tradable[:, c]
            out[sym] = run_symbol_window(bank, sym, t0, t1, cfg, close_open_at_end, tradable=sym_tradable)
        except Exception:  # pragma: no cover - phòng dữ liệu lỗi
            continue
    return out


# --------------------------------------------------------------------------
# Mô phỏng danh mục chia sẻ vốn
# --------------------------------------------------------------------------
@dataclass
class _Pos:
    symbol: str
    shares: float
    units: list[dict[str, Any]]
    avg_entry: float
    cost: float
    fees: float
    risk: float
    t_entry: int
    entry_date: Any
    force_exit: bool = False


def simulate_portfolio(
    bank: FeatureBank,
    cfg: BacktestConfig,
    portfolio_cfg: PortfolioConfig,
    t0: int = 0,
    t1: int | None = None,
    symbols: Sequence[str] | None = None,
    close_open_at_end: bool = True,
    tradable: np.ndarray | None = None,
) -> dict[str, Any]:
    """Danh mục long-only chia sẻ một tài khoản tiền mặt, không dùng margin.

    Parameters
    ----------
    tradable : np.ndarray | None, optional
        Ma trận boolean (n_dates, n_symbols) hoặc (t1-t0, n_symbols) xác định
        mã có được phép giao dịch tại phiên t hay không. Nếu None, toàn bộ
        các phiên và mã đều được coi là tradable.
    """
    p = cfg.strategy
    mkt = cfg.market
    panel = bank.panel
    t1 = bank.n_dates() if t1 is None else t1
    names = list(symbols) if symbols else list(panel.symbols)
    cols = {s: panel.symbol_index[s] for s in names}

    def _is_tradable(t: int, j: int, sym: str) -> bool:
        if tradable is None:
            return True
        r = t if tradable.shape[0] == bank.n_dates() else (t - t0)
        c = j if tradable.shape[1] == panel.shape[1] else names.index(sym)
        return bool(tradable[r, c])

    upper = bank.upper_ref(p.entry_window)
    lower = bank.lower_ref(p.exit_window)
    atr = bank.atr_ref(p.atr_period)

    cash = float(cfg.initial_capital)
    positions: dict[str, _Pos] = {}
    trades: list[dict[str, Any]] = []
    equity = np.zeros(t1 - t0, dtype=float)
    exposure = np.zeros(t1 - t0, dtype=float)

    def gross_value(t: int) -> float:
        return float(sum(pos.shares * panel.close[t, cols[sym]] for sym, pos in positions.items()))

    def close_units(sym: str, t: int, price: float, reason: str, ignore_settlement: bool = False) -> None:
        nonlocal cash
        pos = positions[sym]
        sellable = (
            list(pos.units)
            if ignore_settlement
            else [u for u in pos.units if u["t"] + mkt.settlement_lag <= t]
        )
        if not sellable or price <= 0:
            pos.force_exit = True
            return
        shares = float(sum(u["shares"] for u in sellable))
        gross = shares * price
        fee = gross * (mkt.commission + mkt.sell_tax)
        cash += gross - fee
        cost = float(sum(u["cost"] for u in sellable))
        risk = float(sum(p.stop_atr * u["n"] * u["shares"] for u in sellable))
        pnl = (gross - fee) - cost
        first_t = min(u["t"] for u in sellable)
        trades.append(
            {
                "symbol": sym,
                "entry_date": panel.dates[first_t],
                "exit_date": panel.dates[t],
                "entry_price": cost / shares if shares else 0.0,
                "exit_price": price,
                "shares": shares,
                "units": len(sellable),
                "pnl": pnl,
                "pnl_pct": pnl / cost if cost > 0 else 0.0,
                "r_multiple": pnl / risk if risk > 0 else 0.0,
                "fees": float(sum(u["fees"] for u in sellable)) + fee,
                "holding_days": float(t - first_t),
                "exit_reason": reason,
                "notional_at_entry": cost,
                "risk_vnd": risk,
                "partial": bool(len(sellable) < len(pos.units)),
            }
        )
        sold = {id(u) for u in sellable}
        pos.units = [u for u in pos.units if id(u) not in sold]
        pos.shares -= shares
        pos.cost -= cost
        pos.risk -= risk
        if pos.shares <= 1e-9:
            positions.pop(sym, None)
        else:
            pos.force_exit = True

    def add_unit(sym: str, t: int, price: float, equity_ref: float) -> bool:
        nonlocal cash
        pos = positions[sym]
        if len(pos.units) >= p.max_units or pos.force_exit:
            return False
        last = pos.units[-1]
        if last["t"] + mkt.settlement_lag > t:
            return False
        n_value = last["n"]
        sym_value = pos.shares * price
        room_sym = p.max_symbol_nav * equity_ref - sym_value
        room_gross = portfolio_cfg.max_gross_exposure * equity_ref - gross_value(t)
        budget = max(cash - portfolio_cfg.cash_buffer * equity_ref, 0.0)
        shares = _size_shares(
            price, n_value, equity_ref, cash, p, cfg, min(room_sym, room_gross), budget
        )
        if shares <= 0:
            return False
        fill = price * (1.0 + mkt.slippage)
        gross = shares * fill
        fee = gross * mkt.commission
        cash -= gross + fee
        pos.units.append(
            {"shares": shares, "price": fill, "n": float(n_value), "t": t, "cost": gross + fee, "fees": fee}
        )
        pos.shares += shares
        pos.cost += gross + fee
        pos.fees += fee
        pos.risk += p.stop_atr * n_value * shares
        pos.avg_entry = pos.cost / pos.shares
        return True

    def open_position(sym: str, t: int, price: float, equity_ref: float) -> bool:
        nonlocal cash
        n_value = atr[t, cols[sym]]
        room_gross = portfolio_cfg.max_gross_exposure * equity_ref - gross_value(t)
        budget = max(cash - portfolio_cfg.cash_buffer * equity_ref, 0.0)
        shares = _size_shares(price, n_value, equity_ref, cash, p, cfg, room_gross, budget)
        if shares <= 0:
            return False
        fill = price * (1.0 + mkt.slippage)
        gross = shares * fill
        fee = gross * mkt.commission
        cash -= gross + fee
        positions[sym] = _Pos(
            symbol=sym,
            shares=shares,
            units=[{"shares": shares, "price": fill, "n": float(n_value), "t": t, "cost": gross + fee, "fees": fee}],
            avg_entry=fill,
            cost=gross + fee,
            fees=fee,
            risk=p.stop_atr * n_value * shares,
            t_entry=t,
            entry_date=panel.dates[t],
        )
        return True

    for t in range(t0, t1):
        # ---- A. Thoát lệnh ----
        for sym in list(positions):
            j = cols[sym]
            pos = positions[sym]
            if not _is_tradable(t, j, sym):
                continue
            price_c = panel.close[t, j]
            if pos.force_exit and panel.open[t, j] > bank.floor[t, j] > 0:
                close_units(sym, t, panel.open[t, j] * (1.0 - mkt.slippage), "exit_deferred")
                if sym not in positions:
                    continue
                pos = positions[sym]
            sellable = [u for u in pos.units if u["t"] + mkt.settlement_lag <= t]
            if sellable and not pos.force_exit:
                ref = sellable[-1]
                stop_price = ref["price"] - p.stop_atr * ref["n"]
                if panel.low[t, j] <= stop_price:
                    if panel.open[t, j] <= bank.floor[t, j]:
                        pos.force_exit = True
                    else:
                        fill = max(min(panel.open[t, j], stop_price), bank.floor[t, j])
                        close_units(sym, t, fill * (1.0 - mkt.slippage), "stop_loss")
                        if sym not in positions:
                            continue
                        pos = positions[sym]
            if sym in positions and not pos.force_exit and price_c < lower[t, j]:
                if p.block_floor_exit and price_c <= bank.floor[t, j]:
                    pos.force_exit = True
                else:
                    close_units(sym, t, price_c * (1.0 - mkt.slippage), "breakout_low")

        # ---- B. Gia tăng Unit ----
        for sym in list(positions):
            pos = positions[sym]
            if pos.force_exit or len(pos.units) >= p.max_units:
                continue
            j = cols[sym]
            if not _is_tradable(t, j, sym):
                continue
            price_c = panel.close[t, j]
            last = pos.units[-1]
            if price_c < last["price"] + p.pyramid_atr * last["n"]:
                continue
            if p.avoid_ceiling_entry and price_c >= bank.ceiling[t, j]:
                continue
            add_unit(sym, t, price_c, cash + gross_value(t))

        # ---- C. Vào lệnh mới ----
        if len(positions) < portfolio_cfg.max_positions:
            candidates: list[tuple[float, str]] = []
            for sym, j in cols.items():
                if sym in positions:
                    continue
                if not _is_tradable(t, j, sym):
                    continue
                u = upper[t, j]
                price_c = panel.close[t, j]
                if not np.isfinite(u) or price_c <= u:
                    continue
                n_value = atr[t, j]
                if not np.isfinite(n_value) or n_value <= 0:
                    continue
                if not (np.isfinite(bank.adv[t, j]) and bank.adv[t, j] >= p.adv_min):
                    continue
                if p.use_market_filter and not bank.regime[t, j]:
                    continue
                if bank.age[t, j] < p.entry_window + 1:
                    continue
                if p.avoid_ceiling_entry and price_c >= bank.ceiling[t, j]:
                    continue
                candidates.append((float(price_c / u - 1.0), sym))
            candidates.sort(reverse=True)
            opened = 0
            for _, sym in candidates:
                if opened >= portfolio_cfg.max_new_positions_per_day:
                    break
                if len(positions) >= portfolio_cfg.max_positions:
                    break
                eq_ref = cash + gross_value(t)
                if eq_ref <= 0 or gross_value(t) / eq_ref >= portfolio_cfg.max_gross_exposure:
                    break
                if open_position(sym, t, panel.close[t, cols[sym]], eq_ref):
                    opened += 1

        # ---- D. Đánh giá vốn ----
        mtm = gross_value(t)
        eq = cash + mtm
        equity[t - t0] = eq
        exposure[t - t0] = mtm / eq if eq > 0 else 0.0

    if close_open_at_end and positions:
        for sym in list(positions):
            close_units(
                sym,
                t1 - 1,
                panel.close[t1 - 1, cols[sym]] * (1.0 - mkt.slippage),
                "mark_to_market",
                ignore_settlement=True,
            )
        equity[-1] = cash

    dates = panel.dates[t0:t1]
    metrics = equity_metrics(equity, cfg.trading_days, cfg.rf_annual)
    metrics["avg_exposure"] = safe_float(float(np.mean(exposure)) if exposure.size else 0.0)
    metrics["max_exposure"] = safe_float(float(np.max(exposure)) if exposure.size else 0.0)
    stats = trade_metrics(trades, t1 - t0, cfg.trading_days)
    return {
        "dates": dates,
        "equity": equity,
        "exposure": exposure,
        "trades": trades,
        "metrics": metrics,
        "trade_stats": stats,
        "drawdown": drawdown_series(equity),
    }
