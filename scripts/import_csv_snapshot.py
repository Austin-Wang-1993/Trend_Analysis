#!/usr/bin/env python3
"""将 data/ 下最新 CSV 快照导入 SQLite history.db（快速初始化看板）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from history_store import HistoryStore

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def main() -> int:
    stock_path = DATA_DIR / "stock_turnover_latest.csv"
    sector_path = DATA_DIR / "sector_turnover_daily.csv"
    if not stock_path.exists():
        print(f"错误: 找不到 {stock_path}", file=sys.stderr)
        return 1

    stock_df = pd.read_csv(stock_path)
    sector_df = pd.read_csv(sector_path) if sector_path.exists() else pd.DataFrame()
    sector_ff_path = DATA_DIR / "sector_fund_flow_daily.csv"
    sector_ff_df = pd.read_csv(sector_ff_path) if sector_ff_path.exists() else None
    market_path = DATA_DIR / "market_summary_daily.csv"
    market_row = None
    if market_path.exists():
        market_row = pd.read_csv(market_path).iloc[0].to_dict()
    etf_path = DATA_DIR / "etf_turnover_latest.csv"
    etf_df = pd.read_csv(etf_path) if etf_path.exists() else None

    trade_date = str(stock_df["trade_date"].iloc[0])
    snapshot_time = str(stock_df["snapshot_time"].iloc[0]) if "snapshot_time" in stock_df.columns else ""

    store = HistoryStore(DB_PATH)
    store.upsert_snapshot(
        trade_date=trade_date,
        stock_df=stock_df,
        sector_df=sector_df,
        sector_ff_df=sector_ff_df,
        market_row=market_row,
        etf_df=etf_df,
        snapshot_time=snapshot_time,
    )
    print(f"已导入 trade_date={trade_date} → {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
