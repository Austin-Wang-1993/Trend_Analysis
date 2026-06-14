#!/usr/bin/env python3
"""从必盈 API 拉取申万行业分类、板块映射与最近交易日个股成交额。

输出（data/）：
  - sectors.csv                 申万行业列表（hslt/primarylist）
  - sector_stock_mapping.csv    板块 ↔ 个股映射（hslt/sectors）
  - stock_turnover_latest.csv   个股成交额 + 主行业归属
  - sector_turnover_daily.csv   一级行业成交额汇总
  - unmapped_stocks.csv         全 A 中未出现在映射里的股票

认证：
  export BIYING_LICENCE=你的licence

文档：https://www.biyingapi.com/doc_hs
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from by_common import (
    TYPE2_SW_L1,
    build_hslt_sector_mapping,
    fetch_hslt_sector_tree,
    fetch_stock_list,
    fetch_turnover,
    get_licence,
    infer_snapshot_time,
    pick_primary_sector,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="必盈 API 行业板块 + 成交额采集（hslt 路由）")
    parser.add_argument(
        "--level",
        choices=["l1"],
        default="l1",
        help="申万层级（当前仅支持一级，来自 hslt/primarylist 的 1000SW1*）",
    )
    parser.add_argument(
        "--refresh-mapping",
        action="store_true",
        help="强制重新拉取板块成份（默认使用缓存）",
    )
    parser.add_argument(
        "--no-all-turnover",
        action="store_true",
        help="不使用全市场成交额接口，改用 ssjy_more 批量拉取",
    )
    parser.add_argument(
        "--turnover-only",
        action="store_true",
        help="仅拉取成交额（使用已缓存的行业树与映射）",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="清空 data/ 下 CSV 后全量重拉（隐含 --refresh-mapping）",
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="与 --fresh 联用：仅清 CSV，保留 data/cache/ 行业树与映射缓存",
    )
    return parser.parse_args()


def clear_data_dir(data_dir: Path, *, keep_cache: bool = False) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    removed = 0
    for pattern in ("*.csv", "README.md"):
        for path in data_dir.glob(pattern):
            path.unlink()
            removed += 1
    cache_dir = data_dir / "cache"
    if not keep_cache and cache_dir.exists():
        shutil.rmtree(cache_dir)
        removed += 1
    scope = "CSV" if keep_cache else "CSV 与 cache"
    print(f"已清空 data/ {scope}（移除 {removed} 项）")


def load_or_build_tree(licence: str, cache_path: Path, refresh: bool, level: str) -> pd.DataFrame:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not refresh and cache_path.exists():
        print(f"     使用缓存: {cache_path}")
        return pd.DataFrame(json.loads(cache_path.read_text(encoding="utf-8")))
    tree_df = fetch_hslt_sector_tree(licence, level)
    cache_path.write_text(tree_df.to_json(orient="records", force_ascii=False), encoding="utf-8")
    return tree_df


def load_or_build_mapping(
    licence: str,
    sectors_df: pd.DataFrame,
    refresh: bool,
    cache_name: str,
) -> pd.DataFrame:
    cache = DATA_DIR / "cache" / cache_name
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not refresh and cache.exists():
        print(f"     使用缓存: {cache}")
        return pd.DataFrame(json.loads(cache.read_text(encoding="utf-8")))
    mapping_df = build_hslt_sector_mapping(licence, sectors_df)
    cache.write_text(mapping_df.to_json(orient="records", force_ascii=False), encoding="utf-8")
    return mapping_df


def aggregate_sector_turnover(stock_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        stock_df.groupby(["sector_code", "sector_name"], dropna=False)["turnover"]
        .agg(turnover="sum", stock_count="count")
        .reset_index()
    )
    grouped = grouped[grouped["sector_code"].astype(str).str.len() > 0]
    return grouped.sort_values("turnover", ascending=False).reset_index(drop=True)


def write_readme(
    trade_date: str,
    snapshot_time: str,
    sector_count: int,
    mapped: int,
    unmapped: int,
) -> None:
    readme = f"""# 数据说明（必盈 API / hslt 路由）

