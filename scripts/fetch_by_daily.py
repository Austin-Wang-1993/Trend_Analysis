#!/usr/bin/env python3
"""从必盈 API 拉取申万行业分类、板块映射与最近交易日个股成交额。

输出（data/）：
  - sectors.csv                 全量行业/概念分类树（hszg/list）
  - sector_stock_mapping.csv    板块 ↔ 个股映射（hszg/gg）
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
    TYPE2_SW_L2,
    build_sector_mapping,
    fetch_sector_tree,
    fetch_stock_list,
    fetch_turnover,
    filter_sectors,
    get_licence,
    infer_snapshot_time,
    pick_primary_sector,
)
from mapping_fallback import build_tickflow_mapping

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="必盈 API 行业板块 + 成交额采集")
    parser.add_argument(
        "--level",
        choices=["l1", "l2", "both"],
        default="l1",
        help="映射使用的申万层级（默认一级）",
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
        help="仅拉取成交额（使用已缓存的行业树与映射，跳过重试失败接口）",
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
    parser.add_argument(
        "--mapping-source",
        choices=["auto", "biying", "tickflow"],
        default="auto",
        help="行业映射来源：auto=必盈优先、hszg 失败时回退 TickFlow（默认）",
    )
    return parser.parse_args()


def clear_data_dir(data_dir: Path, *, keep_cache: bool = False) -> None:
    """删除输出 CSV、README；可选是否删除 cache 缓存。"""
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


def sectors_for_level(tree_df: pd.DataFrame, level: str) -> pd.DataFrame:
    if level == "l1":
        return filter_sectors(tree_df, type2=TYPE2_SW_L1)
    if level == "l2":
        return filter_sectors(tree_df, type2=TYPE2_SW_L2)
    l1 = filter_sectors(tree_df, type2=TYPE2_SW_L1)
    l2 = filter_sectors(tree_df, type2=TYPE2_SW_L2)
    return pd.concat([l1, l2], ignore_index=True).drop_duplicates("code")


def load_or_build_tree(
    licence: str,
    cache_path: Path,
    refresh: bool,
) -> pd.DataFrame:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not refresh and cache_path.exists():
        print(f"     使用缓存: {cache_path}")
        return pd.DataFrame(json.loads(cache_path.read_text(encoding="utf-8")))
    try:
        tree_df = fetch_sector_tree(licence)
    except Exception as exc:
        if cache_path.exists():
            print(f"     在线拉取失败，回退缓存: {exc}")
            return pd.DataFrame(json.loads(cache_path.read_text(encoding="utf-8")))
        raise
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
    mapping_df = build_sector_mapping(licence, sectors_df)
    cache.write_text(mapping_df.to_json(orient="records", force_ascii=False), encoding="utf-8")
    return mapping_df


def load_tickflow_sector_data(level: str, refresh: bool, cache_name: str, tree_cache: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mapping_cache = DATA_DIR / "cache" / cache_name
    meta_cache = DATA_DIR / "cache" / f"mapping_source_{level}.json"
    mapping_cache.parent.mkdir(parents=True, exist_ok=True)
    if not refresh and mapping_cache.exists() and tree_cache.exists():
        print(f"     使用缓存: {mapping_cache}")
        tree_df = pd.DataFrame(json.loads(tree_cache.read_text(encoding="utf-8")))
        mapping_df = pd.DataFrame(json.loads(mapping_cache.read_text(encoding="utf-8")))
    else:
        tree_df, mapping_df = build_tickflow_mapping(level)
        tree_cache.write_text(tree_df.to_json(orient="records", force_ascii=False), encoding="utf-8")
        mapping_cache.write_text(mapping_df.to_json(orient="records", force_ascii=False), encoding="utf-8")
        meta_cache.write_text(json.dumps({"source": "tickflow"}, ensure_ascii=False), encoding="utf-8")
    sectors_df = sectors_for_level(tree_df, level) if "type2" in tree_df.columns else pd.DataFrame()
    return tree_df, sectors_df, mapping_df


def load_biying_sector_data(
    licence: str,
    level: str,
    refresh: bool,
    cache_name: str,
    tree_cache: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print("  ② 行业/概念分类树...")
    tree_df = load_or_build_tree(licence, tree_cache, refresh=refresh)
    sectors_df = sectors_for_level(tree_df, level)
    print(f"     目标板块数: {len(sectors_df)}")
    print("  ③ 板块 ↔ 个股映射...")
    mapping_df = load_or_build_mapping(licence, sectors_df, refresh, cache_name)
    meta_cache = DATA_DIR / "cache" / f"mapping_source_{level}.json"
    meta_cache.write_text(json.dumps({"source": "biying"}, ensure_ascii=False), encoding="utf-8")
    return tree_df, sectors_df, mapping_df


def load_sector_data(
    licence: str,
    level: str,
    refresh: bool,
    cache_name: str,
    tree_cache: Path,
    mapping_source: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    mapping_cache = DATA_DIR / "cache" / cache_name
    meta_cache = DATA_DIR / "cache" / f"mapping_source_{level}.json"

    if mapping_source == "tickflow":
        tree_df, sectors_df, mapping_df = load_tickflow_sector_data(level, refresh, cache_name, tree_cache)
        return tree_df, sectors_df, mapping_df, "tickflow"

    try:
        tree_df, sectors_df, mapping_df = load_biying_sector_data(
            licence, level, refresh, cache_name, tree_cache
        )
        return tree_df, sectors_df, mapping_df, "biying"
    except Exception as exc:
        if mapping_source == "biying":
            raise
        if mapping_cache.exists() and not refresh:
            print(f"     ②③ 必盈接口失败，改用映射缓存: {exc}")
            mapping_df = pd.DataFrame(json.loads(mapping_cache.read_text(encoding="utf-8")))
            if tree_cache.exists():
                tree_df = pd.DataFrame(json.loads(tree_cache.read_text(encoding="utf-8")))
            else:
                tree_df = pd.DataFrame(
                    mapping_df[
                        ["sector_code", "sector_name", "sector_type2", "sector_level", "parent_code", "parent_name"]
                    ]
                    .drop_duplicates("sector_code")
                    .rename(columns={"sector_code": "code", "sector_name": "name"})
                )
            sectors_df = (
                sectors_for_level(tree_df, level)
                if "type2" in tree_df.columns
                else mapping_df[["sector_code", "sector_name"]].drop_duplicates()
            )
            source = "cache"
            if meta_cache.exists():
                source = json.loads(meta_cache.read_text(encoding="utf-8")).get("source", source)
            return tree_df, sectors_df, mapping_df, source
        print(f"     ②③ 必盈 hszg 失败: {exc}")
        tree_df, sectors_df, mapping_df = load_tickflow_sector_data(level, refresh=True, cache_name=cache_name, tree_cache=tree_cache)
        return tree_df, sectors_df, mapping_df, "tickflow"


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
    level: str,
    mapping_source: str,
) -> None:
    mapping_desc = {
        "biying": "必盈 hszg/list + hszg/gg（每周六更新）",
        "tickflow": "TickFlow 申万标的池（hszg 不可用时的回退）",
        "cache": "本地缓存（上次成功来源见 mapping_source_*.json）",
    }.get(mapping_source, mapping_source)
    readme = f"""# 数据说明（必盈 API）

