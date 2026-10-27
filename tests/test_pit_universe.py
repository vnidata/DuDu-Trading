import numpy as np
import pandas as pd
import pytest

from dudu.universe.schema import (
    Exchange,
    EndReason,
    ListingEpisode,
    StatusEvent,
    StatusEventType,
)
from dudu.universe.pit import (
    compute_adtv_t_minus_1,
    build_pit_tradable_matrix,
    verify_pit_causality,
)


def test_adtv_t_minus_1_strictly_excludes_t():
    raw_prices = np.full((10, 2), 10000.0)
    volumes = np.full((10, 2), 1000.0)
    # Tại phiên t=5, đột ngột có volume cực lớn 10_000_000
    volumes[5, 0] = 10_000_000.0

    # Tại t=5, ADTV phải tính từ các phiên 0..4 (mỗi phiên 10k * 1k = 10M), KHÔNG ĐƯỢC CHỨA phiên 5
    adtv_at_5 = compute_adtv_t_minus_1(raw_prices, volumes, t=5, window=5)
    assert np.isclose(adtv_at_5[0], 10_000.0 * 1_000.0)

    # Đến t=6, volume đột biến của phiên 5 mới được phản ánh
    adtv_at_6 = compute_adtv_t_minus_1(raw_prices, volumes, t=6, window=5)
    assert adtv_at_6[0] > adtv_at_5[0]


def test_pit_stabilization_and_suspension():
    dates = pd.bdate_range("2024-01-01", periods=100)
    symbols = ["AAA", "BBB"]

    # AAA lên sàn HOSE từ ngày đầu tiên
    ep_aaa = ListingEpisode(
        security_id="SEC_AAA",
        ticker="AAA",
        exchange=Exchange.HOSE,
        first_trade_date=dates[0],
        last_trade_date=None,
    )
    # BBB lên sàn HOSE từ ngày 30
    ep_bbb = ListingEpisode(
        security_id="SEC_BBB",
        ticker="BBB",
        exchange=Exchange.HOSE,
        first_trade_date=dates[30],
        last_trade_date=dates[80],  # Hủy niêm yết tại ngày 80
        end_reason=EndReason.MANDATORY_DELIST,
    )

    # AAA bị đình chỉ từ ngày 50 đến ngày 55
    susp_aaa = StatusEvent(
        security_id="SEC_AAA",
        ticker="AAA",
        event_type=StatusEventType.SUSPENSION,
        effective_date=dates[50],
        end_date=dates[55],
    )

    prices = np.full((100, 2), 20000.0)
    volumes = np.full((100, 2), 500000.0)

    tradable = build_pit_tradable_matrix(
        dates=dates,
        symbols=symbols,
        episodes=[ep_aaa, ep_bbb],
        status_events=[susp_aaa],
        raw_prices=prices,
        volumes=volumes,
        mode="fixed_adv",
        adv_threshold=1e9,
        stabilization_sessions=20,
    )

    # 1. AAA: 20 phiên đầu ổn định -> không tradable
    assert not np.any(tradable[:20, 0])
    # Từ phiên 20 trở đi (phiên thứ 21) -> tradable
    assert tradable[20, 0]

    # AAA bị đình chỉ tại phiên 50..55 -> không tradable
    for t in range(50, 56):
        assert not tradable[t, 0]
    # Sau đình chỉ -> tradable trở lại
    assert tradable[56, 0]

    # 2. BBB: Trước ngày 30 chưa lên HOSE -> không tradable
    assert not np.any(tradable[:30, 1])
    # 20 phiên ổn định sau ngày 30 (tức là 30..49) -> không tradable
    assert not np.any(tradable[30:50, 1])
    assert tradable[50, 1]  # Phiên thứ 21 trên HOSE

    # Sau ngày 80 (hủy niêm yết) -> không tradable
    assert not np.any(tradable[81:, 1])


def test_pit_causality_verification():
    np.random.seed(42)
    dates = pd.bdate_range("2024-01-01", periods=60)
    symbols = ["SYM1", "SYM2", "SYM3"]
    episodes = [
        ListingEpisode("S1", "SYM1", Exchange.HOSE, dates[0]),
        ListingEpisode("S2", "SYM2", Exchange.HOSE, dates[0]),
        ListingEpisode("S3", "SYM3", Exchange.HOSE, dates[10]),
    ]
    prices = np.random.uniform(10000, 50000, size=(60, 3))
    volumes = np.random.uniform(100000, 2000000, size=(60, 3))

    # Kiểm tra causality tại các mốc t khác nhau
    for t_test in [25, 35, 45, 55]:
        passed = verify_pit_causality(
            dates=dates,
            symbols=symbols,
            episodes=episodes,
            status_events=[],
            raw_prices=prices,
            volumes=volumes,
            t_eval=t_test,
            mode="top_n",
            top_n=2,
        )
        assert passed, f"Causality failed at t={t_test}"


def test_saved_universe_artifacts_integrity():
    from pathlib import Path
    import json

    ep_path = Path("data/universe/listing_episodes.json")
    t30_path = Path("data/universe/tradable_fixed_30b.npy")
    top_path = Path("data/universe/tradable_top_100.npy")

    if ep_path.exists() and t30_path.exists() and top_path.exists():
        episodes = json.load(open(ep_path, encoding="utf-8"))
        assert len(episodes) > 100
        tickers = {ep["ticker"] for ep in episodes}
        assert "ROS" in tickers
        assert "FLC" in tickers
        assert "HBC" in tickers

        m_30b = np.load(t30_path)
        m_top = np.load(top_path)
        assert m_30b.shape == m_top.shape
        assert m_30b.dtype == bool
        assert m_top.dtype == bool

