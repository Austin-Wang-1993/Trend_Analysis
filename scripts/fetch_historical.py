#!/usr/bin/env python3
"""回填历史成交额（TickFlow 日 K）。

申万行业归属使用当前标的池快照归类；TickFlow 不提供逐日历史成份表。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tf_common import (
    attach_industry,
    day_timestamp_range,
    get_client,
    infer_trade_date,
    load_or_build_mapping,
)

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "history"
CST = ZoneInfo("Asia/Shanghai")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填历史成交额（TickFlow）")
    parser.add_argument("--start-date", metavar="YYYY-MM-DD", required=True)
    parser.add_argument("--end-date", metavar="YYYY-MM-DD")
    return parser.parse_args()


def trading_days(start_date: date, end_date: date) -> list[date]:
    days: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def main() -> int:
    args = parse_args()
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date) if args.end_date else infer_trade_date(datetime.now(CST))
    if start_date > end_date:
        print("错误: start-date 不能晚于 end-date", file=sys.stderr)
        return 1

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    tf = get_client()
    stock_map = load_or_build_mapping(tf, end_date)
    symbols = tf.universes.get("CN_Equity_A")["symbols"]

    market_path = HISTORY_DIR / "market_turnover_history.csv"
    industry_path = HISTORY_DIR / "industry_turnover_history.csv"
    for path in (market_path, industry_path):
        if path.exists():
            path.unlink()

    days = trading_days(start_date, end_date)
    print(f"回填 {start_date} ~ {end_date}，共 {len(days)} 个工作日（成份=当前申万标的池）")

    for idx, trade_date in enumerate(days, start=1):
        print(f"  [{idx}/{len(days)}] {trade_date}")
        start_ms, end_ms = day_timestamp_range(trade_date)
        rows = []
        for i in range(0, len(symbols), 200):
            chunk = symbols[i : i + 200]
            dfs = tf.klines.batch(
                chunk,
                period="1d",
                start_time=start_ms,
                end_time=end_ms,
                as_dataframe=True,
                show_progress=False,
            )
            for symbol, df in dfs.items():
                if df is None or df.empty:
                    continue
                day_df = df[df["trade_date"].astype(str) == trade_date.isoformat()]
                if day_df.empty:
                    continue
                row = day_df.iloc[-1]
                rows.append(
                    {
                        "stock_code": symbol,
                        "stock_name": row.get("name", ""),
                        "turnover": float(row.get("amount", 0) or 0),
                        "volume": int(row.get("volume", 0) or 0),
                    }
                )

        if not rows:
            print(f"    跳过（无数据）")
            continue

        stock_df = attach_industry(pd.DataFrame(rows), stock_map)
        stock_df.insert(0, "trade_date", trade_date.isoformat())

        market_row = pd.DataFrame(
            [
                {
                    "trade_date": trade_date.isoformat(),
                    "total_turnover": stock_df["turnover"].sum(),
                    "stock_count": len(stock_df),
                }
            ]
        )
        mapped = stock_df[stock_df["industry_l1_name"].astype(str).str.len() > 0]
        industry_df = (
            mapped.groupby(["trade_date", "industry_l1_name"], as_index=False)
            .agg(
                industry_l1_code=("industry_l1_code", "first"),
                turnover=("turnover", "sum"),
                volume=("volume", "sum"),
                stock_count=("stock_code", "count"),
            )
        )

        market_row.to_csv(market_path, mode="a", header=not market_path.exists(), index=False, encoding="utf-8")
        industry_df.to_csv(industry_path, mode="a", header=not industry_path.exists(), index=False, encoding="utf-8")

    readme = f"""# 历史成交额（TickFlow）

- **date_range**: {start_date} ~ {end_date}
- **成交额**: 日 K `amount`
- **行业归属**: 当前申万标的池快照（非逐日历史成份）

输出：
- market_turnover_history.csv
- industry_turnover_history.csv
"""
    (HISTORY_DIR / "README.md").write_text(readme, encoding="utf-8")
    print(f"\n历史数据已写入: {HISTORY_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