- **trade_date**: {trade_date}
- **snapshot_time**: {snapshot_time}
- **板块体系**: 申万行业（type2={level}）
- **映射来源**: {mapping_desc}
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
        print("  ① 股票列表...")
        stocks_df = fetch_stock_list(licence)
        print(f"     全 A: {len(stocks_df)}")

        mapping_source = "biying"
        if args.turnover_only:
            mapping_cache = DATA_DIR / "cache" / cache_name
            if not mapping_cache.exists():
                print(f"错误: 找不到映射缓存 {mapping_cache}，请先完整跑一遍采集", file=sys.stderr)
                return 1
            print("  ②③ 跳过（--turnover-only，使用缓存）...")
            mapping_df = pd.DataFrame(json.loads(mapping_cache.read_text(encoding="utf-8")))
            if tree_cache.exists():
                tree_df = pd.DataFrame(json.loads(tree_cache.read_text(encoding="utf-8")))
            else:
                tree_df = pd.DataFrame(
                    mapping_df[["sector_code", "sector_name", "sector_type2", "sector_level", "parent_code", "parent_name"]]
                    .drop_duplicates("sector_code")
                    .rename(columns={"sector_code": "code", "sector_name": "name"})
                )
            sectors_df = sectors_for_level(tree_df, args.level) if "type2" in tree_df.columns else pd.DataFrame()
            meta_cache = DATA_DIR / "cache" / f"mapping_source_{args.level}.json"
            if meta_cache.exists():
                mapping_source = json.loads(meta_cache.read_text(encoding="utf-8")).get("source", "cache")
            print(f"     映射记录: {len(mapping_df)}")
        else:
            tree_df, sectors_df, mapping_df, mapping_source = load_sector_data(
                licence,
                args.level,
                args.refresh_mapping,
                cache_name,
                tree_cache,
                args.mapping_source,
            )
            print(f"     映射来源: {mapping_source}")
            print(f"     映射记录: {len(mapping_df)}")

        print("  ④ 个股成交额...")
        turnover_df = fetch_turnover(
            licence,
            stocks_df["stock_code"].tolist(),
            prefer_all=not args.no_all_turnover,
        )
        trade_date = str(turnover_df["trade_date"].iloc[0])
        print(f"     trade_date: {trade_date}, 有行情: {len(turnover_df)}")

        primary_type2 = TYPE2_SW_L1 if args.level in {"l1", "both"} else TYPE2_SW_L2
        primary_df = pick_primary_sector(mapping_df, type2=primary_type2)
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

        sector_df = aggregate_sector_turnover(
            stock_df.dropna(subset=["sector_code"]).rename(
                columns={"sector_code": "sector_code", "sector_name": "sector_name"}
            )
        )
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

        sector_count = (
            len(sectors_df)
            if isinstance(sectors_df, pd.DataFrame) and len(sectors_df)
            else mapping_df["sector_code"].nunique()
        )
        write_readme(
            trade_date,
            snapshot_time.isoformat(),
            sector_count,
            len(mapped_codes),
            len(unmapped_df),
            args.level,
            mapping_source,
        )

        market_total = float(stock_df["turnover"].sum())
        sector_sum = float(sector_df["turnover"].sum()) if not sector_df.empty else 0.0
        print("\n========== 校验报告 ==========")
        print(f"trade_date:       {trade_date}")
        print(f"全 A 股票数:      {len(stocks_df)}")
        print(f"映射涉及股票:     {len(mapped_codes)}")
        print(f"未归类:           {len(unmapped_df)}")
        print(f"有成交额:         {len(turnover_df)}")
        print(f"大盘成交额:       {market_total:,.0f} 元")
        print(f"行业合计:         {sector_sum:,.0f} 元 ({sector_sum/market_total:.2%})" if market_total else "")

        print(f"\n数据已写入: {DATA_DIR}")
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        if "hszg" in str(exc).lower() or "行业" in str(exc) or "tickflow" in str(exc).lower():
            print(
                "\n提示: 可安装 tickflow 后使用自动回退：pip install tickflow\n"
                "  python3 scripts/fetch_by_daily.py --fresh --no-all-turnover\n"
                "或强制 TickFlow 映射：--mapping-source tickflow",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
