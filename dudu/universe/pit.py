"""Bộ tính toán Point-in-Time Universe và ma trận tradable causality-checked."""
from __future__ import annotations

from typing import Sequence
import numpy as np
import pandas as pd

from .schema import Exchange, ListingEpisode, StatusEvent, StatusEventType


def compute_adtv_t_minus_1(
    raw_prices: np.ndarray,
    volumes: np.ndarray,
    t: int,
    window: int = 20,
) -> np.ndarray:
    """Tính ADTV từ 20 phiên kết thúc tại t-1 (tuyệt đối không dùng phiên t).

    Parameters
    ----------
    raw_prices : np.ndarray
        Mảng giá thô (n_dates, n_symbols).
    volumes : np.ndarray
        Mảng khối lượng giao dịch (n_dates, n_symbols).
    t : int
        Chỉ số phiên hiện tại đang xét tính hợp lệ.
    window : int
        Số phiên quá khứ dùng tính trung bình (mặc định 20).

    Returns
    -------
    np.ndarray
        Mảng 1D (n_symbols) chứa ADTV (VND) tính từ t-window đến t-1.
    """
    if t < window:
        # Chưa đủ window phiên trong quá khứ
        sl_p = raw_prices[:t]
        sl_v = volumes[:t]
    else:
        sl_p = raw_prices[t - window : t]
        sl_v = volumes[t - window : t]

    if len(sl_p) == 0:
        return np.zeros(raw_prices.shape[1], dtype=float)

    turnover = sl_p * sl_v
    # Bỏ qua NaN, tính mean
    with np.errstate(invalid="ignore"):
        adtv = np.nanmean(turnover, axis=0)
    adtv = np.nan_to_num(adtv, nan=0.0)
    return adtv


def is_episode_tradable_at_date(
    episode: ListingEpisode,
    cur_date: pd.Timestamp,
    session_idx_in_episode: int,
    stabilization_sessions: int = 20,
    target_exchange: Exchange = Exchange.HOSE,
) -> bool:
    """Kiểm tra một tập niêm yết có hợp lệ để giao dịch tại ngày cur_date hay không.

    Quy tắc:
    - Sàn niêm yết tại cur_date phải là target_exchange (HOSE).
    - Phải vượt qua khoảng ổn định sau IPO/chuyển sàn (stabilization_sessions).
    - Phải trước hoặc đúng ngày giao dịch cuối cùng (last_trade_date).
    """
    if episode.exchange != target_exchange:
        return False
    if cur_date < episode.first_trade_date:
        return False
    if episode.last_trade_date is not None and cur_date > episode.last_trade_date:
        return False
    if session_idx_in_episode <= stabilization_sessions:
        return False
    return True


def is_suspended_at_date(
    status_events: Sequence[StatusEvent],
    ticker: str,
    cur_date: pd.Timestamp,
) -> bool:
    """Kiểm tra mã có đang bị đình chỉ giao dịch (SUSPENSION) tại ngày cur_date hay không."""
    for ev in status_events:
        if ev.ticker != ticker:
            continue
        if ev.event_type == StatusEventType.SUSPENSION:
            if ev.effective_date <= cur_date:
                if ev.end_date is None or cur_date <= ev.end_date:
                    return True
    return False


