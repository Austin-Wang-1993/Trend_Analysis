#!/usr/bin/env python3
"""仅拉取/刷新申万板块 ↔ 个股映射缓存（不拉成交/买卖/ETF）。

用于首次生成 sector_mapping_l2.json，或 L1→L2 迁移前准备。
约 2–3 分钟（131 个二级板块 × hszg/gg）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from by_common import build_sector_mapping, ensure_stock_codes, get_licence, pick_primary_sector
from fetch_by_daily import DATA_DIR, load_or_build_tree, sectors_for_level
from sector_config import DEFAULT_SECTOR_LEVEL, mapping_cache_name, primary_type2_for_level


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="仅构建申万板块映射缓存")
    p.add_argument("--level", choices=["l1", "l2"], default=DEFAULT_SECTOR_LEVEL)
    p.add_argument(
        "--refresh",
        action="store_true",
        help="强制重新拉取 hszg/gg（默认：缓存已存在则跳过）",
    )
    p.add_argument(
        "--refresh-tree",
        action="store_true",
        help="同时重新拉取 hszg/list 行业树",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        licence = get_licence()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    cache_path = DATA_DIR / "cache" / mapping_cache_name(args.level)
    tree_cache = DATA_DIR / "cache" / "sector_tree.json"

    if cache_path.exists() and not args.refresh:
        df = ensure_stock_codes(pd.DataFrame(json.loads(cache_path.read_text(encoding="utf-8"))))
        print(f"已存在 {cache_path}（{len(df)} 条，{df['sector_code'].nunique()} 板块），使用 --refresh 强制重拉")
        return 0

    if not tree_cache.exists() and not args.refresh_tree:
        print(
            f"错误: 缺少 {tree_cache}，请先运行完整采集或加 --refresh-tree",
            file=sys.stderr,
        )
        return 1

    print(f"构建申万 {args.level} 映射...")
    tree_df = load_or_build_tree(licence, tree_cache, args.refresh or args.refresh_tree)
    sectors_df = sectors_for_level(tree_df, args.level)
    print(f"  目标板块: {len(sectors_df)}")

    mapping_df = ensure_stock_codes(build_sector_mapping(licence, sectors_df))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(mapping_df.to_json(orient="records", force_ascii=False), encoding="utf-8")

    primary = pick_primary_sector(mapping_df, type2=primary_type2_for_level(args.level))
    print(f"  已写入: {cache_path}")
    print(f"  映射记录: {len(mapping_df)}，覆盖股票: {len(primary)}，板块数: {primary['sector_code'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
