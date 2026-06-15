#!/usr/bin/env python3
"""从必盈 API 拉取申万行业分类、板块映射、个股/ETF 成交与买卖数据。

输出（data/）：
  - sectors.csv                 全量行业/概念分类树（hszg/list）
  - sector_stock_mapping.csv    板块 ↔ 个股映射（hszg/gg）
  - stock_turnover_latest.csv   个股成交额 + 主买/主卖 + 主行业归属
  - sector_turnover_daily.csv   申万二级行业成交额汇总
  - sector_fund_flow_daily.csv  申万二级行业买卖汇总
  - market_summary_daily.csv    全 A 成交 + 买卖汇总
  - etf_turnover_latest.csv     ETF 成交额（必盈暂无 ETF 买卖拆分）
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
    aggregate_market_summary,
    aggregate_sector_fund_flow,
    build_sector_mapping,
    ensure_stock_codes,
    fetch_etf_list,
    fetch_etf_turnover_batch,
    fetch_fund_flow_batch,
    fetch_sector_tree,
    fetch_stock_list,
    fetch_turnover,
    filter_sectors,
    get_licence,
    infer_snapshot_time,
    pick_primary_sector,
)

from sector_config import DEFAULT_SECTOR_LEVEL, primary_type2_for_level
from history_store import HistoryStore

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="必盈 API 行业板块 + 成交额采集")
    parser.add_argument(
        "--level",
        choices=["l1", "l2", "both"],
        default="l2",
        help="映射使用的申万层级（默认二级 l2）",
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
        help="仅拉取成交额（使用已缓存的行业树与映射，跳过资金流与 ETF）",
    )
    parser.add_argument(
        "--no-fund-flow",
        action="store_true",
        help="跳过个股/板块/全市场买卖数据（history/transaction，约 5200 次请求）",
    )
    parser.add_argument(
        "--no-etf",
        action="store_true",
        help="跳过 ETF 成交额（fd/real/time，约 1500 次请求）",
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
        "--no-db",
        action="store_true",
        help="跳过写入 SQLite history.db",
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


def sectors_for_level(tree_df: pd.DataFrame, level: str) -> pd.DataFrame:
    if level == "l1":
        return filter_sectors(tree_df, type2=TYPE2_SW_L1)
    if level == "l2":
        return filter_sectors(tree_df, type2=TYPE2_SW_L2)
    l1 = filter_sectors(tree_df, type2=TYPE2_SW_L1)
    l2 = filter_sectors(tree_df, type2=TYPE2_SW_L2)
    return pd.concat([l1, l2], ignore_index=True).drop_duplicates("code")


def load_or_build_tree(licence: str, cache_path: Path, refresh: bool) -> pd.DataFrame:
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
    *,
    fund_flow: bool,
    etf_count: int,
    etf_trade_date: str,
) -> None:
    ff_line = (
        "- **买卖来源**: hsstock/history/transaction 主买/主卖（每日 21:30 更新）\n"
        if fund_flow
        else "- **买卖数据**: 未采集（使用了 --no-fund-flow 或 --turnover-only）\n"
    )
    etf_line = (
        f"- **ETF**: fd/list/etf + fd/real/time，共 {etf_count} 只，trade_date={etf_trade_date}\n"
        f"- **ETF 买卖**: 必盈暂无 ETF 资金流向接口，仅提供成交额\n"
        if etf_count
        else "- **ETF**: 未采集\n"
    )
    readme = f"""# 数据说明（必盈 API）

- **trade_date**: {trade_date}
- **snapshot_time**: {snapshot_time}
- **板块体系**: 申万行业（hszg/list, type2={level}）
- **映射来源**: hszg/gg（每周六更新）
- **成交额来源**: hsrl/ssjy/all 或 hsrl/ssjy_more 的 `cje` 字段
{ff_line}{etf_line}- **板块数**: {sector_count}
- **映射覆盖**: {mapped}
- **未归类**: {unmapped}

## 查看层级

