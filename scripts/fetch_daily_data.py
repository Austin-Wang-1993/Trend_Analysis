#!/usr/bin/env python3
"""从 TickFlow 拉取申万行业成交额并输出 CSV。

认证（完整服务，含实时行情）：
  export TICKFLOW_API_KEY=your-api-key

无 API Key 时自动使用免费服务（仅历史日 K，适合 --date 指定历史交易日）。

建议在交易日 17:00（CST）后执行当日采集。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tf_common import (
    attach_industry,
    fetch_turnover_klines,
    fetch_turnover_quotes,
    get_client,
    infer_trade_date,
    load_or_build_mapping,
    mapping_to_dataframe,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CST = ZoneInfo("Asia/Shanghai")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拉取申万行业成交额（TickFlow）")
    parser.add_argument("--date", dest="trade_date", metavar="YYYY-MM-DD", help="交易日")
    parser.add_argument("--refresh-mapping", action="store_true", help="强制刷新申万标的池映射缓存")
    return parser.parse_args()


def resolve_trade_date(value: str | None, snapshot_time: datetime) -> date:
    if value:
        return date.fromisoformat(value)
    return infer_trade_date(snapshot_time)


def write_readme(trade_date: date, snapshot_time: datetime, use_quotes: bool) -> None:
    mode = "实时行情 quotes" if use_quotes else "历史日K klines"
    readme = f"""# 数据说明

- **trade_date**: {trade_date.isoformat()}
- **snapshot_time**: {snapshot_time.isoformat()}
- **数据源**: TickFlow（申万标的池 `CN_Equity_SW*`）
- **成交额口径**: {mode} 的 `amount` 字段
- **成份说明**: 申万标的池为**当前成份快照**；历史 `--date` 的成交额来自日 K，行业归属用当前标的池归类

## 文件

| 文件 | 说明 |
|------|------|
| industry_stock_mapping.csv | 申万行业-个股映射（L1/L2/L3） |
| market_turnover_daily.csv | 全 A 成交额 |
| industry_turnover_daily.csv | 一级申万行业成交额 |
| stock_turnover_daily.csv | 个股成交额 + 行业归属 |
"""
    (DATA_DIR / "README.md").write_text(readme, encoding="utf-8")


def print_validation(
    trade_date: date,
    snapshot_time: datetime,
    mapping_df: pd.DataFrame,
    market_df: pd.DataFrame,
    industry_df: pd.DataFrame,
    stock_df: pd.DataFrame,
) -> None:
    market_total = float(market_df["total_turnover"].iloc[0])
    industry_sum = float(industry_df["turnover"].sum())
    ratio = industry_sum / market_total if market_total else 0.0
    mapped = stock_df[stock_df["industry_l1_name"].astype(str).str.len() > 0]

    print("\n========== 校验报告 ==========")
    print(f"trade_date:      {trade_date}")
    print(f"snapshot_time:   {snapshot_time.isoformat()}")
    print(f"映射股票数:      {len(mapping_df)}")
    print(f"有行情股票数:    {len(stock_df)}")
    print(f"有申万归属:      {len(mapped)}")
    print(f"一级行业数:      {len(industry_df)}")
    print(f"大盘成交额:      {market_total:,.0f} 元")
    print(f"行业成交额合计:  {industry_sum:,.0f} 元")
    print(f"行业/大盘:       {ratio:.2%}")


def main() -> int:
    args = parse_args()
    snapshot_time = datetime.now(CST)
    trade_date = resolve_trade_date(args.trade_date, snapshot_time)
    has_api_key = bool(os.environ.get("TICKFLOW_API_KEY", "").strip())

    if not args.trade_date and snapshot_time.hour < 17:
        print(
            f"警告: 当前 {snapshot_time.strftime('%H:%M')} CST，建议交易日 17:00 后采集。",
            file=sys.stderr,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tf = get_client()

    print(f"拉取 trade_date = {trade_date}（TickFlow 申万标的池）...")

    print("  ① 申万行业-个股映射（标的池）...")
    stock_map = load_or_build_mapping(tf, trade_date, refresh=args.refresh_mapping)
    mapping_df = mapping_to_dataframe(stock_map, trade_date)
    print(f"     映射股票数: {len(mapping_df)}")

    print("  ② 个股成交额...")
    use_quotes = has_api_key and trade_date == infer_trade_date(snapshot_time)
    if use_quotes:
        try:
            stock_turnover = fetch_turnover_quotes(tf, trade_date)
        except Exception as exc:
            print(f"     quotes 失败，回退日 K: {exc}", file=sys.stderr)
            use_quotes = False
            stock_turnover = pd.DataFrame()
    else:
        stock_turnover = pd.DataFrame()

    if stock_turnover.empty:
        use_quotes = False
        symbols = tf.universes.get("CN_Equity_A")["symbols"]
        print(f"     使用日 K 拉取 {len(symbols)} 只股票...")
        stock_turnover = fetch_turnover_klines(tf, symbols, trade_date)

    if stock_turnover.empty:
        print(f"错误: {trade_date} 无成交额数据，请确认是否为交易日", file=sys.stderr)
        return 1

    stock_df = attach_industry(stock_turnover, stock_map)
    stock_df.insert(0, "trade_date", trade_date.isoformat())
    stock_df.insert(1, "snapshot_time", snapshot_time.isoformat())

    print("  ③ 大盘 / 行业汇总...")
    market_df = pd.DataFrame(
        [
            {
                "trade_date": trade_date.isoformat(),
                "snapshot_time": snapshot_time.isoformat(),
                "total_turnover": stock_df["turnover"].sum(),
                "stock_count": len(stock_df),
            }
        ]
    )

    mapped = stock_df[stock_df["industry_l1_name"].astype(str).str.len() > 0].copy()
    industry_df = (
        mapped.groupby("industry_l1_name", as_index=False)
        .agg(
            industry_l1_code=("industry_l1_code", "first"),
            turnover=("turnover", "sum"),
            volume=("volume", "sum"),
            stock_count=("stock_code", "count"),
        )
        .sort_values("turnover", ascending=False)
    )
    industry_df.insert(0, "trade_date", trade_date.isoformat())
    industry_df.insert(1, "snapshot_time", snapshot_time.isoformat())

    mapping_df.to_csv(DATA_DIR / "industry_stock_mapping.csv", index=False, encoding="utf-8")
    market_df.to_csv(DATA_DIR / "market_turnover_daily.csv", index=False, encoding="utf-8")
    industry_df.to_csv(DATA_DIR / "industry_turnover_daily.csv", index=False, encoding="utf-8")
    stock_df.to_csv(DATA_DIR / "stock_turnover_daily.csv", index=False, encoding="utf-8")
    write_readme(trade_date, snapshot_time, use_quotes)

    print_validation(trade_date, snapshot_time, mapping_df, market_df, industry_df, stock_df)
    print(f"\n数据已写入: {DATA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
