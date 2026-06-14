#!/usr/bin/env python3
"""从 BigQuant DAI 拉取行业分类、板块映射与个股成交额。

输出（data/）：
  - sectors.csv                 全量行业分类明细（cn_stock_industry）
  - sector_stock_mapping.csv    板块 ↔ 个股映射（cn_stock_industry_component）
  - stock_turnover_latest.csv   个股成交额 + 行业归属
  - sector_turnover_daily.csv   一级行业成交额汇总
  - unmapped_stocks.csv         有成交额但无行业归属的股票

认证（任选其一）：
  export BIGQUANT_APIKEY=AK.SK
  # 或
  export BIGQUANT_AK=... BIGQUANT_SK=...
  # 或先执行：bq auth --apikey AK.SK

前置条件：
  - Python 3.11+
  - 已在 BigQuant 开通 SDK 使用权限
  - pip install bigquant -i https://pypi.bigquant.com/simple/
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bq_common import (
    DEFAULT_INDUSTRY,
    IndustryStd,
    aggregate_sector_turnover,
    attach_industry,
    ensure_auth,
    fetch_latest_trade_date,
    fetch_sector_mapping,
    fetch_sectors,
    fetch_stock_turnover,
    infer_snapshot_time,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BigQuant 行业板块 + 成交额采集")
    parser.add_argument("--date", dest="trade_date", metavar="YYYY-MM-DD", help="交易日（默认最近交易日）")
    parser.add_argument(
        "--industry",
        choices=["sw2021", "sw2014", "cs"],
        default=DEFAULT_INDUSTRY,
        help="行业标准（默认 sw2021 申万2021）",
    )
    return parser.parse_args()


def resolve_trade_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    return fetch_latest_trade_date()


def write_readme(
    trade_date: str,
    snapshot_time: str,
    industry: str,
    sector_count: int,
    mapped: int,
    unmapped: int,
) -> None:
    readme = f"""# 数据说明（BigQuant DAI）

- **trade_date**: {trade_date}
- **snapshot_time**: {snapshot_time}
- **行业标准**: {industry}
- **板块分类表**: cn_stock_industry
- **成份映射表**: cn_stock_industry_component（逐日 point-in-time）
- **成交额表**: cn_stock_bar1d.amount
- **板块数（三级明细）**: {sector_count}
- **有行业归属**: {mapped}
- **未归类**: {unmapped}

## 文件

| 文件 | 说明 |
|------|------|
| sectors.csv | 全量行业分类明细 |
| sector_stock_mapping.csv | 板块与个股映射 |
| stock_turnover_latest.csv | 个股成交额 + 行业归属 |
| sector_turnover_daily.csv | 一级行业成交额汇总 |
| unmapped_stocks.csv | 有成交额但无行业归属 |
"""
    (DATA_DIR / "README.md").write_text(readme, encoding="utf-8")


def print_validation(
    trade_date: str,
    sectors_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    stock_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    unmapped_df: pd.DataFrame,
) -> None:
    mapped = stock_df[stock_df["industry_l1_name"].notna() & (stock_df["industry_l1_name"].astype(str).str.len() > 0)]
    market_total = float(stock_df["turnover"].sum())
    sector_sum = float(sector_df["turnover"].sum()) if not sector_df.empty else 0.0
    ratio = sector_sum / market_total if market_total else 0.0

    print("\n========== 校验报告 ==========")
    print(f"trade_date:           {trade_date}")
    print(f"行业分类条数:         {len(sectors_df)}")
    print(f"映射股票数:           {len(mapping_df)}")
    print(f"有行情股票数:         {len(stock_df)}")
    print(f"有行业归属:           {len(mapped)}")
    print(f"未归类股票数:         {len(unmapped_df)}")
    print(f"一级行业数:           {len(sector_df)}")
    print(f"大盘成交额:           {market_total:,.0f} 元")
    print(f"行业成交额合计:       {sector_sum:,.0f} 元")
    print(f"行业/大盘:            {ratio:.2%}")


def main() -> int:
    args = parse_args()
    industry: IndustryStd = args.industry
    snapshot_time = infer_snapshot_time()

    try:
        ensure_auth()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        trade_date = resolve_trade_date(args.trade_date)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        print(
            "提示: 若报「请先申请SDK使用权限」，请到 BigQuant 个人中心开通 SDK 权限。",
            file=sys.stderr,
        )
        return 1

    print(f"拉取 trade_date = {trade_date}（BigQuant / {industry}）...")

    try:
        print("  ① 行业分类明细...")
        sectors_df = fetch_sectors(industry)
        print(f"     分类条数: {len(sectors_df)}")

        print("  ② 板块 ↔ 个股映射...")
        mapping_df = fetch_sector_mapping(trade_date, industry)
        print(f"     映射股票数: {len(mapping_df)}")

        print("  ③ 个股成交额...")
        turnover_df = fetch_stock_turnover(trade_date)
        print(f"     有行情: {len(turnover_df)}")

        stock_df = attach_industry(turnover_df, mapping_df)
        stock_df.insert(0, "snapshot_time", snapshot_time.isoformat())

        mapped_codes = set(mapping_df["stock_code"])
        unmapped_df = stock_df[~stock_df["stock_code"].isin(mapped_codes)].copy()
        sector_df = aggregate_sector_turnover(stock_df, level=1)
        sector_df.insert(0, "trade_date", trade_date.isoformat())
        sector_df.insert(1, "snapshot_time", snapshot_time.isoformat())

        sectors_out = sectors_df.copy()
        sectors_out.insert(0, "snapshot_time", snapshot_time.isoformat())
        mapping_out = mapping_df.copy()
        mapping_out.insert(0, "snapshot_time", snapshot_time.isoformat())

        sectors_out.to_csv(DATA_DIR / "sectors.csv", index=False, encoding="utf-8")
        mapping_out.to_csv(DATA_DIR / "sector_stock_mapping.csv", index=False, encoding="utf-8")
        stock_df.to_csv(DATA_DIR / "stock_turnover_latest.csv", index=False, encoding="utf-8")
        sector_df.to_csv(DATA_DIR / "sector_turnover_daily.csv", index=False, encoding="utf-8")
        unmapped_df.to_csv(DATA_DIR / "unmapped_stocks.csv", index=False, encoding="utf-8")

        write_readme(
            trade_date.isoformat(),
            snapshot_time.isoformat(),
            industry,
            len(sectors_df),
            len(mapped_codes),
            len(unmapped_df),
        )
        print_validation(
            trade_date.isoformat(),
            sectors_df,
            mapping_df,
            stock_df,
            sector_df,
            unmapped_df,
        )
        print(f"\n数据已写入: {DATA_DIR}")
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        print(
            "提示: 若报「请先申请SDK使用权限」，请到 BigQuant 个人中心开通 SDK 权限。",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