| 层级 | 成交 | 买入/卖出 |
|------|------|-----------|
| 全 A | market_summary_daily.csv | 同上（active_buy / active_sell / net_active） |
| 申万板块 | sector_turnover_daily.csv + sector_fund_flow_daily.csv | sector_fund_flow_daily.csv |
| 个股 | stock_turnover_latest.csv | 同上列 |
| ETF | etf_turnover_latest.csv | 暂无（仅 turnover） |
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

    include_fund_flow = not args.no_fund_flow and not args.turnover_only
    include_etf = not args.no_etf and not args.turnover_only

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
        print("  ① 股票列表 (hslt/list)...")
        stocks_df = fetch_stock_list(licence)
        print(f"     全 A: {len(stocks_df)}")

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
                    mapping_df[
                        ["sector_code", "sector_name", "sector_type2", "sector_level", "parent_code", "parent_name"]
                    ]
                    .drop_duplicates("sector_code")
                    .rename(columns={"sector_code": "code", "sector_name": "name"})
                )
            sectors_df = sectors_for_level(tree_df, args.level) if "type2" in tree_df.columns else pd.DataFrame()
            print(f"     映射记录: {len(mapping_df)}")
        else:
            print("  ② 行业/概念分类树 (hszg/list)...")
            tree_df = load_or_build_tree(licence, tree_cache, args.refresh_mapping)
            sectors_df = sectors_for_level(tree_df, args.level)
            print(f"     目标板块数: {len(sectors_df)}")

            print("  ③ 板块 ↔ 个股映射 (hszg/gg)...")
            mapping_df = load_or_build_mapping(licence, sectors_df, args.refresh_mapping, cache_name)
            print(f"     映射记录: {len(mapping_df)}")

        print("  ④ 个股成交额 (hsrl/ssjy_more)...")
        turnover_df = ensure_stock_codes(
            fetch_turnover(
                licence,
                stocks_df["stock_code"].tolist(),
                prefer_all=not args.no_all_turnover,
            )
        )
        stocks_df = ensure_stock_codes(stocks_df)
        mapping_df = ensure_stock_codes(mapping_df)
        trade_date = str(turnover_df["trade_date"].iloc[0])
        print(f"     trade_date: {trade_date}, 有行情: {len(turnover_df)}")

        fund_flow_df = pd.DataFrame()
        if include_fund_flow:
            print("  ⑤ 个股买卖/资金流 (hsstock/history/transaction)...")
            fund_flow_df = ensure_stock_codes(fetch_fund_flow_batch(licence, stocks_df["stock_code"].tolist()))
            ff_date = str(fund_flow_df["trade_date"].iloc[0]) if len(fund_flow_df) else trade_date
            print(f"     fund_flow trade_date: {ff_date}, 有数据: {len(fund_flow_df)}")
        else:
            print("  ⑤ 跳过资金流")

        primary_type2 = primary_type2_for_level(args.level if args.level != "both" else "l2")
        primary_df = pick_primary_sector(mapping_df, type2=primary_type2)
        stock_df = turnover_df.merge(stocks_df, on="stock_code", how="left")
        if include_fund_flow and not fund_flow_df.empty:
            stock_df = stock_df.merge(fund_flow_df, on="stock_code", how="left", suffixes=("", "_ff"))
            if "trade_date_ff" in stock_df.columns:
                stock_df["trade_date"] = stock_df["trade_date"].fillna(stock_df["trade_date_ff"])
                stock_df = stock_df.drop(columns=["trade_date_ff"])
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
        if include_fund_flow and not fund_flow_df.empty:
            ff_cols = [c for c in fund_flow_df.columns if c != "trade_date"]
            unmapped_df = unmapped_df.merge(fund_flow_df[ff_cols], on="stock_code", how="left")
        unmapped_df.insert(0, "snapshot_time", snapshot_time.isoformat())

        sector_df = aggregate_sector_turnover(stock_df.dropna(subset=["sector_code"]))
        sector_df.insert(0, "trade_date", trade_date)
        sector_df.insert(1, "snapshot_time", snapshot_time.isoformat())

        sector_ff_df = pd.DataFrame()
        if include_fund_flow:
            sector_ff_df = aggregate_sector_fund_flow(stock_df.dropna(subset=["sector_code"]))
            sector_ff_df.insert(0, "trade_date", trade_date)
            sector_ff_df.insert(1, "snapshot_time", snapshot_time.isoformat())

        market_df = pd.DataFrame()
        if include_fund_flow:
            market_row = aggregate_market_summary(stock_df)
            market_row["snapshot_time"] = snapshot_time.isoformat()
            market_df = pd.DataFrame([market_row])

        etf_df = pd.DataFrame()
        etf_trade_date = ""
        etf_count = 0
        if include_etf:
            print("  ⑥ ETF 列表与成交额 (fd/list/etf + fd/real/time)...")
            etf_list_df = fetch_etf_list(licence)
            etf_count = len(etf_list_df)
            print(f"     ETF 数量: {etf_count}")
            etf_turnover_df = fetch_etf_turnover_batch(licence, etf_list_df["etf_code"].tolist())
            etf_df = etf_list_df.merge(etf_turnover_df, on="etf_code", how="inner")
            etf_trade_date = str(etf_df["trade_date"].iloc[0]) if len(etf_df) else ""
            etf_df.insert(0, "snapshot_time", snapshot_time.isoformat())
            print(f"     ETF trade_date: {etf_trade_date}, 有行情: {len(etf_df)}")
        else:
            print("  ⑥ 跳过 ETF")

        tree_out = tree_df.copy()
        tree_out.insert(0, "snapshot_time", snapshot_time.isoformat())
        mapping_out = mapping_df.copy()
        mapping_out.insert(0, "snapshot_time", snapshot_time.isoformat())

        tree_out.to_csv(DATA_DIR / "sectors.csv", index=False, encoding="utf-8")
        mapping_out.to_csv(DATA_DIR / "sector_stock_mapping.csv", index=False, encoding="utf-8")
        stock_df.to_csv(DATA_DIR / "stock_turnover_latest.csv", index=False, encoding="utf-8")
        sector_df.to_csv(DATA_DIR / "sector_turnover_daily.csv", index=False, encoding="utf-8")
        if include_fund_flow and not sector_ff_df.empty:
            sector_ff_df.to_csv(DATA_DIR / "sector_fund_flow_daily.csv", index=False, encoding="utf-8")
        if include_fund_flow and not market_df.empty:
            market_df.to_csv(DATA_DIR / "market_summary_daily.csv", index=False, encoding="utf-8")
        if include_etf and not etf_df.empty:
            etf_df.to_csv(DATA_DIR / "etf_turnover_latest.csv", index=False, encoding="utf-8")
        unmapped_df.to_csv(DATA_DIR / "unmapped_stocks.csv", index=False, encoding="utf-8")

        sector_count = len(sectors_df) if len(sectors_df) else mapping_df["sector_code"].nunique()
        write_readme(
            trade_date,
            snapshot_time.isoformat(),
            sector_count,
            len(mapped_codes),
            len(unmapped_df),
            args.level,
            fund_flow=include_fund_flow,
            etf_count=etf_count if include_etf else 0,
            etf_trade_date=etf_trade_date,
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
        if market_total:
            print(f"行业合计:         {sector_sum:,.0f} 元 ({sector_sum / market_total:.2%})")
        if include_fund_flow and "net_active" in stock_df.columns:
            net = float(stock_df["net_active"].sum())
            buy = float(stock_df["active_buy"].sum())
            sell = float(stock_df["active_sell"].sum())
            print(f"全 A 主买:        {buy:,.0f} 元")
            print(f"全 A 主卖:        {sell:,.0f} 元")
            print(f"全 A 主买-主卖:   {net:,.0f} 元")
        if include_etf and not etf_df.empty:
            print(f"ETF 成交额合计:   {float(etf_df['turnover'].sum()):,.0f} 元 ({len(etf_df)} 只)")

        if not args.no_db:
            print("\n写入 SQLite history.db ...")
            store = HistoryStore(DB_PATH)
            market_row = None
            if include_fund_flow and not market_df.empty:
                market_row = market_df.iloc[0].to_dict()
            store.upsert_snapshot(
                trade_date=trade_date,
                stock_df=stock_df,
                sector_df=sector_df,
                sector_ff_df=sector_ff_df if include_fund_flow else None,
                market_row=market_row,
                etf_df=etf_df if include_etf else None,
                snapshot_time=snapshot_time.isoformat(),
            )
            print(f"     已落库 trade_date={trade_date}")

        print(f"\n数据已写入: {DATA_DIR}")
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