- **trade_date**: {trade_date}
- **snapshot_time**: {snapshot_time}
- **板块体系**: 申万一级（hslt/primarylist 前缀 1000SW1）
- **映射来源**: hslt/sectors/{{板块名称}}
- **成交额来源**: hsrl/ssjy/all 或 hsrl/ssjy_more 的 `cje` 字段
- **板块数**: {sector_count}
- **映射覆盖**: {mapped}
- **未归类**: {unmapped}
"""
    (DATA_DIR / "README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.fresh and args.turnover_only:
        print("错误: --fresh 与 --turnover-only 不能同时使用", file=sys.stderr)
        return 1
    if args.keep_cache and not args.fresh:
        print("错误: --keep-cache 需与 --fresh 一起使用", file=sys.stderr)
        return 1
    if args.fresh:
        args.refresh_mapping = not args.keep_cache

    snapshot_time = infer_snapshot_time()

    try:
        licence = get_licence()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        clear_data_dir(DATA_DIR, keep_cache=args.keep_cache)

    cache_name = f"sector_mapping_{args.level}.json"
    tree_cache = DATA_DIR / "cache" / "sector_tree.json"

    print("拉取必盈 API 数据...")

    try:
        print("  ① 全 A 股票列表 (hslt/list)...")
        stocks_df = fetch_stock_list(licence)
        print(f"     全 A: {len(stocks_df)}")

        if args.turnover_only:
            mapping_cache = DATA_DIR / "cache" / cache_name
            if not mapping_cache.exists():
                print(f"错误: 找不到映射缓存 {mapping_cache}，请先完整跑一遍采集", file=sys.stderr)
                return 1
            print("  ②③ 跳过（--turnover-only，使用缓存）...")
            mapping_df = pd.DataFrame(json.loads(mapping_cache.read_text(encoding="utf-8")))
            tree_df = (
                pd.DataFrame(json.loads(tree_cache.read_text(encoding="utf-8")))
                if tree_cache.exists()
                else mapping_df[["sector_code", "sector_name"]].drop_duplicates("sector_code").rename(
                    columns={"sector_code": "code", "sector_name": "name"}
                )
            )
            sectors_df = tree_df
            print(f"     映射记录: {len(mapping_df)}")
        else:
            print("  ② 申万行业列表 (hslt/primarylist)...")
            tree_df = load_or_build_tree(licence, tree_cache, args.refresh_mapping, args.level)
            sectors_df = tree_df
            print(f"     目标板块数: {len(sectors_df)}")

            print("  ③ 板块 ↔ 个股映射 (hslt/sectors)...")
            mapping_df = load_or_build_mapping(licence, sectors_df, args.refresh_mapping, cache_name)
            print(f"     映射记录: {len(mapping_df)}")

        print("  ④ 个股成交额 (hsrl/ssjy_more)...")
        turnover_df = fetch_turnover(
            licence,
            stocks_df["stock_code"].tolist(),
            prefer_all=not args.no_all_turnover,
        )
        trade_date = str(turnover_df["trade_date"].iloc[0])
        print(f"     trade_date: {trade_date}, 有行情: {len(turnover_df)}")

        primary_df = pick_primary_sector(mapping_df, type2=TYPE2_SW_L1)
        stock_df = turnover_df.merge(stocks_df, on="stock_code", how="left")
        stock_df = stock_df.merge(
            primary_df[["stock_code", "sector_code", "sector_name"]],
            on="stock_code",
            how="left",
        )
        stock_df.insert(0, "snapshot_time", snapshot_time.isoformat())

        mapped_codes = set(mapping_df["stock_code"])
        unmapped_df = stocks_df[~stocks_df["stock_code"].isin(mapped_codes)].copy()
        unmapped_df = unmapped_df.merge(
            turnover_df[["stock_code", "turnover", "volume", "trade_date"]],
            on="stock_code",
            how="left",
        )
        unmapped_df.insert(0, "snapshot_time", snapshot_time.isoformat())

        sector_df = aggregate_sector_turnover(stock_df.dropna(subset=["sector_code"]))
        sector_df.insert(0, "trade_date", trade_date)
        sector_df.insert(1, "snapshot_time", snapshot_time.isoformat())

        tree_out = tree_df.copy()
        tree_out.insert(0, "snapshot_time", snapshot_time.isoformat())
        mapping_out = mapping_df.copy()
        mapping_out.insert(0, "snapshot_time", snapshot_time.isoformat())

        tree_out.to_csv(DATA_DIR / "sectors.csv", index=False, encoding="utf-8")
        mapping_out.to_csv(DATA_DIR / "sector_stock_mapping.csv", index=False, encoding="utf-8")
        stock_df.to_csv(DATA_DIR / "stock_turnover_latest.csv", index=False, encoding="utf-8")
        sector_df.to_csv(DATA_DIR / "sector_turnover_daily.csv", index=False, encoding="utf-8")
        unmapped_df.to_csv(DATA_DIR / "unmapped_stocks.csv", index=False, encoding="utf-8")

        write_readme(trade_date, snapshot_time.isoformat(), len(sectors_df), len(mapped_codes), len(unmapped_df))

        market_total = float(stock_df["turnover"].sum())
        sector_sum = float(sector_df["turnover"].sum()) if not sector_df.empty else 0.0
        unmapped_with_turnover = unmapped_df["turnover"].notna().sum()
        print("\n========== 校验报告 ==========")
        print(f"trade_date:       {trade_date}")
        print(f"全 A 股票数:      {len(stocks_df)}")
        print(f"映射涉及股票:     {len(mapped_codes)}")
        print(f"未归类:           {len(unmapped_df)}")
        print(f"未归类且有成交额: {unmapped_with_turnover}")
        print(f"有成交额:         {len(turnover_df)}")
        print(f"大盘成交额:       {market_total:,.0f} 元")
        if market_total:
            print(f"行业合计:         {sector_sum:,.0f} 元 ({sector_sum / market_total:.2%})")

        print(f"\n数据已写入: {DATA_DIR}")
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