def build_pit_tradable_matrix(
    dates: pd.DatetimeIndex | Sequence[pd.Timestamp],
    symbols: Sequence[str],
    episodes: Sequence[ListingEpisode],
    status_events: Sequence[StatusEvent],
    raw_prices: np.ndarray,
    volumes: np.ndarray,
    mode: str = "top_n",  # "top_n" hoặc "fixed_adv"
    top_n: int = 100,
    adv_threshold: float = 30e9,
    adtv_window: int = 20,
    stabilization_sessions: int = 20,
    target_exchange: Exchange = Exchange.HOSE,
) -> np.ndarray:
    """Xây dựng ma trận tradable[t, j] Point-in-Time đáp ứng toàn diện tiêu chí kiểm toán quant.

    Mọi quyết định đưa mã vào universe tại phiên t chỉ phụ thuộc vào thông tin tại t-1 trở về trước.
    """
    n_dates = len(dates)
    n_symbols = len(symbols)
    sym_map = {s: i for i, s in enumerate(symbols)}
    dates_ts = [pd.Timestamp(d) for d in dates]

    tradable = np.zeros((n_dates, n_symbols), dtype=bool)

    # Đếm số phiên niêm yết trên HOSE cho từng mã để kiểm tra thời gian ổn định
    episode_sessions: dict[str, int] = {s: 0 for s in symbols}

    # Gom các episodes theo symbol
    ep_by_sym: dict[str, list[ListingEpisode]] = {s: [] for s in symbols}
    for ep in episodes:
        if ep.ticker in ep_by_sym:
            ep_by_sym[ep.ticker].append(ep)

    for t in range(n_dates):
        cur_date = dates_ts[t]
        adtv = compute_adtv_t_minus_1(raw_prices, volumes, t, window=adtv_window)

        # 1. Lọc điều kiện niêm yết sàn & đình chỉ
        eligible_indices: list[int] = []
        for j, sym in enumerate(symbols):
            sym_eps = ep_by_sym.get(sym, [])
            active_ep = None
            for ep in sym_eps:
                if ep.first_trade_date <= cur_date and (
                    ep.last_trade_date is None or cur_date <= ep.last_trade_date
                ):
                    active_ep = ep
                    break

            if active_ep is None:
                continue

            if active_ep.exchange == target_exchange:
                episode_sessions[sym] += 1
            else:
                episode_sessions[sym] = 0

            if not is_episode_tradable_at_date(
                active_ep,
                cur_date,
                episode_sessions[sym],
                stabilization_sessions=stabilization_sessions,
                target_exchange=target_exchange,
            ):
                continue

            if is_suspended_at_date(status_events, sym, cur_date):
                continue

            eligible_indices.append(j)

        if not eligible_indices:
            continue

        # 2. Áp dụng bộ lọc thanh khoản ADTV tại t-1
        if mode == "fixed_adv":
            for j in eligible_indices:
                if adtv[j] >= adv_threshold:
                    tradable[t, j] = True
        elif mode == "top_n":
            # Sắp xếp các mã đủ điều kiện theo ADTV giảm dần
            sorted_elig = sorted(eligible_indices, key=lambda idx: adtv[idx], reverse=True)
            chosen = sorted_elig[:top_n]
            for j in chosen:
                tradable[t, j] = True
        else:
            raise ValueError(f"Chế độ lọc không hợp lệ: {mode}")

    return tradable


def verify_pit_causality(
    dates: pd.DatetimeIndex | Sequence[pd.Timestamp],
    symbols: Sequence[str],
    episodes: Sequence[ListingEpisode],
    status_events: Sequence[StatusEvent],
    raw_prices: np.ndarray,
    volumes: np.ndarray,
    t_eval: int,
    mode: str = "top_n",
    top_n: int = 100,
    adv_threshold: float = 30e9,
) -> bool:
    """Kiểm tra tính nhân quả (Causality Check):

    Universe tại t_eval tính chỉ với dữ liệu cắt ngắn đến t_eval - 1
    PHẢI BẰNG EXACT universe tại t_eval tính với toàn bộ dữ liệu lịch sử.
    """
    # 1. Tính với toàn bộ dữ liệu
    full_tradable = build_pit_tradable_matrix(
        dates=dates,
        symbols=symbols,
        episodes=episodes,
        status_events=status_events,
        raw_prices=raw_prices,
        volumes=volumes,
        mode=mode,
        top_n=top_n,
        adv_threshold=adv_threshold,
    )
    res_full = full_tradable[t_eval]

    # 2. Cắt ngắn dữ liệu chỉ đến t_eval (phiên t_eval là phiên cuối cùng được cấp)
    # Dữ liệu tương lai sau t_eval bị xóa hoàn toàn khỏi ma trận giá
    truncated_prices = np.full_like(raw_prices, np.nan)
    truncated_volumes = np.full_like(volumes, np.nan)
    truncated_prices[: t_eval + 1] = raw_prices[: t_eval + 1]
    truncated_volumes[: t_eval + 1] = volumes[: t_eval + 1]

    trunc_tradable = build_pit_tradable_matrix(
        dates=dates[: t_eval + 1],
        symbols=symbols,
        episodes=episodes,
        status_events=status_events,
        raw_prices=truncated_prices[: t_eval + 1],
        volumes=truncated_volumes[: t_eval + 1],
        mode=mode,
        top_n=top_n,
        adv_threshold=adv_threshold,
    )
    res_trunc = trunc_tradable[t_eval]

    return bool(np.array_equal(res_full, res_trunc))
