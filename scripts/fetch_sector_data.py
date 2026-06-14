#!/usr/bin/env python3
"""从 StockAPI 拉取东财行业板块分类、映射与最近交易日个股成交额。

输出（data/）：
  - sectors.csv                 全量行业板块列表
  - sector_stock_mapping.csv    板块 ↔ 个股映射（一对多，一只股票可出现在多个板块）
  - stock_turnover_latest.csv   最近交易日个股成交额 + 主行业归属
  - unmapped_stocks.csv         全 A 中有、但不在任何行业板块成份中的股票

认证：
  export STOCKAPI_TOKEN=你的token

建议在交易日 15:30 后执行（dayAll 当日增量数据更新时间）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sa_common import (
    build_sector_stock_mapping,
    fetch_all_stocks,
    fetch_day_all,
    fetch_sectors,
    get_token,
    infer_snapshot_time,
    pick_primary_sector,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="StockAPI 行业板块分类 + 最近交易日成交额")
    parser.add_argument(
        "--refresh-mapping",
        action="store_true",
        help="强制重新拉取全部板块成份（默认使用缓存）",
    )
    return parser.parse_args()


def load_or_build_mapping(token: str, sectors_df: pd.DataFrame, refresh: bool) -> pd.DataFrame:
    cache = DATA_DIR / "cache" / "sector_stock_mapping.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not refresh and cache.exists():
        print(f"     使用缓存: {cache}")
        return pd.DataFrame(json.loads(cache.read_text(encoding="utf-8")))
    mapping_df = build_sector_stock_mapping(token, sectors_df)
    cache.write_text(mapping_df.to_json(orient="records", force_ascii=False), encoding="utf-8")
    return mapping_df


def write_readme(trade_date: str, snapshot_time: str, sector_count: int, mapped: int, unmapped: int) -> None:
    readme = f"""# 数据说明（StockAPI / 东财行业板块）

- **trade_date**: {trade_date}
- **snapshot_time**: {snapshot_time}
- **板块体系**: 东方财富行业板块（BK 代码），非申万 2021
- **成交额来源**: `/v1/base/dayAll` 的 `amount` 字段
- **板块数**: {sector_count}
- **有行业归属**: {mapped}
- **未归类**: {unmapped}

## 文件

| 文件 | 说明 |
|------|------|
| sectors.csv | 全量行业板块列表 |
| sector_stock_mapping.csv | 板块与个股映射（多对多） |
| stock_turnover_latest.csv | 最近交易日个股成交额 + 主行业 |
| unmapped_stocks.csv | 全 A 中未出现在任何行业板块成份的股票 |
"""
    (DATA_DIR / "README.md").write_text(readme, encoding="utf-8")


def print_validation(
    trade_date: str,
    sectors_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    all_stocks_df: pd.DataFrame,
    stock_df: pd.DataFrame,
    unmapped_df: pd.DataFrame,
) -> None:
    mapped_codes = set(mapping_df["stock_code"])
    all_codes = set(all_stocks_df["stock_code"])
    turnover_codes = set(stock_df["stock_code"])

    print("\n========== 校验报告 ==========")
    print(f"trade_date:           {trade_date}")
    print(f"行业板块数:           {len(sectors_df)}")
    print(f"映射记录数:           {len(mapping_df)}（含重复归属）")
    print(f"映射涉及股票数:       {len(mapped_codes)}")
    print(f"全 A 股票数:          {len(all_codes)}")
    print(f"有成交额股票数:       {len(turnover_codes)}")
    print(f"未归类股票数:         {len(unmapped_df)}")
    if not unmapped_df.empty:
        top = unmapped_df.sort_values("turnover", ascending=False).head(5)
        print("未归类 Top5（按成交额）:")
        for _, row in top.iterrows():
            print(f"  {row['stock_code']} {row.get('stock_name', '')} {row.get('turnover', 0):,.0f}")


def main() -> int:
    args = parse_args()
    snapshot_time = infer_snapshot_time()

    try:
        token = get_token()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("拉取 StockAPI 东财行业板块数据...")

    print("  ① 行业板块列表...")
    sectors_df = fetch_sectors(token)
    print(f"     板块数: {len(sectors_df)}")

    print("  ② 板块 ↔ 个股映射...")
    mapping_df = load_or_build_mapping(token, sectors_df, refresh=args.refresh_mapping)
    mapping_df.to_csv(DATA_DIR / "sector_stock_mapping.csv", index=False, encoding="utf-8")
    print(f"     映射记录: {len(mapping_df)}")

    print("  ③ 全 A 股列表（用于校验遗漏）...")
    all_stocks_df = fetch_all_stocks(token)
    print(f"     全 A: {len(all_stocks_df)}")

    print("  ④ 最近交易日成交额...")
    turnover_df = fetch_day_all(token)
    if turnover_df.empty:
        print("错误: 无成交额数据", file=sys.stderr)
        return 1
    trade_date = str(turnover_df["trade_date"].iloc[0])
    print(f"     trade_date: {trade_date}, 有行情: {len(turnover_df)}")

    primary_df = pick_primary_sector(mapping_df)
    names_df = all_stocks_df[["stock_code", "stock_name"]].drop_duplicates("stock_code")
    stock_df = turnover_df.merge(names_df, on="stock_code", how="left")
    stock_df = stock_df.merge(
        primary_df[["stock_code", "sector_code", "sector_name"]],
        on="stock_code",
        how="left",
    )
    stock_df.insert(0, "snapshot_time", snapshot_time.isoformat())
    stock_df = stock_df.rename(columns={"sector_code": "primary_sector_code", "sector_name": "primary_sector_name"})

    mapped_codes = set(mapping_df["stock_code"])
    unmapped = all_stocks_df[~all_stocks_df["stock_code"].isin(mapped_codes)].copy()
    unmapped = unmapped.merge(turnover_df[["stock_code", "turnover", "volume", "trade_date"]], on="stock_code", how="left")
    unmapped.insert(0, "snapshot_time", snapshot_time.isoformat())

    sectors_out = sectors_df.copy()
    sectors_out.insert(0, "snapshot_time", snapshot_time.isoformat())
    mapping_out = mapping_df.copy()
    mapping_out.insert(0, "snapshot_time", snapshot_time.isoformat())

    sectors_out.to_csv(DATA_DIR / "sectors.csv", index=False, encoding="utf-8")
    mapping_out.to_csv(DATA_DIR / "sector_stock_mapping.csv", index=False, encoding="utf-8")
    stock_df.to_csv(DATA_DIR / "stock_turnover_latest.csv", index=False, encoding="utf-8")
    unmapped.to_csv(DATA_DIR / "unmapped_stocks.csv", index=False, encoding="utf-8")

    write_readme(trade_date, snapshot_time.isoformat(), len(sectors_df), len(mapped_codes), len(unmapped))
    print_validation(trade_date, sectors_df, mapping_df, all_stocks_df, stock_df, unmapped)

    print(f"\n数据已写入: {DATA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
