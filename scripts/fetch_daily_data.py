#!/usr/bin/env python3
"""从 BigQuant DAI 拉取申万 2021 行业成交额数据并输出 CSV。

建议在交易日 17:00（CST）后于腾讯云国内节点执行。
认证：bq auth --apikey <AK.SK>
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bq_common import (
    fetch_industry_range,
    fetch_mapping_range,
    fetch_market_range,
    fetch_stock_range,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CST = ZoneInfo("Asia/Shanghai")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拉取申万行业成交额（BigQuant DAI）")
    parser.add_argument(
        "--date",
        dest="trade_date",
        metavar="YYYY-MM-DD",
        help="交易日（默认：最近一个工作日）",
    )
    return parser.parse_args()


def infer_trade_date(snapshot_time: datetime) -> date:
    d = snapshot_time.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def resolve_trade_date(value: str | None, snapshot_time: datetime) -> date:
    if value:
        return date.fromisoformat(value)
    return infer_trade_date(snapshot_time)


def write_readme(trade_date: date, snapshot_time: datetime) -> None:
    readme = f"""# 数据说明

- **trade_date**: {trade_date.isoformat()}
- **snapshot_time**: {snapshot_time.isoformat()}
- **数据源**: BigQuant DAI（申万 2021，`industry = sw2021`）
- **映射表**: `cn_stock_industry_component`（当日历史成份，非静态快照）
- **行情表**: `cn_stock_bar1d`（成交额 `amount`）

## 文件

| 文件 | 说明 |
|------|------|
| industry_stock_mapping.csv | 当日行业-个股映射（含 L1/L2/L3） |
| market_turnover_daily.csv | 全 A 成交额 |
| industry_turnover_daily.csv | 一级申万行业成交额 |
| stock_turnover_daily.csv | 个股成交额 + 当日行业归属 |
"""
    (DATA_DIR / "README.md").write_text(readme, encoding="utf-8")


def print_validation(
    trade_date: date,
    snapshot_time: datetime,
    mapping_df,
    market_df,
    industry_df,
    stock_df,
) -> None:
    market_total = float(market_df["total_turnover"].iloc[0])
    industry_sum = float(industry_df["turnover"].sum())
    ratio = industry_sum / market_total if market_total else 0.0

    print("\n========== 校验报告 ==========")
    print(f"trade_date:      {trade_date}")
    print(f"snapshot_time:   {snapshot_time.isoformat()}")
    print(f"映射行数:        {len(mapping_df)}")
    print(f"个股成交额行数:  {len(stock_df)}")
    print(f"行业数:          {len(industry_df)}")
    print(f"大盘成交额:      {market_total:,.0f} 元")
    print(f"行业成交额合计:  {industry_sum:,.0f} 元（申万成份股口径）")
    print(f"行业/大盘:       {ratio:.2%}")

    if len(mapping_df) != len(stock_df):
        print(
            f"警告: 映射行数 ({len(mapping_df)}) 与个股行数 ({len(stock_df)}) 不一致",
            file=sys.stderr,
        )

    empty_industries = industry_df[industry_df["stock_count"] < 1]
    if not empty_industries.empty:
        print(f"警告: {len(empty_industries)} 个行业 stock_count < 1", file=sys.stderr)


def main() -> int:
    args = parse_args()
    snapshot_time = datetime.now(CST)
    trade_date = resolve_trade_date(args.trade_date, snapshot_time)

    if not args.trade_date and snapshot_time.hour < 17:
        print(
            f"警告: 当前 {snapshot_time.strftime('%H:%M')} CST，建议交易日 17:00 后采集收盘数据。",
            file=sys.stderr,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"拉取 trade_date = {trade_date}（申万 2021，当日历史成份）...")

    print("  ① 行业-个股映射...")
    mapping_df = fetch_mapping_range(trade_date, trade_date)
    print(f"     行数: {len(mapping_df)}")

    print("  ② 大盘成交额...")
    market_df = fetch_market_range(trade_date, trade_date)
    market_df.insert(1, "snapshot_time", snapshot_time.isoformat())
    print(f"     股票数: {market_df['stock_count'].iloc[0]}")

    print("  ③ 行业 / 个股成交额（JOIN 当日成份）...")
    industry_df = fetch_industry_range(trade_date, trade_date)
    industry_df.insert(1, "snapshot_time", snapshot_time.isoformat())

    stock_df = fetch_stock_range(trade_date, trade_date)
    stock_df.insert(1, "snapshot_time", snapshot_time.isoformat())
    print(f"     行业数: {len(industry_df)}，个股数: {len(stock_df)}")

    if stock_df.empty:
        print(f"错误: {trade_date} 无申万成份股行情，请确认是否为交易日", file=sys.stderr)
        return 1

    mapping_df.to_csv(DATA_DIR / "industry_stock_mapping.csv", index=False, encoding="utf-8")
    market_df.to_csv(DATA_DIR / "market_turnover_daily.csv", index=False, encoding="utf-8")
    industry_df.to_csv(DATA_DIR / "industry_turnover_daily.csv", index=False, encoding="utf-8")
    stock_df.to_csv(DATA_DIR / "stock_turnover_daily.csv", index=False, encoding="utf-8")
    write_readme(trade_date, snapshot_time)

    print_validation(trade_date, snapshot_time, mapping_df, market_df, industry_df, stock_df)
    print(f"\n数据已写入: {DATA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
