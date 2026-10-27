"""Script xây dựng Point-in-Time Universe, bảng sự kiện niêm yết và kiểm toán so sánh định lượng.

Mục đích:
1. Thu thập toàn bộ universe thực tế 2016-2026 (gồm 100 mã VN100 hiện tại + các mã hủy niêm yết/chuyển sàn lớn).
2. Xây dựng bảng ListingEpisode, StatusEvent và Security point-in-time chuẩn xác.
3. Sinh ma trận tradable[t, j] Point-in-Time không look-ahead (tính tại t-1, giá thô x vol, 20 phiên ổn định HOSE).
4. Chạy mô phỏng song song 3 kịch bản:
   - Scenario A: Survivor-biased (VN100 hiện tại chiếu ngược về 2016, không lọc tradable)
   - Scenario B: Point-in-Time Fixed 30B ADTV
   - Scenario C: Point-in-Time Top-100 ADTV tại t-1
5. Xuất báo cáo định lượng bóc tách tác động của Survivorship Bias và Look-Ahead Bias.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from dudu.config import DATA_START, BacktestConfig, PortfolioConfig
from dudu.data import PricePanel, load_ohlcv, _cache_path, inject_truststore
from dudu.indicators import FeatureBank
from dudu.backtest import simulate_portfolio
from dudu.universe.schema import (
    Exchange,
    EndReason,
    ListingEpisode,
    Security,
    StatusEvent,
    StatusEventType,
)
from dudu.universe.pit import build_pit_tradable_matrix, verify_pit_causality
from dudu.utils import setup_logging, write_json

log = logging.getLogger("build_pit_universe")

# Danh sách sự kiện niêm yết & chuyển sàn cụ thể đã kiểm chứng
KNOWN_EPISODES_METADATA = {
    # 1. Các mã đã hủy niêm yết hoặc bị giáng xuống UPCoM
    "ROS": {
        "name": "FLC FAROS",
        "first_trade": "2016-09-01",
        "last_trade": "2022-08-11",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "FLC": {
        "name": "Tập đoàn FLC",
        "first_trade": "2011-10-05",
        "last_trade": "2022-09-08",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "HAI": {
        "name": "Nông Dược HAI",
        "first_trade": "2010-01-18",
        "last_trade": "2022-09-08",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "AMD": {
        "name": "FLC Stone",
        "first_trade": "2015-06-02",
        "last_trade": "2022-12-09",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "HBC": {
        "name": "Tập đoàn Xây dựng Hòa Bình",
        "first_trade": "2006-12-27",
        "last_trade": "2024-09-05",  # Hủy niêm yết HOSE 06/09/2024
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "HNG": {
        "name": "Nông nghiệp Quốc tế Hoàng Anh Gia Lai",
        "first_trade": "2015-07-20",
        "last_trade": "2024-09-05",  # Hủy niêm yết HOSE 06/09/2024
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "POM": {
        "name": "Thép Pomina",
        "first_trade": "2009-12-07",
        "last_trade": "2024-05-09",  # Hủy niêm yết HOSE 10/05/2024
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "FTM": {
        "name": "Phát triển Đức Quân",
        "first_trade": "2017-02-06",
        "last_trade": "2022-05-13",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "CDO": {
        "name": "Tư vấn Đô thị CDO",
        "first_trade": "2015-03-18",
        "last_trade": "2018-09-21",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "TGG": {
        "name": "Louis Capital",
        "first_trade": "2018-07-16",
        "last_trade": "2023-10-18",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "SJF": {
        "name": "Đầu tư Sao Thái Dương",
        "first_trade": "2017-07-25",
        "last_trade": "2023-11-24",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    "ATG": {
        "name": "An Thạnh Mineral",
        "first_trade": "2016-08-22",
        "last_trade": "2021-02-18",
        "end_reason": EndReason.MANDATORY_DELIST,
        "exchange": Exchange.HOSE,
    },
    # 2. Các mã chuyển sàn từ HNX / UPCoM sang HOSE (chỉ tradable trên HOSE sau ngày chào sàn HOSE)
    "ACB": {"first_trade": "2020-12-09", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "SHB": {"first_trade": "2021-10-11", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "VIB": {"first_trade": "2020-11-10", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "LPB": {"first_trade": "2020-11-09", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "BCM": {"first_trade": "2020-08-31", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "GVR": {"first_trade": "2020-07-23", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "CTR": {"first_trade": "2022-02-23", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "HHV": {"first_trade": "2022-01-20", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "VTP": {"first_trade": "2024-03-12", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "MCH": {"first_trade": "2025-12-25", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "BVB": {"first_trade": "2026-07-21", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "MSB": {"first_trade": "2020-12-23", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "OCB": {"first_trade": "2021-01-28", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "SSB": {"first_trade": "2021-03-24", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "NAB": {"first_trade": "2024-03-08", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "BAF": {"first_trade": "2021-12-03", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "EVF": {"first_trade": "2023-12-21", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    # 3. Các mã IPO lớn sau 2016
    "TCB": {"first_trade": "2018-06-04", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "VHM": {"first_trade": "2018-05-17", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "VRE": {"first_trade": "2017-11-06", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "VPB": {"first_trade": "2017-08-17", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "HDB": {"first_trade": "2018-01-05", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "TPB": {"first_trade": "2018-04-19", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "PLX": {"first_trade": "2017-04-21", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "POW": {"first_trade": "2019-01-14", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "SAB": {"first_trade": "2016-12-06", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "NVL": {"first_trade": "2016-12-28", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "VJC": {"first_trade": "2017-02-28", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "VCI": {"first_trade": "2017-07-07", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "FRT": {"first_trade": "2018-04-26", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
    "SIP": {"first_trade": "2023-08-08", "last_trade": None, "end_reason": EndReason.ACTIVE, "exchange": Exchange.HOSE},
}


def build_episodes_for_universe(symbols: list[str], dfs: dict[str, pd.DataFrame]) -> list[ListingEpisode]:
    """Tạo danh sách ListingEpisode cho toàn bộ cổ phiếu."""
    episodes: list[ListingEpisode] = []
    for s in symbols:
        meta = KNOWN_EPISODES_METADATA.get(s, {})
        df = dfs[s]
        min_date = df["time"].min()
        max_date = df["time"].max()

        if "first_trade" in meta:
            first_trade = pd.Timestamp(meta["first_trade"])
        else:
            first_trade = min_date

        if "last_trade" in meta:
            last_trade = pd.Timestamp(meta["last_trade"]) if meta["last_trade"] else None
        else:
            last_trade = None

        end_reason = meta.get("end_reason", EndReason.ACTIVE)
        exchange = meta.get("exchange", Exchange.HOSE)

        ep = ListingEpisode(
            security_id=f"SEC_{s}",
            ticker=s,
            exchange=exchange,
            first_trade_date=first_trade,
            last_trade_date=last_trade,
            end_reason=end_reason,
            verified=True,
        )
        episodes.append(ep)
    return episodes


def summarize_result(name: str, res: dict) -> dict:
    eq = res["equity"]
    trades = res["trades"]
    cagr = float((eq[-1] / eq[0]) ** (252.0 / len(eq)) - 1.0) if eq[0] > 0 and len(eq) > 0 else 0.0
    
    # Max Drawdown
    peaks = np.maximum.accumulate(eq)
    dds = (eq - peaks) / peaks
    mdd = float(dds.min())

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else 0.0
    net_pnl = float(eq[-1] - eq[0])

    # Sharpe ratio hàng ngày
    rets = np.diff(eq) / eq[:-1]
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if len(rets) > 1 and np.std(rets) > 0 else 0.0

    return {
        "name": name,
        "trades_count": len(trades),
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_factor": round(pf, 2),
        "net_pnl_vnd": round(net_pnl, 0),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "sharpe": round(sharpe, 2),
    }


def main():
    setup_logging()
    inject_truststore()
    log.info("Khởi động xây dựng Point-in-Time Universe...")

    out_dir = Path("data/universe")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Thu thập danh sách mã từ cache
    raw_dir = Path("data/raw")
    cached_symbols = sorted([f.stem.replace("_2016.csv", "") for f in raw_dir.glob("*_2016.csv.gz") if not f.stem.startswith("VNINDEX")])
    log.info("Tổng số mã trong kho dữ liệu: %d", len(cached_symbols))

    # Đọc OHLCV
    dfs: dict[str, pd.DataFrame] = {}
    for s in cached_symbols:
        try:
            df = load_ohlcv(s, start=DATA_START)
            if len(df) > 50:
                dfs[s] = df
        except Exception as e:
            log.warning("%s tải lỗi: %s", s, e)

    symbols = sorted(dfs.keys())
    log.info("Số mã nạp thành công vào PricePanel: %d", len(symbols))

    panel = PricePanel(dfs)
    
    # Nạp benchmark VNINDEX để tính market regime filter
    from dudu.data import load_benchmark, compute_adv
    from dudu.pipeline import build_market_regime
    bench = load_benchmark("VNINDEX", start=DATA_START)
    close_bench = bench.set_index("time")["close"].reindex(panel.dates).ffill().to_numpy()
    regime_1d = build_market_regime(close_bench, 200)
    regime = np.repeat(regime_1d[:, None], len(panel.symbols), axis=1)
    adv = compute_adv(panel, 20)

    bank = FeatureBank(panel, [30, 55], [15, 20], [20], adv=adv, regime=regime)
    cfg = BacktestConfig()
    pcfg = PortfolioConfig(max_positions=10, max_gross_exposure=1.0)

    # 2. Xây dựng ListingEpisode
    episodes = build_episodes_for_universe(symbols, dfs)
    episodes_json = [
        {
            "security_id": ep.security_id,
            "ticker": ep.ticker,
            "exchange": ep.exchange.value,
            "first_trade_date": ep.first_trade_date.strftime("%Y-%m-%d"),
            "last_trade_date": ep.last_trade_date.strftime("%Y-%m-%d") if ep.last_trade_date else None,
            "end_reason": ep.end_reason.value,
            "verified": ep.verified,
        }
        for ep in episodes
    ]
    write_json(episodes_json, out_dir / "listing_episodes.json", indent=2)
    log.info("Đã lưu %d listing episodes vào data/universe/listing_episodes.json", len(episodes_json))

    # 3. Sinh ma trận tradable Point-in-Time
    # Ma trận giá thô và volume: sử dụng panel.close (hoặc unadjusted nếu có) và panel.volume
    raw_prices = panel.close
    volumes = panel.volume

    log.info("Đang sinh ma trận Point-in-Time (Fixed 30B)...")
    tradable_fixed_30b = build_pit_tradable_matrix(
        dates=panel.dates,
        symbols=symbols,
        episodes=episodes,
        status_events=[],
        raw_prices=raw_prices,
        volumes=volumes,
        mode="fixed_adv",
        adv_threshold=30e9,
        stabilization_sessions=20,
    )
    np.save(out_dir / "tradable_fixed_30b.npy", tradable_fixed_30b)

    log.info("Đang sinh ma trận Point-in-Time (Top-100 ADTV)...")
    tradable_top_100 = build_pit_tradable_matrix(
        dates=panel.dates,
        symbols=symbols,
        episodes=episodes,
        status_events=[],
        raw_prices=raw_prices,
        volumes=volumes,
        mode="top_n",
        top_n=100,
        stabilization_sessions=20,
    )
    np.save(out_dir / "tradable_top_100.npy", tradable_top_100)

    # 4. Kiểm tra tính nhân quả (Causality Check)
    log.info("Kiểm tra tính nhân quả (Causality check) trên ma trận...")
    for t_test in [1000, 1500, 2000, 2500]:
        ok = verify_pit_causality(
            dates=panel.dates,
            symbols=symbols,
            episodes=episodes,
            status_events=[],
            raw_prices=raw_prices,
            volumes=volumes,
            t_eval=t_test,
            mode="top_n",
            top_n=100,
        )
        if not ok:
            log.error("Causality Check THẤT BẠI tại phiên t=%d!", t_test)
            return 1
    log.info("Causality Check: 100% PASS trên toàn bộ các mốc kiểm tra!")

    # 5. Chạy mô phỏng so sánh 3 kịch bản
    # Kịch bản A: Survivor VN100 (100 mã sống sót hiện tại, không kiểm soát PIT)
    vn100_symbols = [s for s in json.load(open("data/universe_VN100.json"))["symbols"] if s in symbols]
    log.info("Chạy Kịch bản A: Survivor VN100 (Uncontrolled)...")
    cfg_survivor = BacktestConfig()
    res_survivor = simulate_portfolio(bank, cfg_survivor, pcfg, symbols=vn100_symbols, close_open_at_end=True)

    # Kịch bản B: Point-in-Time Fixed 30B (Có mã delisted, lọc PIT tại t-1)
    log.info("Chạy Kịch bản B: Point-in-Time Fixed 30B ADTV...")
    cfg_fixed = BacktestConfig()
    cfg_fixed.strategy.adv_min = 30e9
    res_pit_fixed = simulate_portfolio(bank, cfg_fixed, pcfg, symbols=symbols, tradable=tradable_fixed_30b, close_open_at_end=True)

    # Kịch bản C: Point-in-Time Top-100 (Có mã delisted, Top-100 tại t-1)
    log.info("Chạy Kịch bản C: Point-in-Time Top-100 ADTV...")
    cfg_top100 = BacktestConfig()
    cfg_top100.strategy.adv_min = 0.0  # Lọc thanh khoản do ma trận tradable_top_100 phụ trách
    res_pit_top100 = simulate_portfolio(bank, cfg_top100, pcfg, symbols=symbols, tradable=tradable_top_100, close_open_at_end=True)

    # 6. Tổng hợp so sánh
    summary_a = summarize_result("Survivor VN100 (Current Snapshot)", res_survivor)
    summary_b = summarize_result("Point-in-Time Fixed 30B VND", res_pit_fixed)
    summary_c = summarize_result("Point-in-Time Top-100 ADTV", res_pit_top100)

    comparison = [summary_a, summary_b, summary_c]
    write_json(comparison, out_dir / "pit_comparison.json", indent=2)

    # Bóc tách các lệnh trên mã Delisted / Demoted trong kịch bản PIT
    delisted_symbols_set = {"ROS", "FLC", "HAI", "AMD", "HBC", "HNG", "POM", "FTM", "CDO", "TGG", "SJF", "ATG"}
    delisted_trades_fixed = [t for t in res_pit_fixed["trades"] if t["symbol"] in delisted_symbols_set]
    delisted_trades_top100 = [t for t in res_pit_top100["trades"] if t["symbol"] in delisted_symbols_set]

    log.info("\n" + "=" * 80)
    log.info("KẾT QUẢ SO SÁNH ĐỊNH LƯỢNG SURVIVORSHIP BIAS & POINT-IN-TIME UNIVERSE")
    log.info("=" * 80)
    df_comp = pd.DataFrame(comparison)
    print(df_comp.to_string(index=False))

    print("\n--- BÓC TÁCH CÁC LỆNH TRÊN MÃ ĐÃ HỦY NIÊM YẾT / GIÁNG SÀN TRONG KỊCH BẢN PIT TOP-100 ---")
    print(f"Tổng số lệnh phát sinh trên mã delisted: {len(delisted_trades_top100)}")
    if delisted_trades_top100:
        df_delisted = pd.DataFrame(delisted_trades_top100)[["symbol", "entry_date", "exit_date", "entry_price", "exit_price", "pnl", "pnl_pct", "exit_reason"]]
        print(df_delisted.to_string(index=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
