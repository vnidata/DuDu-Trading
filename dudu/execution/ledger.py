"""Quản lý sổ lệnh giao dịch thực tế (Human-in-the-loop Trading Ledger).

Kế thừa từ VN-SWING:
Theo dõi các vị thế mở, lệnh đã chốt, tỷ lệ thắng (Win Rate), hệ số Lời/Lỗ (Profit Factor)
và tổng lợi nhuận thực chiến trên thị trường cơ sở.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd


@dataclass
class TradeRecord:
    id: str
    symbol: str
    entry_date: str
    exit_date: Optional[str]
    entry_price: float
    exit_price: Optional[float]
    shares: int
    pnl: float
    return_pct: float
    holding_days: int
    status: str             # "OPEN", "CLOSED"
    reason: str             # "TrailingStop", "Target", "StopLoss", "Manual"


class LedgerManager:
    """Quản trị sổ lệnh và tổng hợp KPI hiệu suất thực chiến."""

    def __init__(self, trades: Optional[List[TradeRecord]] = None):
        self.trades: List[TradeRecord] = trades or []

    @classmethod
    def from_json(cls, json_path: str | Path) -> "LedgerManager":
        p = Path(json_path)
        if not p.exists():
            return cls([])
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("trades", data.get("trade_history", []))
        records = []
        for item in items:
            rec = TradeRecord(
                id=str(item.get("trade_id", item.get("id", ""))),
                symbol=str(item.get("symbol", "")),
                entry_date=str(item.get("entry_date", "")),
                exit_date=item.get("exit_date"),
                entry_price=float(item.get("entry_price", 0)),
                exit_price=float(item.get("exit_price")) if item.get("exit_price") is not None else None,
                shares=int(item.get("shares", 0)),
                pnl=float(item.get("pnl_vnd", item.get("pnl", 0))),
                return_pct=float(item.get("pnl_pct", item.get("return_pct", 0))),
                holding_days=int(item.get("holding_days", 0)),
                status=str(item.get("status", "CLOSED")),
                reason=str(item.get("exit_reason", item.get("reason", "TrailingStop"))),
            )
            records.append(rec)
        return cls(records)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        return [asdict(t) for t in self.trades]

    def summary_kpis(self) -> Dict[str, Any]:
        """Tính toán các chỉ số KPI thống kê hiệu suất."""
        if not self.trades:
            return {
                "total_trades": 0, "open_trades": 0, "closed_trades": 0,
                "win_rate": 0.0, "profit_factor": 0.0, "total_pnl": 0.0,
                "win_count": 0, "loss_count": 0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0
            }

        closed = [t for t in self.trades if t.status == "CLOSED"]
        opened = [t for t in self.trades if t.status == "OPEN"]
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]

        total_gain = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        profit_factor = (total_gain / total_loss) if total_loss > 0 else (99.0 if total_gain > 0 else 1.0)
        win_rate = (len(wins) / len(closed)) * 100.0 if closed else 0.0

        avg_win = (sum(t.return_pct for t in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(t.return_pct for t in losses) / len(losses)) if losses else 0.0

        return {
            "total_trades": len(self.trades),
            "open_trades": len(opened),
            "closed_trades": len(closed),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "total_pnl": round(sum(t.pnl for t in self.trades), 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
        }
